from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Account,
    AccountType,
    Budget,
    Category,
    Holding,
    MarketCache,
    MemberProfile,
    Payee,
    Tag,
    Transaction,
    WatchlistEntry,
)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class FinanceAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin-user",
            email="admin@example.com",
            password="admin-password",
        )
        self.client.force_login(self.user)
        self.account_type = AccountType.objects.create(type_name="Checking")
        self.account = Account.objects.create(
            user=self.user,
            account_type=self.account_type,
            account_name="Everyday",
            current_balance=Decimal("950.00"),
        )
        self.category = Category.objects.create(category_name="Dining")
        self.payee = Payee.objects.create(payee_name="Cafe")
        self.transaction = Transaction.objects.create(
            account=self.account,
            category=self.category,
            payee=self.payee,
            transaction_date=date(2026, 6, 12),
            amount=Decimal("24.50"),
            transaction_type=Transaction.TransactionType.DEBIT,
            description="Lunch",
        )

    def test_finance_models_are_available_in_admin(self):
        for model in (
            AccountType,
            Account,
            Category,
            Payee,
            Tag,
            Transaction,
            Budget,
            MemberProfile,
            Holding,
            WatchlistEntry,
            MarketCache,
        ):
            with self.subTest(model=model):
                self.assertTrue(admin.site.is_registered(model))

        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sable Finance Administration")
        self.assertContains(response, "Manage finance data and users")

    def test_transaction_list_searches_descriptions_and_related_fields(self):
        url = reverse("admin:members_transaction_changelist")
        response = self.client.get(url, {"q": "Lunch"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Everyday")
        self.assertContains(response, "Cafe")
        self.assertEqual(
            list(response.context["cl"].queryset), [self.transaction]
        )

    def test_admin_lists_have_working_transaction_filters(self):
        response = self.client.get(
            reverse("admin:members_transaction_changelist"),
            {"transaction_type__exact": Transaction.TransactionType.CREDIT},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["cl"].queryset.exists())
