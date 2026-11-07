import logging
import re
from math import cos, radians, sin
import xml.etree.ElementTree as ET

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import AccountForm, BudgetForm, TransactionForm
from .models import Account, Budget, Transaction
from .news import fetch_cnbc_articles


logger = logging.getLogger(__name__)
CNBC_QUOTES_URL = "https://www.cnbc.com/quotes/"
MARKET_LINKS = (
    {"name": "S&P 500", "symbol": ".SPX"},
    {"name": "Dow Jones", "symbol": ".DJI"},
    {"name": "Nasdaq Composite", "symbol": ".IXIC"},
)


def _cnbc_articles():
    cached_result = cache.get("cnbc_finance_articles")
    if cached_result is not None:
        return cached_result

    try:
        articles = fetch_cnbc_articles()
    except (ET.ParseError, OSError, TimeoutError, ValueError) as error:
        logger.warning("Unable to load CNBC headlines: %s", error)
        result = (
            [],
            "CNBC headlines are temporarily unavailable. Please try again later.",
        )
        cache.set("cnbc_finance_articles", result, timeout=60)
        return result

    result = (articles, "")
    cache.set("cnbc_finance_articles", result, timeout=900)
    return result


def _market_context():
    return {
        "market_links": [
            {
                **market,
                "url": f"{CNBC_QUOTES_URL}{market['symbol']}",
            }
            for market in MARKET_LINKS
        ]
    }


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
    budget_form = BudgetForm()
    open_dialog = ""
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
            budget_form = BudgetForm(request.POST)
            if budget_form.is_valid():
                with transaction.atomic():
                    budget_form.save(request.user)
                messages.success(request, "Monthly budget saved.")
                return redirect("finance:dashboard")
            open_dialog = "budget-dialog"

    today = timezone.localdate()
    month_start = today.replace(day=1)
    user_accounts = Account.objects.filter(user=request.user)
    user_transactions = Transaction.objects.filter(account__user=request.user)

    transactions = user_transactions.select_related(
        "category", "payee", "account"
    ).order_by("-transaction_date", "-created_at")[:6]
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

    monthly_debits = user_transactions.filter(
        transaction_type=Transaction.TransactionType.DEBIT,
        transaction_date__gte=month_start,
        transaction_date__lte=today,
    ).aggregate(total=Sum("amount"))["total"] or 0
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
                    "color": SPENDING_CHART_COLORS[
                        index % len(SPENDING_CHART_COLORS)
                    ],
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
        "accounts": user_accounts.select_related("account_type"),
        "transactions": transactions,
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
    news_articles, news_error = _cnbc_articles()
    context["news_articles"] = news_articles[:3]
    context["news_error"] = news_error
    context.update(_market_context())
    return render(request, "members/dashboard.html", context)


@login_required
def transactions(request):
    base_transactions = Transaction.objects.filter(
        account__user=request.user
    ).select_related("category", "payee", "account")
    current_year = timezone.localdate().year
    years = sorted(
        {
            current_year,
            *(
                date.year
                for date in base_transactions.dates("transaction_date", "year")
            ),
        },
        reverse=True,
    )
    selected_year = request.GET.get("year", str(current_year))
    if selected_year == "all":
        year_value = None
    elif re.fullmatch(r"[0-9]{4}", selected_year) and int(selected_year) in years:
        year_value = int(selected_year)
    else:
        selected_year = str(current_year)
        year_value = int(selected_year)

    selected_type = request.GET.get("type", "")
    if selected_type not in dict(Transaction.TransactionType.choices):
        selected_type = ""
    selected_account = request.GET.get("account", "")
    account_ids = set(
        Account.objects.filter(user=request.user).values_list("pk", flat=True)
    )
    if not re.fullmatch(r"[0-9]{1,10}", selected_account) or int(selected_account) not in account_ids:
        selected_account = ""
    selected_category = request.GET.get("category", "")
    category_ids = set(
        base_transactions.exclude(category=None).values_list("category_id", flat=True)
    )
    if not re.fullmatch(r"[0-9]{1,10}", selected_category) or int(selected_category) not in category_ids:
        selected_category = ""
    search = request.GET.get("q", "").strip()[:100]

    filtered_transactions = base_transactions
    if year_value is not None:
        filtered_transactions = filtered_transactions.filter(
            transaction_date__year=year_value
        )
    if selected_type:
        filtered_transactions = filtered_transactions.filter(
            transaction_type=selected_type
        )
    if selected_account:
        filtered_transactions = filtered_transactions.filter(account_id=selected_account)
    if selected_category:
        filtered_transactions = filtered_transactions.filter(category_id=selected_category)
    if search:
        filtered_transactions = filtered_transactions.filter(
            Q(description__icontains=search)
            | Q(payee__payee_name__icontains=search)
            | Q(category__category_name__icontains=search)
        )

    currency_totals = list(
        filtered_transactions.values("account__currency", "transaction_type")
        .annotate(total=Sum("amount"))
        .order_by("account__currency", "transaction_type")
    )
    paginator = Paginator(
        filtered_transactions.order_by("-transaction_date", "-created_at"), 25
    )
    page_obj = paginator.get_page(request.GET.get("page"))
    filter_params = request.GET.copy()
    filter_params.pop("page", None)
    categories = (
        base_transactions.exclude(category=None)
        .values("category_id", "category__category_name")
        .distinct()
        .order_by("category__category_name")
    )
    context = {
        "page_title": "Transactions",
        "page_subtitle": "Search and review your full transaction history.",
        "current_month": timezone.localdate().strftime("%B %Y"),
        "transactions": page_obj.object_list,
        "page_obj": page_obj,
        "years": years,
        "accounts": Account.objects.filter(user=request.user).order_by("account_name"),
        "categories": categories,
        "selected_year": selected_year,
        "selected_type": selected_type,
        "selected_account": selected_account,
        "selected_category": selected_category,
        "search": search,
        "currency_totals": currency_totals,
        "filter_query": filter_params.urlencode(),
        "transaction_types": Transaction.TransactionType.choices,
    }
    return render(request, "members/transactions.html", context)


@login_required
def budgets(request):
    today = timezone.localdate()
    user_transactions = Transaction.objects.filter(account__user=request.user)
    budget_rows = []
    for budget in Budget.objects.filter(user=request.user).select_related(
        "category"
    ).order_by("-period_start", "category__category_name"):
        spent = user_transactions.filter(
            category=budget.category,
            transaction_type=Transaction.TransactionType.DEBIT,
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
                "percent": min(round((spent / budget.amount) * 100), 100)
                if budget.amount
                else 0,
                "is_current": budget.period_start <= today <= budget.period_end,
            }
        )
    return render(
        request,
        "members/budgets.html",
        {
            "page_title": "Budgets",
            "page_subtitle": "Track category limits and see how spending adds up.",
            "current_month": today.strftime("%B %Y"),
            "budgets": budget_rows,
        },
    )


@login_required
def balances(request):
    accounts = list(
        Account.objects.filter(user=request.user)
        .select_related("account_type")
        .annotate(
            transaction_count=Count("transactions"),
            last_transaction=Max("transactions__transaction_date"),
        )
        .order_by("currency", "account_type__type_name", "account_name")
    )
    currency_totals = list(
        Account.objects.filter(user=request.user)
        .values("currency")
        .annotate(total=Sum("current_balance"))
        .order_by("currency")
    )
    return render(
        request,
        "members/balances.html",
        {
            "page_title": "Balances",
            "page_subtitle": "See every account and its latest activity.",
            "current_month": timezone.localdate().strftime("%B %Y"),
            "accounts": accounts,
            "currency_totals": currency_totals,
        },
    )


@login_required
def news_stocks(request):
    if request.GET.get("refresh") == "1":
        cache.delete("cnbc_finance_articles")
    articles, news_error = _cnbc_articles()
    symbol = request.GET.get("symbol", "").strip().upper()
    symbol_error = ""
    stock_url = ""
    if symbol:
        if re.fullmatch(r"[A-Z0-9.^-]{1,10}", symbol):
            stock_url = f"{CNBC_QUOTES_URL}{symbol}"
        else:
            symbol_error = (
                "Enter a valid stock symbol using letters, numbers, dots, or hyphens."
            )
    context = {
        "page_title": "News & Stocks",
        "page_subtitle": "Financial headlines and market links, sourced from CNBC.",
        "current_month": timezone.localdate().strftime("%B %Y"),
        "news_articles": articles,
        "news_error": news_error,
        "symbol": symbol,
        "symbol_error": symbol_error,
        "stock_url": stock_url,
    }
    context.update(_market_context())
    return render(request, "members/news_stocks.html", context)
