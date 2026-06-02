"""Live foreign exchange rates via open.er-api.com (free, no API key).

Usage:
    from bank_parsers.fx import sgd_from
    amount_sgd = sgd_from("USD", 14830)  # 14830 USD cents -> SGD cents
    # or get the rate directly:
    rate = get_rate("USD")  # e.g. 1.277
"""

import json
import logging
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

_API_BASE = "https://open.er-api.com/v6/latest"
_USER_AGENT = "actual-transaction-automation/1.0"

# In-memory cache: currency -> rate (float) or None on failure
_cache: dict[str, float | None] = {}

# Fallback rates when API is unreachable
_FALLBACK: dict[str, float] = {
    "USD": 1.33, "EUR": 1.45, "GBP": 1.70, "AUD": 0.88,
    "JPY": 0.009, "MYR": 0.29, "THB": 0.037, "CNY": 0.19,
    "HKD": 0.17, "KRW": 0.001, "TWD": 0.041,
}


def get_rate(currency: str) -> float | None:
    """Fetch live rate for currency -> SGD. Cached per session.

    Returns the rate (e.g. 1.277 for USD -> SGD) or None on failure.
    """
    if currency.upper() == "SGD":
        return 1.0

    cur = currency.upper()
    if cur in _cache:
        return _cache[cur]

    url = f"{_API_BASE}/{cur}"
    try:
        req = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            raw = data.get("rates", {}).get("SGD")
            if raw is not None:
                rate = float(raw)
                _cache[cur] = rate
                logger.info("FX rate %s -> SGD: %s", cur, rate)
                return rate
            logger.warning("FX rate %s -> SGD not found in response", cur)
    except (URLError, json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        logger.warning("FX rate fetch failed for %s: %s", cur, e)

    return None


def get_rate_or_fallback(currency: str) -> float | None:
    """Like get_rate(), but falls back to hardcoded approx if live fetch fails."""
    rate = get_rate(currency)
    if rate is not None:
        return rate
    fallback = _FALLBACK.get(currency.upper())
    if fallback is not None:
        logger.info("Using fallback rate %s -> SGD: %s", currency, fallback)
        return fallback
    return None


def sgd_from(currency: str, amount_cents: int) -> tuple[int, float | None]:
    """Convert amount in foreign currency cents to SGD cents.

    Returns (sgd_cents, rate_used). rate_used is None if conversion failed
    (amount is returned unconverted).
    """
    rate = get_rate_or_fallback(currency)
    if rate is not None:
        return int(round(amount_cents * rate)), rate
    return amount_cents, None


def clear_cache():
    """Clear the in-memory rate cache. Useful for testing."""
    _cache.clear()
