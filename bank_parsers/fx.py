"""Live foreign exchange rates via open.er-api.com (free, no API key).

Rates are cached per session with automatic expiration (3600s). Falls back to
hardcoded approximate rates if live fetch fails. Returns None if both fail.

Usage:
    from bank_parsers.fx import sgd_from, clear_cache
    amount_sgd, rate = sgd_from("USD", 14830)  # 14830 USD cents -> SGD cents
    # or get the rate directly:
    rate = get_rate("USD")  # e.g. 1.277, or None on failure
"""

import json
import logging
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

_API_BASE = "https://open.er-api.com/v6/latest"
_USER_AGENT = "actual-transaction-automation/1.0"
_TIMEOUT = 5  # seconds, for HTTP requests
_CACHE_TTL = 3600  # seconds, rate cache expiration (1 hour)

# In-memory cache: currency -> (rate, timestamp). Only successful fetches cached.
_cache: dict[str, tuple[float, float]] = {}

# Fallback rates when API is unreachable
_FALLBACK: dict[str, float] = {
    "USD": 1.33, "EUR": 1.45, "GBP": 1.70, "AUD": 0.88,
    "JPY": 0.009, "MYR": 0.29, "THB": 0.037, "CNY": 0.19,
    "HKD": 0.17, "KRW": 0.001, "TWD": 0.041,
}


def get_rate(currency: str) -> float | None:
    """Fetch live rate for currency -> SGD. Cached per session with TTL.

    Args:
        currency: ISO 4217 currency code (e.g., "USD", "EUR")

    Returns:
        Rate (e.g. 1.277 for USD -> SGD) or None if fetch and cache miss.
        Cached rates expire after _CACHE_TTL seconds.
    """
    if currency.upper() == "SGD":
        return 1.0

    # Validate currency code format
    if not currency or len(currency) != 3 or not currency.isalpha():
        logger.warning("Invalid currency code: %s", currency)
        return None

    cur = currency.upper()
    
    # Check cache with expiration
    if cur in _cache:
        cached = _cache[cur]
        if cached is not None:
            rate, timestamp = cached
            if time.time() - timestamp < _CACHE_TTL:
                logger.debug("FX rate cache hit %s -> SGD: %s", cur, rate)
                return rate
            else:
                logger.debug("FX rate cache expired for %s", cur)
                del _cache[cur]

    url = f"{_API_BASE}/{cur}"
    try:
        req = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning("FX API returned status %d for %s", resp.status, cur)
                return None
            
            data = json.loads(resp.read().decode())
            raw = data.get("rates", {}).get("SGD")
            if raw is not None:
                rate = float(raw)
                _cache[cur] = (rate, time.time())
                logger.info("FX rate %s -> SGD: %s", cur, rate)
                return rate
            logger.warning("FX rate %s -> SGD not found in response", cur)
    except (URLError, json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        logger.warning("FX rate fetch failed for %s: %s", cur, e)

    return None


def get_rate_or_fallback(currency: str) -> float | None:
    """Fetch live rate, fall back to hardcoded approx if live fetch fails.
    
    Fallback rates are approximate and updated infrequently. Prefer live rates.
    
    Args:
        currency: ISO 4217 currency code (e.g., "USD", "EUR")
    
    Returns:
        Rate (live or fallback) or None if neither available.
    """
    rate = get_rate(currency)
    if rate is not None:
        return rate
    
    fallback = _FALLBACK.get(currency.upper())
    if fallback is not None:
        logger.warning(
            "Using fallback rate %s -> SGD: %s (live fetch failed, rate may be stale)",
            currency.upper(),
            fallback
        )
        return fallback
    
    logger.error("No rate available (live or fallback) for %s", currency.upper())
    return None


def sgd_from(currency: str, amount_cents: int) -> tuple[int, float | None]:
    """Convert amount in foreign currency cents to SGD cents.

    Args:
        currency: ISO 4217 currency code (e.g., "USD", "EUR")
        amount_cents: Amount in cents of the foreign currency (int)

    Returns:
        (sgd_cents, rate_used). rate_used is None if conversion failed
        (amount_cents returned unconverted). Uses live or fallback rates.
    """
    rate = get_rate_or_fallback(currency)
    if rate is not None:
        return int(round(amount_cents * rate)), rate
    return amount_cents, None


def clear_cache():
    """Clear the in-memory rate cache (including failed lookups).
    
    Useful for testing or forcing a refresh of all rates.
    """
    _cache.clear()
