import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone

from .market_data import MarketDataError, get_market_data


logger = logging.getLogger(__name__)
CACHE_SECONDS = 300


@login_required
def market_data(request):
    if not settings.FINNHUB_API_KEY:
        return JsonResponse(
            {
                "error": (
                    "Market data is not configured yet. Add FINNHUB_API_KEY "
                    "to the app's environment settings."
                )
            },
            status=503,
        )

    symbols = ",".join(settings.MARKET_WATCHLIST)
    cache_key = f"market-data:finnhub:{symbols}"
    cached = cache.get(cache_key)
    if cached is None:
        try:
            data = get_market_data(settings.FINNHUB_API_KEY)
        except MarketDataError as error:
            logger.warning("Market data could not be loaded: %s", error)
            return JsonResponse({"error": str(error)}, status=502)
        updated_at = timezone.now().isoformat()
        if not data["errors"]:
            cache.set(
                cache_key,
                {"data": data, "updated_at": updated_at},
                CACHE_SECONDS,
            )
    else:
        data = cached["data"]
        updated_at = cached["updated_at"]

    return JsonResponse({**data, "updated_at": updated_at})
