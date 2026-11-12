from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Account, AccountType, Budget, Category, Transaction


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class FinancePageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="finance-pages-user", password="Strong-test-pass-98!"
        )
        self.account_type = AccountType.objects.create(type_name="Checking")
        self.account = Account.objects.create(
            user=self.user,
            account_type=self.account_type,
            account_name="Everyday",
            current_balance=Decimal("950.00"),
        )
        self.category = Category.objects.create(category_name="Dining")
        self.client.force_login(self.user)

    def add_entry(self, description, transaction_date, transaction_type="debit"):
        return Transaction.objects.create(
            account=self.account,
            category=self.category,
            description=description,
            transaction_date=transaction_date,
            transaction_type=transaction_type,
            amount=Decimal("24.50"),
        )

    def test_transactions_page_filters_year_category_type_and_search(self):
        matching = self.add_entry("Coffee with Sam", date(2025, 6, 12))
        self.add_entry("Coffee income", date(2025, 6, 11), "credit")
        self.add_entry("Older coffee", date(2024, 6, 12))

        response = self.client.get(
            reverse("finance:transactions"),
            {
                "year": "2025",
                "type": "debit",
                "category": str(self.category.pk),
                "q": "coffee",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["transactions"]), [matching])
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, "Coffee with Sam")

    def test_transaction_page_only_shows_the_signed_in_users_records(self):
        other_user = get_user_model().objects.create_user(
            username="other-finance-pages-user"
        )
        other_account = Account.objects.create(
            user=other_user,
            account_type=self.account_type,
            account_name="Private",
        )
        Transaction.objects.create(
            account=other_account,
            category=self.category,
            description="Private transaction",
            transaction_date=date(2025, 1, 1),
            transaction_type=Transaction.TransactionType.DEBIT,
            amount=Decimal("500.00"),
        )

        response = self.client.get(
            reverse("finance:transactions"), {"year": "all"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Private transaction")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_sidebar_destinations_render_their_own_pages(self):
        for route_name, heading in (
            ("transactions", "Transactions"),
            ("budgets", "Budgets"),
            ("balances", "Balances"),
            ("investments", "Investments"),
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(f"finance:{route_name}"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"<h1")
                self.assertContains(response, heading)
                self.assertContains(response, 'aria-current="page"')

    def test_budgets_page_calculates_current_budget_progress(self):
        budget = Budget.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal("100.00"),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        self.add_entry("Lunch", date(2026, 1, 5))

        response = self.client.get(reverse("finance:budgets"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["budgets"][0]["spent"], Decimal("24.50"))
        self.assertEqual(response.context["budgets"][0]["limit"], budget.amount)

    def test_dashboard_splits_available_cash_by_currency(self):
        Account.objects.create(
            user=self.user,
            account_type=self.account_type,
            account_name="Travel wallet",
            current_balance=Decimal("40.00"),
            currency="EUR",
        )

        response = self.client.get(reverse("finance:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["cash_totals"]),
            [
                {"currency": "EUR", "total": Decimal("40.00")},
                {"currency": "USD", "total": Decimal("950.00")},
            ],
        )
