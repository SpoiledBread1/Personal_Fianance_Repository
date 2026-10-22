from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import override_settings
from decimal import Decimal

from .models import Account, AccountType, Budget, Category, Transaction


@override_settings(
	STORAGES={
		"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
		"staticfiles": {
			"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
		},
	}
)
class SignupTests(TestCase):
	def test_signup_page_shows_email_password_and_bank_fields(self):
		response = self.client.get(reverse("finance:signup"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'name="email"')
		self.assertContains(response, 'name="password1"')
		self.assertContains(response, 'name="bank_name"')

	def test_signup_creates_user_and_logs_them_in(self):
		response = self.client.post(
			reverse("finance:signup"),
			{
				"email": "newuser@example.com",
				"password1": "C0mpl3x!Passphrase",
				"password2": "C0mpl3x!Passphrase",
				"bank_name": "Example Bank",
			},
		)

		user = get_user_model().objects.get(username="newuser@example.com")
		self.assertRedirects(response, reverse("finance:dashboard"))
		self.assertTrue(user.check_password("C0mpl3x!Passphrase"))
		self.assertEqual(user.email, "newuser@example.com")
		self.assertEqual(user.profile.bank_name, "Example Bank")
		self.assertIn("_auth_user_id", self.client.session)

	def test_signup_rejects_mismatched_passwords(self):
		response = self.client.post(
			reverse("finance:signup"),
			{
				"email": "newuser@example.com",
				"password1": "C0mpl3x!Passphrase",
				"password2": "Different!Passphrase",
				"bank_name": "Example Bank",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(
			get_user_model().objects.filter(username="newuser@example.com").exists()
		)


class TransactionEntryTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username="ledgeruser", password="Test-pass-123!"
		)
		self.account_type = AccountType.objects.create(type_name="Checking")
		self.account = Account.objects.create(
			user=self.user,
			account_type=self.account_type,
			account_name="Daily checking",
			current_balance=Decimal("100.00"),
		)
		self.client.force_login(self.user)

	def transaction_data(self, account):
		return {
			"action": "transaction",
			"account": account.pk,
			"transaction_type": "debit",
			"amount": "12.50",
			"transaction_date": "2026-10-06",
			"description": "Lunch",
		}

	def test_transaction_is_saved_and_updates_owned_account_balance(self):
		response = self.client.post(
			reverse("finance:dashboard"), self.transaction_data(self.account)
		)

		self.assertRedirects(response, reverse("finance:dashboard"))
		entry = Transaction.objects.get(description="Lunch")
		self.assertEqual(entry.account, self.account)
		self.account.refresh_from_db()
		self.assertEqual(self.account.current_balance, Decimal("87.50"))

	def test_transaction_cannot_use_another_users_account(self):
		other_user = get_user_model().objects.create_user(
			username="otheruser", password="Test-pass-123!"
		)
		other_account = Account.objects.create(
			user=other_user,
			account_type=self.account_type,
			account_name="Private account",
		)

		response = self.client.post(
			reverse("finance:dashboard"), self.transaction_data(other_account)
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(Transaction.objects.exists())

	def test_account_can_be_created_for_signed_in_user(self):
		response = self.client.post(
			reverse("finance:dashboard"),
			{
				"action": "account",
				"account_name": "Rainy day",
				"account_type_name": "Savings",
				"opening_balance": "250.00",
				"currency": "usd",
			},
		)

		self.assertRedirects(response, reverse("finance:dashboard"))
		account = Account.objects.get(account_name="Rainy day")
		self.assertEqual(account.user, self.user)
		self.assertEqual(account.account_type.type_name, "Savings")
		self.assertEqual(account.current_balance, Decimal("250.00"))
		self.assertEqual(account.currency, "USD")

	def test_budget_can_be_created_for_signed_in_user(self):
		category = Category.objects.create(category_name="Groceries")
		response = self.client.post(
			reverse("finance:dashboard"),
			{
				"action": "budget",
				"category": category.pk,
				"amount": "300.00",
				"period_start": "2026-10-01",
				"period_end": "2026-10-31",
			},
		)

		self.assertRedirects(response, reverse("finance:dashboard"))
		budget = Budget.objects.get(category=category)
		self.assertEqual(budget.user, self.user)
		self.assertEqual(budget.amount, Decimal("300.00"))

	def test_transaction_budget_field_lists_budget_categories(self):
		category = Category.objects.create(category_name="Groceries")
		Budget.objects.create(
			user=self.user,
			category=category,
			amount=Decimal("300.00"),
			period_start="2026-10-01",
			period_end="2026-10-31",
		)
		unbudgeted_category = Category.objects.create(category_name="Dining")
		other_user = get_user_model().objects.create_user(username="otherbudgetuser")
		other_budget_category = Category.objects.create(category_name="Transport")
		Budget.objects.create(
			user=other_user,
			category=other_budget_category,
			amount=Decimal("100.00"),
			period_start="2026-10-01",
			period_end="2026-10-31",
		)
		response = self.client.get(reverse("finance:dashboard"))
		category_field = response.context["transaction_form"].fields["category"]
		self.assertEqual(category_field.label, "Budget")
		self.assertEqual(list(category_field.queryset), [category])
		self.assertNotIn(unbudgeted_category, category_field.queryset)

		data = self.transaction_data(self.account)
		data["category"] = category.pk

		response = self.client.post(reverse("finance:dashboard"), data)

		self.assertRedirects(response, reverse("finance:dashboard"))
		entry = Transaction.objects.get(description="Lunch")
		self.assertEqual(entry.category, category)
