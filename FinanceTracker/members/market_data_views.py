from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .market_data import MarketDataError, load_market_content, search_instruments
from .models import Holding, WatchlistEntry


def _money(value):
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None


@login_required
@never_cache
@require_GET
def market_data(request):
    holdings = list(Holding.objects.filter(user=request.user))
    watchlist = list(WatchlistEntry.objects.filter(user=request.user))
    owned = [entry.symbol for entry in holdings]
    symbols = list(dict.fromkeys(owned + [entry.symbol for entry in watchlist]))
    configured = bool(getattr(settings, "FINNHUB_API_KEY", ""))
    if configured:
        quotes, headlines, errors = load_market_content(symbols, owned)
    else:
        quotes, headlines, errors = {}, [], ["Automatic prices and news are not available yet."]

    rows, market_total, day_total, sessions = [], Decimal("0"), Decimal("0"), set()
    complete, fresh = True, True
    for entry in holdings:
        quote = quotes.get(entry.symbol)
        value = day_change = None
        if quote:
            value = Decimal(quote["price"]) * entry.shares
            day_change = Decimal(quote["change"]) * entry.shares
            market_total += value
            day_total += day_change
            sessions.add(parse_datetime(quote["quote_at"]).astimezone(ZoneInfo("America/New_York")).date())
            fresh = fresh and not quote["stale"]
        else:
            complete = fresh = False
        rows.append({"id": entry.pk, "symbol": entry.symbol, "name": entry.name,
                     "shares": str(entry.shares), "quote": quote, "market_value": _money(value),
                     "day_change": _money(day_change),
                     "edit_url": reverse("finance:holding-edit", args=[entry.pk])})
    session_consistent = len(sessions) <= 1
    if not session_consistent:
        errors.append("Quotes cover different trading sessions; combined day change is unavailable.")
    if not complete:
        errors.append("Portfolio totals are unavailable until every holding has a quote.")
    previous_value = market_total - day_total
    display_day = complete and fresh and session_consistent
    return JsonResponse({
        "holdings": rows,
        "watchlist": [{"id": e.pk, "symbol": e.symbol, "name": e.name, "quote": quotes.get(e.symbol)} for e in watchlist],
        "headlines": headlines, "errors": list(dict.fromkeys(errors)), "configured": configured,
        "checked_at": timezone.now().isoformat(), "refresh_seconds": 60 if errors else 300,
        "summary": {"count": len(holdings), "market_value": _money(market_total) if complete else None,
                    "day_change": _money(day_total) if display_day else None,
                    "day_change_percent": _money(day_total / previous_value * 100) if display_day and previous_value > 0 else None,
                    "stale": not fresh, "complete": complete},
    })


@login_required
@never_cache
@require_GET
def instrument_search(request):
    query = request.GET.get("q", "").strip()[:60]
    try:
        results = search_instruments(query)
    except MarketDataError as error:
        return JsonResponse({"results": [], "error": str(error)}, status=503)
    return JsonResponse({"results": results})

