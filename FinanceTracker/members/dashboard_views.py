from math import cos, radians, sin

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import AccountForm, BudgetForm, TransactionForm
from .models import Account, Budget, Transaction


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
    return render(request, "members/dashboard.html", context)
