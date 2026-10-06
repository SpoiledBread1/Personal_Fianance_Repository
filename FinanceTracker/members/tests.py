from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from decimal import Decimal

from .models import Account, AccountType, Transaction


class SignupTests(TestCase):
	def test_signup_creates_user_and_logs_them_in(self):
		response = self.client.post(
			reverse("finance:signup"),
			{
				"username": "newuser",
				"password1": "C0mpl3x!Passphrase",
				"password2": "C0mpl3x!Passphrase",
			},
		)

		user = get_user_model().objects.get(username="newuser")
		self.assertRedirects(response, reverse("finance:dashboard"))
		self.assertTrue(user.check_password("C0mpl3x!Passphrase"))
		self.assertIn("_auth_user_id", self.client.session)

	def test_signup_rejects_mismatched_passwords(self):
		response = self.client.post(
			reverse("finance:signup"),
			{
				"username": "newuser",
				"password1": "C0mpl3x!Passphrase",
				"password2": "Different!Passphrase",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(get_user_model().objects.filter(username="newuser").exists())


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
