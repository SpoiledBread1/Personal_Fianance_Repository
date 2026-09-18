from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    # Fictional display data only. Replace with user-filtered database queries later.
    transactions = [
        {"name": "Weekly groceries", "category": "Groceries", "date": "Sep 18", "amount": "−$64.20"},
        {"name": "Coffee shop", "category": "Dining", "date": "Sep 18", "amount": "−$5.50"},
        {"name": "Paycheck", "category": "Income", "date": "Sep 17", "amount": "+$850.00", "income": True},
        {"name": "Gas station", "category": "Transport", "date": "Sep 16", "amount": "−$38.00"},
    ]
    budgets = [
        {"name": "Groceries", "spent": 240, "limit": 400, "percent": 60, "remaining": 160},
        {"name": "Dining out", "spent": 170, "limit": 200, "percent": 85, "remaining": 30},
        {"name": "Transport", "spent": 90, "limit": 150, "percent": 60, "remaining": 60},
    ]
    return render(request, "members/dashboard.html", {"transactions": transactions, "budgets": budgets})
