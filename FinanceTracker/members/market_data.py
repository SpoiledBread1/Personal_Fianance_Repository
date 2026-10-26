import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


logger = logging.getLogger(__name__)
FINNHUB_API_URL = "https://finnhub.io/api/v1"
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.^_-]{1,15}$")


class MarketDataError(Exception):
    pass


def _request_finnhub(endpoint, params, api_key):
    query = urlencode({**params, "token": api_key})
    request = Request(
        f"{FINNHUB_API_URL}/{endpoint}?{query}",
        headers={"Accept": "application/json", "User-Agent": "SableFinance/1.0"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise MarketDataError(
            f"Finnhub returned HTTP {error.code} for {endpoint}."
        ) from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise MarketDataError(
            f"Finnhub could not provide {endpoint} data."
        ) from error

    if isinstance(payload, dict) and payload.get("error"):
        raise MarketDataError(f"Finnhub rejected the {endpoint} request.")
    return payload


def _quote(symbol, api_key):
    payload = _request_finnhub("quote", {"symbol": symbol}, api_key)
    if not isinstance(payload, dict):
        raise MarketDataError("Finnhub returned an invalid quote.")

    price = payload.get("c")
    change = payload.get("d")
    change_percent = payload.get("dp")
    previous_close = payload.get("pc")
    values = (price, change, change_percent, previous_close)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in values
    ) or price <= 0:
        raise MarketDataError("Finnhub returned an incomplete quote.")

    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "change_percent": change_percent,
        "previous_close": previous_close,
    }


def _news(api_key):
    payload = _request_finnhub("news", {"category": "general"}, api_key)
    if not isinstance(payload, list):
        raise MarketDataError("Finnhub returned invalid headlines.")

    headlines = []
    for article in payload:
        if not isinstance(article, dict):
            continue
        headline = article.get("headline")
        article_url = article.get("url")
        timestamp = article.get("datetime")
        if (
            not isinstance(headline, str)
            or not headline.strip()
            or not isinstance(article_url, str)
            or not article_url.startswith("https://")
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
        ):
            continue
        headlines.append(
            {
                "headline": headline[:400],
                "source": str(article.get("source", "Market news"))[:100],
                "url": article_url[:2048],
                "published_at": timestamp,
            }
        )
        if len(headlines) == 8:
            break
    return headlines


def get_market_data(api_key):
    symbols = settings.MARKET_WATCHLIST
    if not symbols or len(symbols) > 8 or any(
        not SYMBOL_PATTERN.fullmatch(symbol) for symbol in symbols
    ):
        raise MarketDataError("The market watchlist configuration is invalid.")

    quotes = []
    headlines = []
    errors = []
    jobs = {"headlines": lambda: _news(api_key)}
    jobs.update(
        {
            symbol: lambda symbol=symbol: _quote(symbol, api_key)
            for symbol in symbols
        }
    )

    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = {executor.submit(fetch): name for name, fetch in jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except MarketDataError as error:
                logger.warning("Market data request failed for %s: %s", name, error)
                errors.append(
                    "Market headlines are temporarily unavailable."
                    if name == "headlines"
                    else f"{name} price is temporarily unavailable."
                )
                continue

            if name == "headlines":
                headlines = result
            else:
                quotes.append(result)

    if not quotes and not headlines:
        raise MarketDataError(
            "Market data is temporarily unavailable. Please try again shortly."
        )

    quotes.sort(key=lambda quote: symbols.index(quote["symbol"]))
    headlines.sort(key=lambda article: article["published_at"], reverse=True)
    return {"quotes": quotes, "headlines": headlines, "errors": errors}
