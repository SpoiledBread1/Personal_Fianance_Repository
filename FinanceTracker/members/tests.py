from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.test import override_settings
from django.utils import timezone
from decimal import Decimal
from unittest.mock import patch

from .market_data import get_market_data
from .models import Account, AccountType, Budget, Category, Transaction


@override_settings(
	STORAGES={
		"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
		"staticfiles": {
			"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
		},
	},
	FINNHUB_API_KEY="test-token",
	MARKET_WATCHLIST=("AAPL", "MSFT", "NVDA"),
)
class MarketNewsTests(TestCase):
	def setUp(self):
		cache.clear()
		self.user = get_user_model().objects.create_user(username="marketuser")
		self.client.force_login(self.user)

	def test_dashboard_includes_stocks_and_news_tab(self):
		response = self.client.get(reverse("finance:dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'href="#stocks-news"')
		self.assertContains(response, "Market &amp; finance headlines")
		self.assertContains(response, reverse("finance:market-data"))

	@override_settings(FINNHUB_API_KEY="")
	def test_market_data_endpoint_explains_when_api_key_is_missing(self):
		response = self.client.get(reverse("finance:market-data"))

		self.assertEqual(response.status_code, 503)
		self.assertIn("FINNHUB_API_KEY", response.json()["error"])

	@patch("members.market_data_views.get_market_data")
	def test_market_data_endpoint_returns_and_caches_provider_data(self, get_data):
		data = {
			"quotes": [
				{
					"symbol": "AAPL",
					"price": 200.0,
					"change": 2.0,
					"change_percent": 1.0,
					"previous_close": 198.0,
				}
			],
			"headlines": [],
			"errors": [],
		}
		get_data.return_value = data

		first_response = self.client.get(reverse("finance:market-data"))
		second_response = self.client.get(reverse("finance:market-data"))

		self.assertEqual(first_response.status_code, 200)
		self.assertEqual(first_response.json()["quotes"], data["quotes"])
		self.assertIn("updated_at", first_response.json())
		self.assertEqual(second_response.status_code, 200)
		get_data.assert_called_once()

	@patch("members.market_data._request_finnhub")
	def test_market_data_normalizes_quotes_and_rejects_non_https_articles(
		self, request_finnhub
	):
		def provider_response(endpoint, params, _api_key):
			if endpoint == "quote":
				return {"c": 200.0, "d": 2.0, "dp": 1.0, "pc": 198.0}
			return [
				{
					"headline": "Markets open higher",
					"source": "Example News",
					"url": "https://example.com/markets",
					"datetime": 1_800_000_000,
				},
				{
					"headline": "Untrusted link",
					"url": "javascript:alert(1)",
					"datetime": 1_800_000_001,
				},
			]

		request_finnhub.side_effect = provider_response

		data = get_market_data("test-token")

		self.assertEqual([quote["symbol"] for quote in data["quotes"]], [
			"AAPL",
			"MSFT",
			"NVDA",
		])
		self.assertEqual(len(data["headlines"]), 1)
		self.assertEqual(data["headlines"][0]["source"], "Example News")
		self.assertEqual(data["errors"], [])


@override_settings(
	STORAGES={
		"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
		"staticfiles": {
			"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
		},
	}
)
class ProgressiveWebAppTests(TestCase):
	def test_service_worker_is_available_at_the_site_root(self):
		response = self.client.get("/service-worker.js")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response["Content-Type"], "application/javascript")
		self.assertContains(response, "sable-static-v2")
		self.assertContains(response, "url.pathname.startsWith('/static/')", html=False)

	def test_login_page_includes_installable_app_metadata(self):
		response = self.client.get(reverse("finance:login"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'name="theme-color"')
		self.assertContains(response, 'rel="manifest"')
		self.assertContains(response, 'id="install-app"')


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


@override_settings(
	STORAGES={
		"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
		"staticfiles": {
			"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
		},
	}
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

	def test_custom_category_can_be_added_as_budget(self):
		response = self.client.post(
			reverse("finance:dashboard"),
			{
				"action": "budget",
				"category_name": "__new__",
				"custom_category": "Pet Care",
				"amount": "75.00",
				"period_start": "2026-10-01",
				"period_end": "2026-10-31",
			},
		)

		self.assertRedirects(response, reverse("finance:dashboard"))
		category = Category.objects.get(category_name="Pet Care")
		budget = Budget.objects.get(user=self.user, category=category)
		self.assertEqual(budget.amount, Decimal("75.00"))

	def test_setting_same_category_budget_again_updates_this_month(self):
		category = Category.objects.create(category_name="Groceries")
		for amount in ("100.00", "250.00"):
			response = self.client.post(
				reverse("finance:dashboard"),
				{
					"action": "budget",
					"category_name": "Groceries",
					"amount": amount,
				},
			)
			self.assertRedirects(response, reverse("finance:dashboard"))

		self.assertEqual(Budget.objects.filter(user=self.user).count(), 1)
		self.assertEqual(
			Budget.objects.get(user=self.user, category=category).amount,
			Decimal("250.00"),
		)

	def test_transaction_category_field_lists_common_and_saved_categories(self):
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
		category_field = response.context["transaction_form"].fields["category_name"]
		self.assertEqual(category_field.label, "Category")
		category_choices = dict(category_field.choices)
		self.assertIn("Groceries", category_choices)
		self.assertIn("Dining", category_choices)
		self.assertIn("Transport", category_choices)
		self.assertIn("Add a new category...", category_choices.values())
		self.assertIn(unbudgeted_category.category_name, category_choices)
		self.assertContains(response, "No spending recorded this month.")

		data = self.transaction_data(self.account)
		data["category"] = category.pk

		response = self.client.post(reverse("finance:dashboard"), data)

		self.assertRedirects(response, reverse("finance:dashboard"))
		entry = Transaction.objects.get(description="Lunch")
		self.assertEqual(entry.category, category)

	def test_custom_category_can_be_added_to_transaction(self):
		data = self.transaction_data(self.account)
		data.update(
			{
				"category_name": "__new__",
				"custom_category": "Pet Care",
			}
		)

		response = self.client.post(reverse("finance:dashboard"), data)

		self.assertRedirects(response, reverse("finance:dashboard"))
		entry = Transaction.objects.get(description="Lunch")
		self.assertEqual(entry.category.category_name, "Pet Care")

	def test_dashboard_chart_summarizes_monthly_debits_by_category(self):
		today = timezone.localdate()
		category = Category.objects.create(category_name="Groceries")
		Transaction.objects.create(
			account=self.account,
			category=category,
			transaction_date=today,
			amount=Decimal("25.00"),
			transaction_type=Transaction.TransactionType.DEBIT,
		)
		Transaction.objects.create(
			account=self.account,
			transaction_date=today,
			amount=Decimal("10.00"),
			transaction_type=Transaction.TransactionType.DEBIT,
		)
		response = self.client.get(reverse("finance:dashboard"))

		self.assertEqual(response.context["monthly_spending"], Decimal("35.00"))
		self.assertEqual(len(response.context["spending_chart"]), 2)
		self.assertEqual(
			response.context["spending_chart"][0]["name"], "Groceries"
		)
		self.assertEqual(
			response.context["spending_chart"][0]["amount"], Decimal("25.00")
		)
		self.assertContains(response, "Spending breakdown")
		self.assertContains(response, "Uncategorized")
