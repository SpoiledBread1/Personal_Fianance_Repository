from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Account, AccountType, Category, Transaction
from .news import fetch_cnbc_articles


class CnbcFeedTests(TestCase):
    def test_feed_reader_keeps_https_cnbc_story_links(self):
        feed = b"""<rss><channel>
            <item><title>Finance headline</title><description>Summary</description>
                <link>https://www.cnbc.com/finance/story.html</link>
                <pubDate>Sat, 07 Nov 2026 12:00:00 GMT</pubDate></item>
            <item><title>External link</title><link>https://example.com/story</link></item>
            <item><title>Insecure link</title><link>http://www.cnbc.com/story</link></item>
        </channel></rss>"""
        with patch("members.news.urlopen", return_value=BytesIO(feed)):
            articles = fetch_cnbc_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Finance headline")
        self.assertEqual(
            articles[0]["url"], "https://www.cnbc.com/finance/story.html"
        )


class FinanceSectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="sections-user", password="Strong-test-pass-98!"
        )
        self.account_type = AccountType.objects.create(type_name="Checking")
        self.account = Account.objects.create(
            user=self.user,
            account_type=self.account_type,
            account_name="Daily checking",
            current_balance=Decimal("125.00"),
        )
        self.category = Category.objects.create(category_name="Dining")
        self.client.force_login(self.user)

    def add_transaction(
        self, description, transaction_date, transaction_type="debit", amount="12.50"
    ):
        return Transaction.objects.create(
            account=self.account,
            category=self.category,
            description=description,
            transaction_date=transaction_date,
            transaction_type=transaction_type,
            amount=Decimal(amount),
        )

    def test_transactions_filter_year_type_category_and_search(self):
        matching = self.add_transaction("Coffee shop", date(2025, 5, 12))
        self.add_transaction(
            "Salary",
            date(2025, 4, 1),
            transaction_type=Transaction.TransactionType.CREDIT,
            amount="100.00",
        )
        self.add_transaction("Older coffee", date(2024, 5, 12))

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
        self.assertEqual(response.context["selected_year"], "2025")
        self.assertContains(response, "USD 12.50")

    def test_transaction_page_does_not_expose_another_users_records(self):
        other_user = get_user_model().objects.create_user(
            username="other-sections-user", password="Strong-test-pass-98!"
        )
        other_account = Account.objects.create(
            user=other_user,
            account_type=self.account_type,
            account_name="Other account",
        )
        Transaction.objects.create(
            account=other_account,
            category=self.category,
            description="Private transaction",
            transaction_date=date(2025, 2, 1),
            transaction_type=Transaction.TransactionType.DEBIT,
            amount=Decimal("42.00"),
        )

        response = self.client.get(
            reverse("finance:transactions"), {"year": "all"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Private transaction")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_section_pages_render_for_signed_in_user(self):
        for route_name in ("budgets", "balances", "news_stocks"):
            with self.subTest(route_name=route_name):
                if route_name == "news_stocks":
                    with patch(
                        "members.dashboard_views.fetch_cnbc_articles",
                        return_value=[],
                    ):
                        response = self.client.get(reverse(f"finance:{route_name}"))
                else:
                    response = self.client.get(reverse(f"finance:{route_name}"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "News &amp; Stocks")

    def test_homepage_includes_cnbc_news_preview(self):
        articles = [
            {
                "title": "Markets update",
                "description": "A test market headline.",
                "url": "https://www.cnbc.com/finance/test-story.html",
                "published": "Nov 07, 2026",
            }
        ]
        with patch(
            "members.dashboard_views.fetch_cnbc_articles", return_value=articles
        ):
            response = self.client.get(reverse("finance:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Markets update")
        self.assertContains(response, reverse("finance:news_stocks"))

    def test_stock_lookup_only_builds_cnbc_quote_links_for_valid_symbols(self):
        with patch(
            "members.dashboard_views.fetch_cnbc_articles", return_value=[]
        ):
            valid_response = self.client.get(
                reverse("finance:news_stocks"), {"symbol": "BRK.B"}
            )
            invalid_response = self.client.get(
                reverse("finance:news_stocks"), {"symbol": "../../example.com"}
            )

        self.assertContains(
            valid_response, "https://www.cnbc.com/quotes/BRK.B"
        )
        self.assertContains(invalid_response, "Enter a valid stock symbol")
        self.assertNotContains(invalid_response, "https://www.cnbc.com/quotes/../")
