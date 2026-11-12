import io
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse
from unittest.mock import patch

import pyotp
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .account_views import _decrypt_totp_secret, _encrypt_totp_secret
from .models import Account, AccountType, Budget, Category, MemberProfile, Transaction


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Sable <finance@example.com>",
)
class AccountSettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="account@example.com",
            email="account@example.com",
            first_name="Avery",
            password="Original-password-123!",
        )
        self.profile = MemberProfile.objects.create(user=self.user, bank_name="North Bank")
        self.client.force_login(self.user)

    def test_account_page_shows_profile_security_and_notification_controls(self):
        response = self.client.get(reverse("finance:account"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personal details")
        self.assertContains(response, "Authenticator app")
        self.assertContains(response, "Monthly financial summary")
        self.assertContains(response, "Budget limit alerts")
        self.assertContains(response, "Account")

    def test_user_email_changes_only_after_password_and_email_confirmation(self):
        response = self.client.post(
            reverse("finance:account"),
            {
                "action": "details",
                "first_name": "Avery Rose",
                "email": "avery@example.com",
                "current_password": "Original-password-123!",
                "bank_name": "Community Bank",
                "email_monthly_summary": "on",
                "email_budget_alerts": "on",
            },
        )
        self.assertRedirects(response, reverse("finance:account"))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, "Avery Rose")
        self.assertEqual(self.user.email, "account@example.com")
        self.assertEqual(self.user.username, "account@example.com")
        self.assertEqual(self.profile.bank_name, "Community Bank")
        self.assertTrue(self.profile.email_monthly_summary)
        self.assertTrue(self.profile.email_budget_alerts)
        self.assertEqual(self.profile.pending_email, "avery@example.com")
        self.assertEqual(len(mail.outbox), 1)

        confirmation_path = urlparse(
            next(
                line
                for line in mail.outbox[0].body.splitlines()
                if line.startswith("http://")
            )
        ).path
        self.assertEqual(self.client.get(confirmation_path).status_code, 200)
        response = self.client.post(confirmation_path)
        self.assertRedirects(response, reverse("finance:account"))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, "avery@example.com")
        self.assertEqual(self.user.username, "avery@example.com")
        self.assertEqual(self.profile.pending_email, "")

    def test_email_change_requires_current_password(self):
        response = self.client.post(
            reverse("finance:account"),
            {
                "action": "details",
                "first_name": "Changed",
                "email": "avery@example.com",
                "current_password": "wrong-password",
                "bank_name": "Community Bank",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, "Avery")
        self.assertFalse(self.profile.pending_email)
        self.assertFalse(mail.outbox)

    def test_password_change_keeps_current_session_authenticated(self):
        response = self.client.post(
            reverse("finance:account"),
            {
                "action": "password",
                "old_password": "Original-password-123!",
                "new_password1": "New-Strong-password-456!",
                "new_password2": "New-Strong-password-456!",
            },
        )
        self.assertRedirects(response, reverse("finance:account"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-Strong-password-456!"))
        self.assertEqual(self.client.get(reverse("finance:account")).status_code, 200)

    def test_authenticator_setup_requires_a_valid_code_and_then_protects_login(self):
        response = self.client.post(
            reverse("finance:account"), {"action": "begin_authenticator"}
        )
        self.assertRedirects(response, f"{reverse('finance:account')}?auth=setup")
        response = self.client.get(reverse("finance:account"), {"auth": "setup"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "authenticator-qr")
        self.profile.refresh_from_db()
        secret = _decrypt_totp_secret(self.profile)
        self.assertNotEqual(self.profile.totp_secret, secret)

        invalid = self.client.post(
            reverse("finance:account"),
            {"action": "verify_authenticator", "code": "000000"},
        )
        self.assertEqual(invalid.status_code, 200)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.totp_enabled)

        response = self.client.post(
            reverse("finance:account"),
            {
                "action": "verify_authenticator",
                "code": pyotp.TOTP(secret).now(),
            },
        )
        self.assertRedirects(response, reverse("finance:account"))
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.totp_enabled)

        self.client.logout()
        response = self.client.post(
            reverse("finance:login"),
            {
                "username": "account@example.com",
                "password": "Original-password-123!",
                "next": reverse("finance:balances"),
            },
        )
        self.assertRedirects(response, reverse("finance:login-verify"))
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(
            reverse("finance:login-verify"),
            {"code": pyotp.TOTP(secret).now()},
        )
        self.assertRedirects(response, reverse("finance:balances"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_authenticator_can_only_be_disabled_with_password_and_valid_code(self):
        secret = pyotp.random_base32()
        self.profile.totp_secret = _encrypt_totp_secret(secret)
        self.profile.totp_enabled = True
        self.profile.save()

        response = self.client.post(
            reverse("finance:account"),
            {
                "action": "disable_authenticator",
                "current_password": "wrong-password",
                "code": pyotp.TOTP(secret).now(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.totp_enabled)

        response = self.client.post(
            reverse("finance:account"),
            {
                "action": "disable_authenticator",
                "current_password": "Original-password-123!",
                "code": pyotp.TOTP(secret).now(),
            },
        )
        self.assertRedirects(response, reverse("finance:account"))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.totp_enabled)
        self.assertEqual(self.profile.totp_secret, "")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Sable <finance@example.com>",
)
class FinancialEmailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alerts@example.com",
            email="alerts@example.com",
            password="Alert-password-123!",
        )
        self.profile = MemberProfile.objects.create(
            user=self.user,
            bank_name="",
            email_budget_alerts=True,
            email_monthly_summary=True,
        )
        self.category = Category.objects.create(category_name="Dining")
        self.account_type = AccountType.objects.create(type_name="Checking")
        self.account = Account.objects.create(
            user=self.user,
            account_type=self.account_type,
            account_name="Everyday",
            current_balance=Decimal("100"),
        )

    def test_budget_limit_email_sends_once_and_resets_after_spending_drops(self):
        today = timezone.localdate()
        budget = Budget.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal("50"),
            period_start=today.replace(day=1),
            period_end=today,
        )
        transaction = Transaction.objects.create(
            account=self.account,
            category=self.category,
            transaction_date=today,
            amount=Decimal("50"),
            transaction_type=Transaction.TransactionType.DEBIT,
        )
        from .notifications import budget_groups, update_budget_email_alerts

        self.assertTrue(
            update_budget_email_alerts(
                self.user, budget_groups(transaction.category_id, transaction.transaction_date)
            )
        )
        budget.refresh_from_db()
        self.assertTrue(budget.alert_sent)
        self.assertEqual(len(mail.outbox), 1)

        update_budget_email_alerts(
            self.user,
            budget_groups(transaction.category_id, transaction.transaction_date),
        )
        self.assertEqual(len(mail.outbox), 1)

        transaction.delete()
        update_budget_email_alerts(
            self.user,
            budget_groups(self.category.pk, today),
            allow_send=False,
        )
        budget.refresh_from_db()
        self.assertFalse(budget.alert_sent)

    def test_monthly_command_sends_previous_month_and_groups_by_currency(self):
        Account.objects.filter(pk=self.account.pk).update(currency="CAD")
        Transaction.objects.create(
            account=self.account,
            category=self.category,
            transaction_date=date(2025, 5, 10),
            amount=Decimal("21.25"),
            transaction_type=Transaction.TransactionType.DEBIT,
        )
        with patch("members.management.commands.send_monthly_summaries.timezone.localdate",
                   return_value=date(2025, 6, 1)):
            call_command("send_monthly_summaries", stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("May 2025", mail.outbox[0].subject)
        self.assertIn("CAD", mail.outbox[0].body)
        self.assertIn("21.25", mail.outbox[0].body)
