import re
from math import cos, radians, sin

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator

from .forms import AccountForm, BudgetForm, TransactionForm
from .models import Account, Budget, Transaction, Holding, WatchlistEntry


SPENDING_CHART_COLORS = (
    "#d8bd82",
    "#9fbf9b",
    "#91b7c1",
    "#c69c8a",
    "#a99bc9",
    "#d28b9a",
    "#aeb7bd",
)


def _pie_slice_path(start_angle, end_angle, full_circle=False):
    if full_circle:
        return "M 100 10 A 90 90 0 1 1 100 190 A 90 90 0 1 1 100 10 Z"

    start_x = 100 + 90 * cos(radians(start_angle))
    start_y = 100 + 90 * sin(radians(start_angle))
    end_x = 100 + 90 * cos(radians(end_angle))
    end_y = 100 + 90 * sin(radians(end_angle))
    large_arc = 1 if end_angle - start_angle > 180 else 0
    return (
        f"M 100 100 L {start_x:.3f} {start_y:.3f} "
        f"A 90 90 0 {large_arc} 1 {end_x:.3f} {end_y:.3f} Z"
    )


@login_required
def dashboard(request):
    transaction_form = TransactionForm(user=request.user)
    account_form = AccountForm()
    budget_form = BudgetForm(user=request.user)
    requested_dialog = request.GET.get("dialog", "")
    open_dialog = (
        requested_dialog
        if requested_dialog in {
            "transaction-dialog",
            "account-dialog",
            "budget-dialog",
        }
        else ""
    )
    if request.method == "POST":
        if request.POST.get("action") == "transaction":
            transaction_form = TransactionForm(request.POST, user=request.user)
            if transaction_form.is_valid():
                with transaction.atomic():
                    entry = transaction_form.save()
                    balance_change = entry.amount
                    if entry.transaction_type == Transaction.TransactionType.DEBIT:
                        balance_change = -balance_change
                    Account.objects.filter(
                        pk=entry.account_id, user=request.user
                    ).update(current_balance=F("current_balance") + balance_change)
                messages.success(request, "Transaction added.")
                return redirect("finance:dashboard")
            open_dialog = "transaction-dialog"
        elif request.POST.get("action") == "account":
            account_form = AccountForm(request.POST)
            if account_form.is_valid():
                with transaction.atomic():
                    account_form.save(request.user)
                messages.success(request, "Account added.")
                return redirect("finance:dashboard")
            open_dialog = "account-dialog"
        elif request.POST.get("action") == "budget":
            budget_form = BudgetForm(request.POST, user=request.user)
            if budget_form.is_valid():
                with transaction.atomic():
                    budget_form.save()
                messages.success(request, "Budget added.")
                return redirect("finance:dashboard")
            open_dialog = "budget-dialog"

    today = timezone.localdate()
    month_start = today.replace(day=1)
    user_accounts = Account.objects.filter(user=request.user)
    user_transactions = Transaction.objects.filter(account__user=request.user)

    transactions = user_transactions.select_related(
        "category", "payee", "account"
    ).order_by("-transaction_date", "-created_at", "-pk")
    transaction_page = Paginator(transactions, 6).get_page(request.GET.get("page"))
    transactions = transaction_page.object_list
    budgets = []
    for budget in Budget.objects.filter(
        user=request.user, period_start__lte=today, period_end__gte=today
    ).select_related("category"):
        spent = user_transactions.filter(
            category=budget.category,
            transaction_type=Transaction.TransactionType.DEBIT,
            transaction_date__range=(budget.period_start, budget.period_end),
        ).aggregate(total=Sum("amount"))["total"] or 0
        percent = min(round((spent / budget.amount) * 100), 100) if budget.amount else 0
        budgets.append(
            {
                "name": budget.category.category_name,
                "spent": spent,
                "limit": budget.amount,
                "percent": percent,
                "remaining": max(budget.amount - spent, 0),
            }
        )

    category_spending = list(
        user_transactions.filter(
            transaction_type=Transaction.TransactionType.DEBIT,
            transaction_date__gte=month_start,
            transaction_date__lte=today,
        )
        .values("category__category_name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    monthly_debits = sum((item["total"] for item in category_spending), 0)
    spending_chart = []
    if monthly_debits:
        start_angle = -90
        for index, item in enumerate(category_spending):
            amount = item["total"]
            share = float(amount / monthly_debits)
            end_angle = start_angle + share * 360
            spending_chart.append(
                {
                    "name": item["category__category_name"] or "Uncategorized",
                    "amount": amount,
                    "percent": round(share * 100),
                    "color": SPENDING_CHART_COLORS[index % len(SPENDING_CHART_COLORS)],
                    "path": _pie_slice_path(
                        start_angle,
                        end_angle,
                        full_circle=len(category_spending) == 1,
                    ),
                }
            )
            start_angle = end_angle
    budget_remaining = sum((budget["remaining"] for budget in budgets), 0)
    credit_card_balance = user_accounts.filter(
        Q(account_type__type_name__icontains="credit")
        | Q(account_type__type_name__icontains="card")
    ).aggregate(total=Sum("current_balance"))["total"] or 0

    context = {
        "holdings": Holding.objects.filter(user=request.user),
        "holding_preview": Holding.objects.filter(user=request.user).order_by("symbol")[:4],
        "watchlist_entries": WatchlistEntry.objects.filter(user=request.user),
        "accounts": user_accounts.select_related("account_type"),
        "cash_totals": user_accounts.values("currency")
        .annotate(total=Sum("current_balance"))
        .order_by("currency"),
        "transactions": transactions,
        "transaction_page": transaction_page,
        "budgets": budgets,
        "available_cash": user_accounts.aggregate(total=Sum("current_balance"))["total"] or 0,
        "monthly_spending": monthly_debits,
        "spending_chart": spending_chart,
        "budget_remaining": budget_remaining,
        "credit_card_balance": credit_card_balance,
        "current_month": today.strftime("%B %Y"),
        "transaction_form": transaction_form,
        "account_form": account_form,
        "budget_form": budget_form,
        "open_dialog": open_dialog,
    }
    return render(request, "members/dashboard.html", context)


@login_required
def transactions(request):
    entries = Transaction.objects.filter(account__user=request.user).select_related(
        "account", "category", "payee"
    )
    current_year = timezone.localdate().year
    years = sorted(
        {
            current_year,
            *(transaction_date.year for transaction_date in entries.dates("transaction_date", "year")),
        },
        reverse=True,
    )

    selected_year = request.GET.get("year", str(current_year))
    if selected_year == "all":
        year_value = None
    elif re.fullmatch(r"\d{4}", selected_year) and int(selected_year) in years:
        year_value = int(selected_year)
    else:
        selected_year = str(current_year)
        year_value = current_year

    transaction_type = request.GET.get("type", "")
    if transaction_type not in dict(Transaction.TransactionType.choices):
        transaction_type = ""
    account_id = request.GET.get("account", "")
    user_account_ids = set(
        Account.objects.filter(user=request.user).values_list("pk", flat=True)
    )
    if not re.fullmatch(r"\d{1,10}", account_id) or int(account_id) not in user_account_ids:
        account_id = ""
    category_id = request.GET.get("category", "")
    user_category_ids = set(
        entries.exclude(category=None).values_list("category_id", flat=True)
    )
    if not re.fullmatch(r"\d{1,10}", category_id) or int(category_id) not in user_category_ids:
        category_id = ""

    start_date = request.GET.get("start", "").strip()
    end_date = request.GET.get("end", "").strip()
    try:
        parsed_start = parse_date(start_date) if start_date else None
    except ValueError:
        parsed_start = None
    try:
        parsed_end = parse_date(end_date) if end_date else None
    except ValueError:
        parsed_end = None
    filter_error = ""
    if start_date and parsed_start is None:
        filter_error = "Enter a valid start date."
        start_date = ""
    if end_date and parsed_end is None:
        filter_error = "Enter a valid end date."
        end_date = ""
    if parsed_start and parsed_end and parsed_start > parsed_end:
        filter_error = "The start date must be on or before the end date."
        parsed_start = parsed_end = None
        start_date = end_date = ""

    search = request.GET.get("q", "").strip()[:100]
    filtered_entries = entries
    if year_value is not None:
        filtered_entries = filtered_entries.filter(transaction_date__year=year_value)
    if transaction_type:
        filtered_entries = filtered_entries.filter(transaction_type=transaction_type)
    if account_id:
        filtered_entries = filtered_entries.filter(account_id=account_id)
    if category_id:
        filtered_entries = filtered_entries.filter(category_id=category_id)
    if parsed_start:
        filtered_entries = filtered_entries.filter(transaction_date__gte=parsed_start)
    if parsed_end:
        filtered_entries = filtered_entries.filter(transaction_date__lte=parsed_end)
    if search:
        filtered_entries = filtered_entries.filter(
            Q(description__icontains=search)
            | Q(payee__payee_name__icontains=search)
            | Q(category__category_name__icontains=search)
        )

    page_obj = Paginator(
        filtered_entries.order_by("-transaction_date", "-created_at", "-pk"), 25
    ).get_page(request.GET.get("page"))
    totals = list(
        filtered_entries.values("account__currency", "transaction_type")
        .annotate(total=Sum("amount"))
        .order_by("account__currency", "transaction_type")
    )
    filter_query = request.GET.copy()
    filter_query.pop("page", None)
    categories = (
        entries.exclude(category=None)
        .values("category_id", "category__category_name")
        .distinct()
        .order_by("category__category_name")
    )
    return render(
        request,
        "members/transactions.html",
        {
            "page_title": "Transactions",
            "page_subtitle": "A complete, searchable history of money in and out.",
            "current_month": timezone.localdate().strftime("%B %Y"),
            "page_obj": page_obj,
            "transactions": page_obj.object_list,
            "years": years,
            "selected_year": selected_year,
            "selected_type": transaction_type,
            "selected_account": account_id,
            "selected_category": category_id,
            "start_date": start_date,
            "end_date": end_date,
            "search": search,
            "filter_error": filter_error,
            "filter_query": filter_query.urlencode(),
            "transaction_types": Transaction.TransactionType.choices,
            "accounts": Account.objects.filter(user=request.user).order_by("account_name"),
            "categories": categories,
            "totals": totals,
        },
    )


@login_required
def budgets(request):
    today = timezone.localdate()
    entries = Transaction.objects.filter(
        account__user=request.user,
        transaction_type=Transaction.TransactionType.DEBIT,
    )
    budget_rows = []
    for budget in Budget.objects.filter(user=request.user).select_related(
        "category"
    ).order_by("-period_start", "category__category_name"):
        spent = entries.filter(
            category=budget.category,
            transaction_date__range=(budget.period_start, budget.period_end),
        ).aggregate(total=Sum("amount"))["total"] or 0
        budget_rows.append(
            {
                "category": budget.category.category_name,
                "period_start": budget.period_start,
                "period_end": budget.period_end,
                "spent": spent,
                "limit": budget.amount,
                "remaining": max(budget.amount - spent, 0),
                "over_budget": max(spent - budget.amount, 0),
                "percent": min(round(spent / budget.amount * 100), 100)
                if budget.amount
                else 0,
                "is_current": budget.period_start <= today <= budget.period_end,
            }
        )
    active_budgets = [budget for budget in budget_rows if budget["is_current"]]
    return render(
        request,
        "members/budgets.html",
        {
            "page_title": "Budgets",
            "page_subtitle": "Plan a little ahead. See how each category is tracking.",
            "current_month": today.strftime("%B %Y"),
            "budgets": budget_rows,
            "current_budget_count": len(active_budgets),
            "current_limit_total": sum(
                (budget["limit"] for budget in active_budgets), 0
            ),
            "current_spent_total": sum(
                (budget["spent"] for budget in active_budgets), 0
            ),
        },
    )


@login_required
def balances(request):
    accounts = Account.objects.filter(user=request.user).select_related(
        "account_type"
    ).annotate(
        transaction_count=Count("transactions"),
        last_transaction=Max("transactions__transaction_date"),
    ).order_by("currency", "account_name")
    totals = Account.objects.filter(user=request.user).values("currency").annotate(
        total=Sum("current_balance")
    ).order_by("currency")
    return render(
        request,
        "members/balances.html",
        {
            "page_title": "Balances",
            "page_subtitle": "Your accounts, grouped by currency and activity.",
            "current_month": timezone.localdate().strftime("%B %Y"),
            "accounts": accounts,
            "currency_totals": totals,
        },
    )


@login_required
def investments(request):
    return render(
        request,
        "members/investments.html",
        {
            "page_title": "Investments",
            "page_subtitle": "Your portfolio, watchlist, and market headlines.",
            "current_month": timezone.localdate().strftime("%B %Y"),
            "holdings": Holding.objects.filter(user=request.user),
            "watchlist_entries": WatchlistEntry.objects.filter(user=request.user),
        },
    )


def _balance_effect(entry):
    return -entry.amount if entry.transaction_type == Transaction.TransactionType.DEBIT else entry.amount


@login_required
@require_http_methods(["GET", "POST"])
def transaction_edit(request, pk):
    # Capture the old values before ModelForm validation mutates its instance.
    with transaction.atomic():
        entries = Transaction.objects.filter(account__user=request.user)
        if request.method == "POST":
            entries = entries.select_for_update(of=("self",))
        entry = get_object_or_404(entries, pk=pk)
        old_account_id = entry.account_id
        old_effect = _balance_effect(entry)
        form = TransactionForm(
            request.POST if request.method == "POST" else None,
            instance=entry,
            user=request.user,
        )
        if request.method == "POST" and form.is_valid():
            # Lock both accounts in a consistent order when moving an entry.
            list(Account.objects.select_for_update().filter(
                pk__in={old_account_id, form.cleaned_data["account"].pk},
                user=request.user,
            ).order_by("pk"))
            updated = form.save()
            changes = {old_account_id: -old_effect}
            changes[updated.account_id] = changes.get(updated.account_id, 0) + _balance_effect(updated)
            for account_id in sorted(changes):
                Account.objects.filter(pk=account_id, user=request.user).update(
                    current_balance=F("current_balance") + changes[account_id]
                )
            messages.success(request, "Transaction updated.")
            return redirect("finance:transactions")
    return render(request, "members/transaction_edit.html", {"form": form, "entry": entry})


@login_required
@require_http_methods(["GET", "POST"])
def transaction_delete(request, pk):
    with transaction.atomic():
        entries = Transaction.objects.filter(account__user=request.user)
        if request.method == "POST":
            entries = entries.select_for_update(of=("self",))
        entry = get_object_or_404(entries, pk=pk)
        if request.method == "POST":
            Account.objects.filter(pk=entry.account_id, user=request.user).update(
                current_balance=F("current_balance") - _balance_effect(entry)
            )
            entry.delete()
            messages.success(request, "Transaction deleted and account balance corrected.")
            return redirect("finance:transactions")
    return render(request, "members/transaction_delete.html", {"entry": entry})
