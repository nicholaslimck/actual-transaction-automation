import json
import pytest
from urllib.error import URLError
from unittest.mock import MagicMock
import bank_parsers.fx as fx


@pytest.fixture(autouse=True)
def reset_cache():
    fx.clear_cache()
    yield
    fx.clear_cache()


def _make_fake_resp(payload: dict) -> MagicMock:
    """Return a MagicMock that behaves like a urlopen context-manager response."""
    fake = MagicMock()
    fake.__enter__ = lambda s: s
    fake.__exit__ = MagicMock(return_value=False)
    fake.status = 200
    fake.read.return_value = json.dumps(payload).encode()
    return fake


def test_sgd_returns_1_without_network():
    """SGD short-circuits to 1.0 with no network call required."""
    assert fx.get_rate("SGD") == 1.0
    assert fx.get_rate("sgd") == 1.0  # case-insensitive


def test_successful_live_fetch(monkeypatch):
    """get_rate() parses the JSON response and returns the SGD rate."""
    fake_resp = _make_fake_resp({"rates": {"SGD": 1.29}})
    monkeypatch.setattr(fx, "urlopen", lambda req, timeout: fake_resp)
    assert fx.get_rate("USD") == 1.29


def test_result_is_cached(monkeypatch):
    """After a successful fetch the cached value is returned; urlopen is not called again."""
    fake_resp = _make_fake_resp({"rates": {"SGD": 1.29}})
    monkeypatch.setattr(fx, "urlopen", lambda req, timeout: fake_resp)

    # Populate cache
    fx.get_rate("USD")

    # Break the network; cache should still serve the value
    def _broken(*a, **kw):
        raise URLError("broken")

    monkeypatch.setattr(fx, "urlopen", _broken)
    result = fx.get_rate("USD")
    assert result == 1.29


def test_fallback_when_api_fails(monkeypatch):
    """get_rate_or_fallback() returns the hardcoded fallback when urlopen raises."""
    monkeypatch.setattr(fx, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(URLError("down")))
    result = fx.get_rate_or_fallback("USD")
    assert result == 1.33  # hardcoded _FALLBACK["USD"]


def test_unknown_currency_with_api_failure_returns_none(monkeypatch):
    """get_rate_or_fallback() returns None for a currency absent from both API and _FALLBACK."""
    monkeypatch.setattr(fx, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(URLError("down")))
    result = fx.get_rate_or_fallback("XYZ")
    assert result is None


def test_sgd_from_converts_correctly(monkeypatch):
    """sgd_from() multiplies amount_cents by the live rate and rounds to int."""
    fake_resp = _make_fake_resp({"rates": {"SGD": 1.45}})
    monkeypatch.setattr(fx, "urlopen", lambda req, timeout: fake_resp)
    sgd_cents, rate = fx.sgd_from("EUR", 10000)
    assert rate == 1.45
    assert sgd_cents == 14500  # int(round(10000 * 1.45))


def test_no_negative_caching_on_failure(monkeypatch):
    """A failed fetch should not poison the cache; subsequent call can succeed."""
    call_count = [0]
    fail_resp = _make_fake_resp({"rates": {"SGD": 1.55}})

    def urlopen_side_effect(req, timeout):
        call_count[0] += 1
        if call_count[0] == 1:
            raise URLError("temporary failure")
        return fail_resp

    monkeypatch.setattr(fx, "urlopen", urlopen_side_effect)

    # First call fails
    result1 = fx.get_rate("GBP")
    assert result1 is None

    # Second call succeeds (network recovered) — must NOT get None from cache
    result2 = fx.get_rate("GBP")
    assert result2 == 1.55
