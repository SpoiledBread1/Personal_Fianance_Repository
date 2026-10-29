"""Regression tests for transaction corrections. Run: manage.py test members.tests_transactions"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import TransactionForm
from .models import Account, AccountType, Budget, Category, Transaction


class TransactionCorrectionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="owner", password="testing-only-123")
        self.other = User.objects.create_user(username="other", password="testing-only-456")
        kind = AccountType.objects.create(type_name="Checking")
        self.a = Account.objects.create(user=self.user, account_type=kind, account_name="Checking", current_balance=950)
        self.b = Account.objects.create(user=self.user, account_type=kind, account_name="Savings", current_balance=200)
        self.foreign = Account.objects.create(user=self.other, account_type=kind, account_name="Private", current_balance=500)
        self.category = Category.objects.create(category_name="Groceries")
        self.date = timezone.localdate()
        self.entry = Transaction.objects.create(account=self.a, category=self.category, amount=50, transaction_type="debit", transaction_date=self.date, description="Original")
        Budget.objects.create(user=self.user, category=self.category, amount=100, period_start=self.date.replace(day=1), period_end=self.date)
        self.client.force_login(self.user)
        self.edit = reverse("finance:transaction-edit", args=[self.entry.pk])
        self.delete = reverse("finance:transaction-delete", args=[self.entry.pk])
        self.home = reverse("finance:dashboard")

    def payload(self, **changes):
        data = dict(account=self.a.pk, transaction_type="debit", amount="30.00",
                    transaction_date=self.date.isoformat(), category_name="Groceries",
                    description="Corrected", custom_category="")
        data.update(changes)
        return data

    def balance(self, account):
        account.refresh_from_db()
        return account.current_balance

    def test_edit_expense_updates_balance_budget_and_chart(self):
        self.assertEqual(self.client.post(self.edit, self.payload()).status_code, 302)
        self.assertEqual(self.balance(self.a), Decimal("970"))
        page = self.client.get(self.home)
        self.assertEqual(page.context["monthly_spending"], Decimal("30"))
        self.assertEqual(page.context["budgets"][0]["remaining"], Decimal("70"))
        self.assertEqual(page.context["spending_chart"][0]["amount"], Decimal("30"))
        # Repeating the same save must not apply the change again.
        self.client.post(self.edit, self.payload())
        self.assertEqual(self.balance(self.a), Decimal("970"))

    def test_change_type_and_move_account(self):
        self.client.post(self.edit, self.payload(account=self.b.pk, transaction_type="credit", amount="75"))
        self.assertEqual(self.balance(self.a), Decimal("1000"))
        self.assertEqual(self.balance(self.b), Decimal("275"))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.account_id, self.b.pk)
        self.assertEqual(self.client.get(self.home).context["monthly_spending"], 0)

    def test_delete_get_does_not_mutate_and_post_reverses_expense(self):
        response = self.client.get(self.delete)
        self.assertContains(response, "Keep transaction")
        self.assertEqual(self.balance(self.a), Decimal("950"))
        self.assertTrue(Transaction.objects.filter(pk=self.entry.pk).exists())
        self.assertEqual(self.client.post(self.delete).status_code, 302)
        self.assertEqual(self.balance(self.a), Decimal("1000"))
        self.assertFalse(Transaction.objects.filter(pk=self.entry.pk).exists())
        self.assertEqual(self.client.post(self.delete).status_code, 404)
        self.assertEqual(self.balance(self.a), Decimal("1000"))
        self.assertEqual(self.client.get(self.home).context["monthly_spending"], 0)

    def test_delete_income(self):
        self.client.post(self.edit, self.payload(transaction_type="credit", amount="75"))
        self.assertEqual(self.balance(self.a), Decimal("1075"))
        self.client.post(self.delete)
        self.assertEqual(self.balance(self.a), Decimal("1000"))

    def test_invalid_values_and_foreign_account_leave_everything_unchanged(self):
        for changes in [dict(amount="0"), dict(amount="-1"), dict(amount="abc"),
                        dict(transaction_type="transfer"), dict(account=self.foreign.pk)]:
            with self.subTest(changes=changes):
                response = self.client.post(self.edit, self.payload(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.entry.refresh_from_db()
                self.assertEqual(self.entry.amount, Decimal("50"))
                self.assertEqual(self.balance(self.a), Decimal("950"))
                self.assertEqual(self.balance(self.foreign), Decimal("500"))

    def test_other_users_cannot_view_edit_or_delete(self):
        self.client.force_login(self.other)
        for url in [self.edit, self.delete]:
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, self.payload()).status_code, 404)
        self.assertEqual(self.balance(self.a), Decimal("950"))
        self.client.logout()
        self.assertEqual(self.client.get(self.edit).status_code, 302)
        self.assertEqual(self.client.post(self.delete).status_code, 302)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.edit, self.payload()).status_code, 403)
        self.assertEqual(client.post(self.delete).status_code, 403)
        self.assertEqual(self.balance(self.a), Decimal("950"))

    def test_prefill_and_custom_category(self):
        old_date = self.date - timedelta(days=40)
        # Case variation must survive even if common category choices differ.
        self.category.category_name = "groceries"
        self.category.save()
        self.entry.transaction_date = old_date
        self.entry.save()
        response = self.client.get(self.edit)
        self.assertEqual(response.context["form"]["transaction_date"].value(), old_date)
        self.assertContains(response, 'value="groceries" selected')
        self.client.post(self.edit, self.payload(category_name="__new__", custom_category="Books"))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.category.category_name, "Books")

    def test_old_transactions_reachable(self):
        for i in range(7):
            Transaction.objects.create(account=self.a, amount=1, transaction_type="debit",
                                       transaction_date=self.date, description=f"Entry {i}")
        page = self.client.get(self.home)
        self.assertEqual(page.context["transaction_page"].paginator.count, 8)
        self.assertContains(page, "Older")
        page2 = self.client.get(self.home, {"page": 2})
        self.assertContains(page2, self.edit)
        self.assertContains(page2, self.delete)

    def test_labels_and_add_still_work(self):
        form = TransactionForm(user=self.user)
        self.assertEqual(list(form.fields["transaction_type"].choices), [("debit", "Expense"), ("credit", "Income")])
        self.client.post(self.home, {"action": "transaction", **self.payload(amount="10")})
        self.assertEqual(self.balance(self.a), Decimal("940"))

    def test_failure_rolls_back_edit_and_delete(self):
        # A failure after saving the edited row must roll back that row too.
        from django.db.models.query import QuerySet
        with patch.object(QuerySet, "update", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.edit, self.payload())
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, Decimal("50"))
        self.assertEqual(self.balance(self.a), Decimal("950"))
        with patch.object(Transaction, "delete", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.delete)
        self.assertTrue(Transaction.objects.filter(pk=self.entry.pk).exists())
        self.assertEqual(self.balance(self.a), Decimal("950"))
