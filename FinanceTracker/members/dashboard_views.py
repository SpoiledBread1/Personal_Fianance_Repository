from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Account, Budget, Transaction


@login_required
def dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    user_accounts = Account.objects.filter(user=request.user)
    user_transactions = Transaction.objects.filter(account__user=request.user)

    transactions = user_transactions.select_related(
        "category", "payee", "account"
    ).order_by("-transaction_date", "-created_at")[:10]
    budgets = []
    for budget in Budget.objects.filter(user=request.user).select_related("category"):
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
        "budget_remaining": budget_remaining,
        "credit_card_balance": credit_card_balance,
        "current_month": today.strftime("%B %Y"),
    }
    return render(request, "members/dashboard.html", context)
