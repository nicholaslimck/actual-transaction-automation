"""Tests for EmailFetcher static helpers — no IMAP connection required."""
import re
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from email_fetcher import EmailFetcher


# ---------------------------------------------------------------------------
# _decode_header
# ---------------------------------------------------------------------------

def test_decode_header_plain_ascii():
    assert EmailFetcher._decode_header("Hello World") == "Hello World"


def test_decode_header_utf8_encoded_word():
    # "=?UTF-8?q?15_Max_Miles_earned!?=" decodes to "15 Max Miles earned!"
    encoded = "=?UTF-8?q?15_Max_Miles_earned!?="
    result = EmailFetcher._decode_header(encoded)
    assert result == "15 Max Miles earned!"


def test_decode_header_base64_encoded_word():
    # "Subject" base64-encoded in UTF-8
    import base64
    word = base64.b64encode("こんにちは".encode()).decode()
    encoded = f"=?utf-8?b?{word}?="
    result = EmailFetcher._decode_header(encoded)
    assert result == "こんにちは"


def test_decode_header_mixed_plain_and_encoded():
    # "Hello =?utf-8?q?World?=" → "Hello World"
    result = EmailFetcher._decode_header("Hello =?utf-8?q?World?=")
    assert "Hello" in result and "World" in result


def test_decode_header_empty():
    assert EmailFetcher._decode_header("") == ""


# ---------------------------------------------------------------------------
# _decode_payload
# ---------------------------------------------------------------------------

def _make_part(payload: bytes | None, charset: str | None = "utf-8", raises: bool = False):
    """Build a MagicMock that mimics email.message.Message."""
    part = MagicMock()
    part.get_content_charset.return_value = charset
    if raises:
        part.get_payload.side_effect = Exception("decode error")
    else:
        part.get_payload.return_value = payload
    return part


def test_decode_payload_utf8_bytes():
    part = _make_part("Hello, World!".encode("utf-8"))
    assert EmailFetcher._decode_payload(part) == "Hello, World!"


def test_decode_payload_latin1():
    part = _make_part("caf\xe9".encode("latin-1"), charset="latin-1")
    assert EmailFetcher._decode_payload(part) == "café"


def test_decode_payload_none_payload_returns_empty():
    part = _make_part(None)
    assert EmailFetcher._decode_payload(part) == ""


def test_decode_payload_exception_returns_empty():
    part = _make_part(b"anything", raises=True)
    assert EmailFetcher._decode_payload(part) == ""


def test_decode_payload_no_charset_falls_back_to_utf8():
    """None charset → falls back to utf-8."""
    part = _make_part("SGD 6.98".encode("utf-8"), charset=None)
    assert EmailFetcher._decode_payload(part) == "SGD 6.98"


def test_decode_payload_replacement_chars_on_bad_bytes():
    """Undecodable bytes with the declared charset should not raise — replaced."""
    part = _make_part(b"\xff\xfe garbage", charset="ascii")
    result = EmailFetcher._decode_payload(part)
    assert isinstance(result, str)  # replacement chars, not an exception


# ---------------------------------------------------------------------------
# _date_days_ago
# ---------------------------------------------------------------------------

def test_date_days_ago_format():
    result = EmailFetcher._date_days_ago(7)
    # Must match DD-Mon-YYYY, e.g. "25-May-2026"
    assert re.fullmatch(r"\d{2}-[A-Z][a-z]{2}-\d{4}", result), f"unexpected format: {result}"


def test_date_days_ago_is_correct_delta():
    expected = (datetime.now() - timedelta(days=14)).strftime("%d-%b-%Y")
    assert EmailFetcher._date_days_ago(14) == expected


def test_date_days_ago_zero():
    expected = datetime.now().strftime("%d-%b-%Y")
    assert EmailFetcher._date_days_ago(0) == expected
