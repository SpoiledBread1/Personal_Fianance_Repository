from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Account, AccountType, Budget, Category, Transaction


class MonthlyBudgetSetupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="budgetuser", password="SafePass!123"
        )
        self.client.force_login(self.user)

    def post_budget(self, category_name, amount):
        return self.client.post(
            reverse("finance:dashboard"),
            {
                "action": "budget",
                "category_name": category_name,
                "amount": amount,
            },
        )

    def test_budget_setup_creates_category_and_current_month_budget(self):
        response = self.post_budget("Grocery Shopping", "500.00")

        self.assertRedirects(response, reverse("finance:dashboard"))
        category = Category.objects.get(category_name="Grocery Shopping")
        today = timezone.localdate()
        period_start = today.replace(day=1)
        next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        budget = Budget.objects.get(user=self.user, category=category)
        self.assertEqual(budget.amount, Decimal("500.00"))
        self.assertEqual(budget.period_start, period_start)
        self.assertEqual(budget.period_end, next_month - timedelta(days=1))
        dashboard_response = self.client.get(reverse("finance:dashboard"))
        self.assertContains(dashboard_response, "Set up budget")
        self.assertContains(dashboard_response, "Grocery Shopping")
        self.assertEqual(
            dashboard_response.context["budgets"][0]["name"], "Grocery Shopping"
        )

        account_type = AccountType.objects.create(type_name="Checking")
        account = Account.objects.create(
            user=self.user, account_type=account_type, account_name="Checking"
        )
        transaction_response = self.client.post(
            reverse("finance:dashboard"),
            {
                "action": "transaction",
                "account": account.pk,
                "transaction_type": "debit",
                "amount": "42.50",
                "transaction_date": today.isoformat(),
                "category": category.pk,
                "description": "Weekly groceries",
            },
        )

        self.assertRedirects(transaction_response, reverse("finance:dashboard"))
        self.assertEqual(
            Transaction.objects.get(description="Weekly groceries").category,
            category,
        )

    def test_saving_category_again_updates_this_months_budget(self):
        self.post_budget("Groceries", "100.00")
        response = self.post_budget("groceries", "250.00")

        self.assertRedirects(response, reverse("finance:dashboard"))
        self.assertEqual(Category.objects.filter(category_name__iexact="groceries").count(), 1)
        self.assertEqual(Budget.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Budget.objects.get(user=self.user).amount, Decimal("250.00"))

    def test_custom_category_can_be_added_from_budget_selector(self):
        response = self.client.post(
            reverse("finance:dashboard"),
            {
                "action": "budget",
                "category_name": "__new__",
                "custom_category": "Pet Care",
                "amount": "75.00",
            },
        )

        self.assertRedirects(response, reverse("finance:dashboard"))
        category = Category.objects.get(category_name="Pet Care")
        self.assertEqual(
            Budget.objects.get(user=self.user, category=category).amount,
            Decimal("75.00"),
        )

    def test_custom_transaction_category_is_in_monthly_spending_chart(self):
        account_type = AccountType.objects.create(type_name="Checking")
        account = Account.objects.create(
            user=self.user, account_type=account_type, account_name="Checking"
        )
        response = self.client.post(
            reverse("finance:dashboard"),
            {
                "action": "transaction",
                "account": account.pk,
                "transaction_type": "debit",
                "amount": "18.25",
                "transaction_date": timezone.localdate().isoformat(),
                "category_name": "__new__",
                "custom_category": "Pet Care",
                "description": "Pet food",
            },
        )

        self.assertRedirects(response, reverse("finance:dashboard"))
        dashboard_response = self.client.get(reverse("finance:dashboard"))
        self.assertEqual(
            dashboard_response.context["spending_chart"][0]["name"], "Pet Care"
        )
        self.assertEqual(
            dashboard_response.context["spending_chart"][0]["amount"],
            Decimal("18.25"),
        )
        self.assertContains(dashboard_response, "Spending breakdown")

    def test_nonpositive_monthly_limit_is_rejected(self):
        response = self.post_budget("Unplanned", "0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["open_dialog"], "budget-dialog")
        self.assertFalse(Category.objects.filter(category_name="Unplanned").exists())
        self.assertFalse(Budget.objects.exists())
