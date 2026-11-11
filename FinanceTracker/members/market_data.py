"""Finnhub transport, shared PostgreSQL cache and a conservative request budget.

No private holdings or API keys are ever stored in the shared market cache.
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import MarketCache

logger = logging.getLogger(__name__)
FINNHUB_API_URL = "https://finnhub.io/api/v1"
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?$")
QUOTE_SECONDS = 300
NEWS_SECONDS = 1800


class MarketDataError(Exception):
    pass


def _prefix():
    key = getattr(settings, "FINNHUB_API_KEY", "")
    if not key:
        raise MarketDataError("Market prices and symbol lookup are not available yet.")
    return "fh:" + hashlib.sha256(key.encode()).hexdigest()[:12] + ":"


def _reserve_call():
    # Database-backed so multiple Gunicorn workers share the same allowance.
    key = _prefix() + "budget"
    MarketCache.objects.get_or_create(key=key)
    window = int(time.time()) // 60
    with transaction.atomic():
        row = MarketCache.objects.select_for_update().get(key=key)
        count = row.payload.get("count", 0) if row.payload.get("window") == window else 0
        if count >= 50:
            raise MarketDataError("Market data is busy. Please try again in a minute.")
        row.payload = {"window": window, "count": count + 1}
        row.save(update_fields=["payload"])


def _request_finnhub(endpoint, params, deadline=None):
    if deadline is not None and time.monotonic() >= deadline:
        raise MarketDataError("Some updates are pending. Please refresh in a minute.")
    _reserve_call()
    # Header authentication keeps the token out of URLs and request error strings.
    request = Request(
        f"{FINNHUB_API_URL}/{endpoint}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "SableFinance/2.0", "X-Finnhub-Token": settings.FINNHUB_API_KEY},
    )
    timeout = min(4, max(0.2, deadline - time.monotonic())) if deadline is not None else 4
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        logger.warning("Finnhub endpoint %s returned HTTP %s", endpoint, error.code)
        raise MarketDataError("Market data is temporarily unavailable. Please try again shortly.") from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise MarketDataError("Market data is temporarily unavailable. Please try again shortly.") from error
    if isinstance(payload, dict) and payload.get("error"):
        raise MarketDataError("This market data is unavailable with the current provider access.")
    return payload


def cached_data(key, fetch, seconds):
    key = _prefix() + key
    row, _ = MarketCache.objects.get_or_create(key=key)
    now = timezone.now()
    if row.refresh_after and row.refresh_after > now:
        if row.fetched_at:
            return row.payload, (now - row.fetched_at).total_seconds() >= seconds, row.fetched_at
        raise MarketDataError("Market data is temporarily unavailable. Please retry in a minute.")
    leased = MarketCache.objects.filter(pk=row.pk).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=now)
    ).update(lease_until=now + timedelta(seconds=30))
    if not leased:
        if row.fetched_at:
            return row.payload, True, row.fetched_at
        raise MarketDataError("Market data is loading. Please retry shortly.")
    try:
        payload = fetch()
    except MarketDataError:
        MarketCache.objects.filter(pk=row.pk).update(refresh_after=now + timedelta(seconds=60), lease_until=None)
        if row.fetched_at:
            return row.payload, True, row.fetched_at
        raise
    except Exception:
        MarketCache.objects.filter(pk=row.pk).update(lease_until=None)
        raise
    fetched_at = timezone.now()
    MarketCache.objects.filter(pk=row.pk).update(
        payload=payload, fetched_at=fetched_at,
        refresh_after=fetched_at + timedelta(seconds=seconds), lease_until=None,
    )
    return payload, False, fetched_at


def _catalog():
    data = _request_finnhub("stock/symbol", {"exchange": "US", "currency": "USD"})
    if not isinstance(data, list):
        raise MarketDataError("Symbol lookup is temporarily unavailable.")
    allowed_types = {"Common Stock", "ETP", "ETF", "REIT", "ADR", "Preferred Stock"}
    instruments = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol", "")
        if (not isinstance(symbol, str) or not SYMBOL_PATTERN.fullmatch(symbol)
                or item.get("currency") != "USD" or item.get("type") not in allowed_types):
            continue
        instruments[symbol] = {"symbol": symbol, "name": str(item.get("description") or symbol)[:160]}
    if not instruments:
        raise MarketDataError("Symbol lookup is temporarily unavailable.")
    return instruments


def instrument_catalog():
    catalog, _, _ = cached_data("symbols:US:USD", _catalog, 86400)
    return catalog


def resolve_instrument(symbol):
    instrument = instrument_catalog().get(symbol)
    if not instrument:
        raise MarketDataError("Choose a supported US-listed stock or ETF priced in USD.")
    return instrument


def search_instruments(query):
    query = query.strip().upper()
    if len(query) < 2:
        return []
    catalog = instrument_catalog()
    matches = [item for item in catalog.values() if query in item["symbol"] or query in item["name"].upper()]
    matches.sort(key=lambda item: (item["symbol"] != query, not item["symbol"].startswith(query), item["symbol"]))
    return matches[:12]


def _number(value):
    if isinstance(value, bool):
        raise MarketDataError("The provider returned an incomplete quote.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MarketDataError("The provider returned an incomplete quote.")
    if not number.is_finite():
        raise MarketDataError("The provider returned an incomplete quote.")
    return number


def _quote(symbol, deadline):
    data = _request_finnhub("quote", {"symbol": symbol}, deadline)
    if not isinstance(data, dict):
        raise MarketDataError("The provider returned an incomplete quote.")
    price, close = _number(data.get("c")), _number(data.get("pc"))
    stamp = data.get("t")
    if price <= 0 or close <= 0 or isinstance(stamp, bool) or not isinstance(stamp, int):
        raise MarketDataError("No valid quote is available for this symbol.")
    try:
        quote_at = datetime.fromtimestamp(stamp, dt_timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise MarketDataError("The provider returned an invalid quote time.")
    if quote_at.year < 2000 or quote_at > timezone.now() + timedelta(minutes=5):
        raise MarketDataError("The provider returned an invalid quote time.")
    change = price - close
    return {"symbol": symbol, "price": str(price), "previous_close": str(close),
            "change": str(change), "change_percent": str(change / close * 100),
            "quote_at": quote_at.isoformat()}


def _company_news(symbol, deadline):
    today = timezone.now().date()
    data = _request_finnhub("company-news", {
        "symbol": symbol, "from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat(),
    }, deadline)
    if not isinstance(data, list):
        raise MarketDataError("Company headlines are temporarily unavailable.")
    news = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title, url, stamp = item.get("headline"), item.get("url"), item.get("datetime")
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
            valid_url = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError:
            valid_url = False
        if (not valid_url or isinstance(stamp, bool) or not isinstance(stamp, int)
                or stamp < int((timezone.now() - timedelta(days=8)).timestamp())
                or stamp > int((timezone.now() + timedelta(minutes=5)).timestamp())):
            continue
        news.append({"headline": title.strip()[:400], "url": url[:2048],
                     "source": str(item.get("source") or "Publisher")[:100], "published_at": stamp})
    return sorted(news, key=lambda item: item["published_at"], reverse=True)[:8]


def load_market_content(symbols, owned_symbols):
    quotes, errors = {}, []
    deadline = time.monotonic() + 12
    # All holdings and watchlist quotes take priority over news on a cold start.
    for symbol in symbols:
        try:
            data, stale, fetched = cached_data("quote:" + symbol, lambda s=symbol: _quote(s, deadline), QUOTE_SECONDS)
            quotes[symbol] = {**data, "stale": stale, "fetched_at": fetched.isoformat()}
            if stale:
                errors.append(f"{symbol}: showing a saved quote; refresh is unavailable.")
        except MarketDataError:
            quotes[symbol] = None
            errors.append(f"{symbol}: quote is unavailable.")
    merged = {}
    for symbol in owned_symbols:
        try:
            articles, stale, _ = cached_data("news:" + symbol, lambda s=symbol: _company_news(s, deadline), NEWS_SECONDS)
            if stale:
                errors.append(f"{symbol}: showing saved headlines.")
            for article in articles:
                existing = merged.setdefault(article["url"], {**article, "symbols": []})
                if symbol not in existing["symbols"]:
                    existing["symbols"].append(symbol)
        except MarketDataError:
            errors.append(f"{symbol}: recent headlines are unavailable.")
    news = sorted(merged.values(), key=lambda item: item["published_at"], reverse=True)[:160]
    return quotes, news, errors
