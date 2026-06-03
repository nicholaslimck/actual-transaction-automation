import pytest
from datetime import datetime
from bank_parsers import BaseParser


# ---------------------------------------------------------------------------
# Minimal concrete stub (BaseParser is abstract)
# ---------------------------------------------------------------------------

class _P(BaseParser):
    bank_name = "test"
    sender_pattern = r"test@example\.com"

    def _parse_alert(self, text, email_data):
        return None

    def parse(self, email_data):
        return []


p = _P()


# ---------------------------------------------------------------------------
# to_cents
# ---------------------------------------------------------------------------

class TestToCents:
    def test_plain_decimal(self):
        assert p.to_cents("12.34") == 1234

    def test_s_dollar_prefix(self):
        assert p.to_cents("S$12.34") == 1234

    def test_sgd_prefix(self):
        assert p.to_cents("SGD2100.00") == 210000

    def test_comma_thousands(self):
        assert p.to_cents("1,234.50") == 123450

    def test_small_amount(self):
        assert p.to_cents("0.50") == 50

    def test_bad_input_raises(self):
        with pytest.raises(ValueError):
            p.to_cents("abc")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            p.to_cents("")


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_full_month_name(self):
        assert p.parse_date("31 May 2026") == "2026-05-31"

    def test_two_digit_year_slash(self):
        assert p.parse_date("28/05/26") == "2026-05-28"

    def test_iso_format(self):
        assert p.parse_date("2026-05-31") == "2026-05-31"

    def test_no_year_uses_email_date(self):
        email_date = datetime(2026, 1, 1)
        assert p.parse_date("28 May", email_date) == "2026-05-28"

    def test_no_year_no_email_date_uses_current_year(self):
        result = p.parse_date("31 May")
        current_year = datetime.now().year
        assert result == f"{current_year}-05-31"

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            p.parse_date("NOTADATE!!!")


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_plain_text_preferred_over_html(self):
        result = p.extract_text("hello plain", "<p>ignore html</p>")
        assert result == "hello plain"

    def test_falls_back_to_html_when_plain_empty(self):
        result = p.extract_text("", "<p>Amount &amp; Details</p>")
        assert "&" in result          # &amp; decoded to &
        assert "<p>" not in result    # tags stripped

    def test_html_nbsp_decoded(self):
        result = p.extract_text("", "<td>hello&nbsp;world</td>")
        assert "hello world" in result

    def test_html_nested_tags_stripped(self):
        result = p.extract_text("", "<div><span><b>Clean text</b></span></div>")
        assert "Clean text" in result
        assert "<" not in result

    def test_both_empty_returns_empty_string(self):
        assert p.extract_text("", "") == ""


# ---------------------------------------------------------------------------
# extract_last4
# ---------------------------------------------------------------------------

class TestExtractLast4:
    def test_ending_digits(self):
        assert p.extract_last4("DBS/POSB card ending 7654") == "7654"

    def test_ending_in_digits(self):
        assert p.extract_last4("account ending in 1234") == "1234"

    def test_star_prefix(self):
        # Single * alone doesn't match (banks use ** or **** minimum)
        assert p.extract_last4("*7654") is None

    def test_multi_star_prefix(self):
        assert p.extract_last4("****7654") == "7654"

    def test_xxxx_dashes(self):
        assert p.extract_last4("XXXX-XXXX-XXXX-7654") == "7654"

    def test_plain_name_returns_none(self):
        assert p.extract_last4("Trust Platinum") is None

    def test_empty_string_returns_none(self):
        assert p.extract_last4("") is None

    def test_none_returns_none(self):
        assert p.extract_last4(None) is None


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------

class TestCanHandle:
    def test_matching_sender(self):
        assert p.can_handle("test@example.com") is True

    def test_non_matching_sender(self):
        assert p.can_handle("other@bank.com") is False
