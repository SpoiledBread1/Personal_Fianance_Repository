"""Run with: python manage.py test members.tests_investments members.tests_transactions"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import market_data as provider
from .models import Account, AccountType, Holding, MarketCache, WatchlistEntry


def quote(symbol, price='200', close='198', stale=False, days=0):
    price, close = Decimal(price), Decimal(close)
    return {'symbol': symbol, 'price': str(price), 'previous_close': str(close),
            'change': str(price-close), 'change_percent': str((price-close)/close*100),
            'quote_at': (timezone.now()-timedelta(days=days)).isoformat(),
            'fetched_at': timezone.now().isoformat(), 'stale': stale}


@override_settings(FINNHUB_API_KEY='testing-provider-key')
class InvestmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='owner')
        self.other = User.objects.create_user(username='other')
        self.client.force_login(self.user)
        self.lookup = patch('members.investment_forms.resolve_instrument', side_effect=lambda s: {'symbol':s, 'name':'Example '+s})
        self.lookup.start()
        self.addCleanup(self.lookup.stop)

    def test_add_fractional_shares_normalizes_symbol_and_preserves_balances(self):
        kind = AccountType.objects.create(type_name='Investments')
        account = Account.objects.create(user=self.user, account_type=kind, account_name='Broker', current_balance=123)
        response = self.client.post(reverse('finance:holding-add'), {'symbol':'aapl', 'shares':'2.125'})
        self.assertRedirects(response, reverse('finance:dashboard')+'#stocks-news')
        entry = Holding.objects.get(user=self.user)
        self.assertEqual(entry.symbol, 'AAPL')
        self.assertEqual(entry.shares, Decimal('2.125'))
        account.refresh_from_db()
        self.assertEqual(account.current_balance, 123)

    def test_duplicates_invalid_symbols_and_share_quantities(self):
        Holding.objects.create(user=self.user, symbol='AAPL', name='Apple', shares=1)
        for data in [{'symbol':'AAPL','shares':'2'}, {'symbol':'<script>','shares':'2'},
                     {'symbol':'MSFT','shares':'0'}, {'symbol':'MSFT','shares':'-1'},
                     {'symbol':'MSFT','shares':'NaN'}, {'symbol':'MSFT','shares':'0.0000001'}]:
            with self.subTest(data=data):
                response = self.client.post(reverse('finance:holding-add'), data)
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.context['form'].errors)
        self.assertEqual(Holding.objects.filter(user=self.user).count(),1)
        # Same symbol in a different person's portfolio is legitimate.
        self.client.force_login(self.other)
        self.client.post(reverse('finance:holding-add'), {'symbol':'AAPL','shares':'3'})
        self.assertEqual(Holding.objects.count(),2)

    def test_edit_existing_shares_works_without_provider(self):
        entry = Holding.objects.create(user=self.user, symbol='AAPL', name='Apple', shares=1)
        with patch('members.investment_forms.resolve_instrument', side_effect=AssertionError('must not call provider')):
            response = self.client.post(reverse('finance:holding-edit',args=[entry.pk]), {'symbol':'AAPL','shares':'1.5'})
        self.assertEqual(response.status_code,302)
        entry.refresh_from_db()
        self.assertEqual(entry.shares, Decimal('1.5'))

    def test_remove_requires_confirmation_post_and_user_ownership(self):
        entry = Holding.objects.create(user=self.user,symbol='AAPL',name='Apple',shares=1)
        edit = reverse('finance:holding-edit',args=[entry.pk])
        remove = reverse('finance:holding-delete',args=[entry.pk])
        self.assertContains(self.client.get(edit),'Remove holding')
        self.assertContains(self.client.get(remove),'Keep holding')
        self.assertTrue(Holding.objects.filter(pk=entry.pk).exists())
        self.client.force_login(self.other)
        for url in (edit,remove):
            self.assertEqual(self.client.get(url).status_code,404)
            self.assertEqual(self.client.post(url, {'symbol':'AAPL','shares':'5'}).status_code,404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(remove).status_code,302)
        self.assertFalse(Holding.objects.filter(pk=entry.pk).exists())

    def test_watchlist_does_not_count_as_owned_and_remove_is_post_only(self):
        self.client.post(reverse('finance:watchlist-add'), {'symbol':'MSFT'})
        entry = WatchlistEntry.objects.get(user=self.user)
        remove = reverse('finance:watchlist-delete',args=[entry.pk])
        self.assertEqual(self.client.get(remove).status_code,405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(remove).status_code,404)
        self.client.force_login(self.user)
        with patch('members.market_data_views.load_market_content',return_value=({'MSFT':quote('MSFT')},[],[])) as load:
            data=self.client.get(reverse('finance:market-data')).json()
        self.assertEqual(data['summary']['count'],0)
        self.assertEqual(data['summary']['market_value'],'0.00')
        load.assert_called_once_with(['MSFT'],[])
        self.assertEqual(self.client.post(remove).status_code,302)

    def test_authentication_and_csrf(self):
        entry=Holding.objects.create(user=self.user,symbol='AAPL',name='Apple',shares=1)
        guarded=[reverse('finance:holding-add'),reverse('finance:holding-edit',args=[entry.pk]),
                 reverse('finance:holding-delete',args=[entry.pk]),reverse('finance:watchlist-add'),
                 reverse('finance:instrument-search'),reverse('finance:market-data')]
        anonymous=Client()
        for url in guarded:
            self.assertEqual(anonymous.get(url).status_code,302)
        secure=Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(reverse('finance:holding-add'),{'symbol':'AAPL','shares':3}).status_code,403)
        self.assertEqual(secure.post(guarded[2]).status_code,403)

    def test_dashboard_contains_approved_columns_and_safe_empty_state(self):
        page=self.client.get(reverse('finance:dashboard'))
        for text in ('Shares','Price chng','Day change $','Market value','News for your holdings','Add holding'):
            self.assertContains(page,text)
        self.assertNotContains(page,'Avg. cost')
        self.assertNotContains(page,'FINNHUB_API_KEY')

    def test_portfolio_math_fractional_shares_and_personal_news_symbols(self):
        Holding.objects.create(user=self.user,symbol='AAPL',name='Apple',shares=Decimal('2.5'))
        Holding.objects.create(user=self.user,symbol='MSFT',name='Microsoft',shares=5)
        Holding.objects.create(user=self.other,symbol='NVDA',name='Private',shares=999)
        WatchlistEntry.objects.create(user=self.user,symbol='GOOGL',name='Alphabet')
        with patch('members.market_data_views.load_market_content',return_value=({'AAPL':quote('AAPL'), 'MSFT':quote('MSFT','420','425')},[],[])) as load:
            response=self.client.get(reverse('finance:market-data'))
        data=response.json()
        load.assert_called_once_with(['AAPL','MSFT','GOOGL'],['AAPL','MSFT'])
        self.assertEqual(data['holdings'][0]['day_change'],'5.00')
        self.assertEqual(data['holdings'][0]['market_value'],'500.00')
        self.assertEqual(data['holdings'][1]['day_change'],'-25.00')
        self.assertEqual(data['summary']['market_value'],'2600.00')
        self.assertEqual(data['summary']['day_change'],'-20.00')
        self.assertEqual(data['summary']['day_change_percent'],'-0.76')
        self.assertNotIn('NVDA',response.content.decode())
        self.assertIn('no-store',response['Cache-Control'])
        self.assertNotIn('testing-provider-key',response.content.decode())

    def test_missing_quote_never_becomes_zero_or_partial_total(self):
        Holding.objects.create(user=self.user,symbol='AAPL',name='Apple',shares=10)
        with patch('members.market_data_views.load_market_content',return_value=({'AAPL':None},[],['Unavailable'])):
            data=self.client.get(reverse('finance:market-data')).json()
        self.assertIsNone(data['holdings'][0]['market_value'])
        self.assertIsNone(data['summary']['market_value'])
        self.assertIsNone(data['summary']['day_change'])

    def test_stale_or_mixed_session_quotes_disable_combined_day_change(self):
        Holding.objects.create(user=self.user,symbol='AAPL',name='Apple',shares=10)
        Holding.objects.create(user=self.user,symbol='MSFT',name='Microsoft',shares=1)
        for stale,days in [(True,0),(False,3)]:
            with self.subTest(stale=stale,days=days):
                quotes={'AAPL':quote('AAPL'), 'MSFT':quote('MSFT',stale=stale,days=days)}
                with patch('members.market_data_views.load_market_content',return_value=(quotes,[],[])):
                    data=self.client.get(reverse('finance:market-data')).json()
                self.assertEqual(data['summary']['market_value'],'2200.00')
                self.assertIsNone(data['summary']['day_change'])

    @override_settings(FINNHUB_API_KEY='')
    def test_missing_api_key_returns_saved_holdings_without_leaking_configuration(self):
        Holding.objects.create(user=self.user,symbol='AAPL',name='Apple',shares=1)
        data=self.client.get(reverse('finance:market-data')).json()
        self.assertFalse(data['configured'])
        self.assertEqual(data['holdings'][0]['symbol'],'AAPL')
        self.assertIsNone(data['holdings'][0]['quote'])
        self.assertNotIn('FINNHUB',str(data))


@override_settings(FINNHUB_API_KEY='testing-provider-key')
class ProviderTests(TestCase):
    def test_quote_math_timestamp_and_invalid_values(self):
        raw={'c':135,'pc':130,'t':int(timezone.now().timestamp())}
        with patch.object(provider,'_request_finnhub',return_value=raw):
            data=provider._quote('NVDA',None)
        self.assertEqual(data['change'],'5')
        self.assertEqual(data['price'],'135')
        for changes in [{'c':0},{'c':float('nan')},{'pc':0},{'t':0},{'c':True}]:
            with patch.object(provider,'_request_finnhub',return_value={**raw,**changes}):
                with self.assertRaises(provider.MarketDataError): provider._quote('NVDA',None)

    def test_shared_quote_cache_stale_fallback_and_error_backoff(self):
        fresh=MagicMock(return_value={'price':'100'})
        first=provider.cached_data('quote:AAPL',fresh,300)
        second=provider.cached_data('quote:AAPL',fresh,300)
        self.assertEqual(first[0],second[0])
        self.assertEqual(fresh.call_count,1)
        row=MarketCache.objects.exclude(key__endswith='budget').get()
        MarketCache.objects.filter(pk=row.pk).update(fetched_at=timezone.now()-timedelta(minutes=6),refresh_after=timezone.now()-timedelta(seconds=1))
        failing=MagicMock(side_effect=provider.MarketDataError('offline'))
        saved=provider.cached_data('quote:AAPL',failing,300)
        self.assertTrue(saved[1])
        self.assertEqual(saved[0]['price'],'100')
        provider.cached_data('quote:AAPL',failing,300)
        self.assertEqual(failing.call_count,1)

    def test_failed_initial_request_does_not_cache_fake_quote(self):
        fetch=MagicMock(side_effect=provider.MarketDataError('offline'))
        for _ in range(2):
            with self.assertRaises(provider.MarketDataError): provider.cached_data('quote:BAD',fetch,300)
        self.assertEqual(fetch.call_count,1)
        self.assertIsNone(MarketCache.objects.get(key=provider._prefix()+'quote:BAD').fetched_at)

    def test_concurrent_refresh_lease_uses_existing_snapshot(self):
        MarketCache.objects.create(key=provider._prefix()+'quote:AAPL',payload={'price':'100'},fetched_at=timezone.now()-timedelta(hours=1),lease_until=timezone.now()+timedelta(seconds=20))
        fetch=MagicMock()
        data=provider.cached_data('quote:AAPL',fetch,300)
        self.assertTrue(data[1])
        fetch.assert_not_called()

    def test_request_budget_and_key_auth_header(self):
        with patch.object(provider.time,'time',return_value=600):
            for _ in range(50): provider._reserve_call()
            with self.assertRaises(provider.MarketDataError): provider._reserve_call()
        with patch.object(provider.time,'time',return_value=660): provider._reserve_call()
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"c":100}'
        with patch.object(provider,'urlopen',return_value=response) as opener:
            provider._request_finnhub('quote',{'symbol':'AAPL'})
        request=opener.call_args.args[0]
        self.assertNotIn('testing-provider-key',request.full_url)
        self.assertEqual(request.get_header('X-finnhub-token'),'testing-provider-key')

    def test_us_symbol_catalog_covers_etfs_and_excludes_other_currencies(self):
        items=[{'symbol':'AAPL','description':'Apple Inc','currency':'USD','type':'Common Stock'},
               {'symbol':'VOO','description':'Vanguard S&P 500 ETF','currency':'USD','type':'ETP'},
               {'symbol':'BAD','description':'Non USD','currency':'CAD','type':'Common Stock'}]
        with patch.object(provider,'_request_finnhub',return_value=items) as request:
            self.assertEqual(provider.resolve_instrument('VOO')['symbol'],'VOO')
            self.assertEqual(provider.search_instruments('apple')[0]['symbol'],'AAPL')
            with self.assertRaises(provider.MarketDataError): provider.resolve_instrument('BAD')
        self.assertEqual(request.call_count,1)

    def test_company_news_filters_urls_and_duplicate_articles_merge(self):
        stamp=int(timezone.now().timestamp())
        items=[{'headline':'Example','url':'https://example.com/article','source':'Publisher','datetime':stamp},
               {'headline':'Unsafe','url':'javascript:alert(1)','datetime':stamp}]
        with patch.object(provider,'_request_finnhub',return_value=items) as request:
            news=provider._company_news('AAPL',None)
        self.assertEqual(len(news),1)
        self.assertEqual(request.call_args.args[0],'company-news')
        self.assertEqual(request.call_args.args[1]['symbol'],'AAPL')
        with patch.object(provider,'_quote',side_effect=lambda s,d:quote(s)), patch.object(provider,'_company_news',return_value=news):
            quotes,headlines,errors=provider.load_market_content(['AAPL','MSFT'],['AAPL','MSFT'])
        self.assertEqual(len(headlines),1)
        self.assertEqual(headlines[0]['symbols'],['AAPL','MSFT'])
        self.assertEqual(errors,[])
