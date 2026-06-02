"""Base parser class for bank transaction alert emails."""
from abc import ABC, abstractmethod
import hashlib
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Abstract base for bank email parsers.

    Each bank subclass must implement:
      - bank_name: human-friendly name
      - sender_pattern: regex to match sender email
      - _parse_alert(): extract one transaction from email text, or None
    """

    @property
    @abstractmethod
    def bank_name(self) -> str:
        ...

    @property
    @abstractmethod
    def sender_pattern(self) -> str:
        ...

    @staticmethod
    def _content_id(prefix: str, date: str, amount: int, payee: str, time: str = "") -> str:
        """Stable content-hash transaction id.

        Including `time` disambiguates two genuinely separate purchases with the
        same date, amount, and payee (e.g. two identical coffees). Falls back to
        the date-only recipe when the email carries no time component.
        """
        raw = f"{date}|{time}|{amount}|{payee}" if time else f"{date}|{amount}|{payee}"
        return f"{prefix}:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    @abstractmethod
    def _parse_alert(self, text: str, email_data: dict) -> "dict | None":
        """Parse email text into a transaction dict, or None if unrecognised."""
        ...

    def parse(self, email_data: dict) -> list[dict]:
        """Template method: extract text, call _parse_alert, log on miss."""
        text = self.extract_text(email_data.get("body_text", ""), email_data.get("body_html", ""))
        logger.debug("%s raw text:\n%s", self.bank_name, text[:2000])
        txn = self._parse_alert(text, email_data)
        if not txn:
            logger.warning("Could not parse %s. Subject: %s", self.bank_name, email_data.get("subject", ""))
        return [txn] if txn else []

    def can_handle(self, sender: str) -> bool:
        return bool(re.search(self.sender_pattern, sender, re.IGNORECASE))

    @staticmethod
    def extract_text(body_text: str, body_html: str) -> str:
        """Use plain text if available, fall back to stripping HTML tags."""
        if body_text.strip():
            return body_text
        # Strip HTML tags for rough text extraction
        clean = re.sub(r"<[^>]+>", " ", body_html)
        # Decode common HTML entities
        clean = clean.replace("&amp;", "&")
        clean = clean.replace("&nbsp;", " ")
        clean = clean.replace("&lt;", "<")
        clean = clean.replace("&gt;", ">")
        clean = clean.replace("&quot;", '"')
        clean = clean.replace("&#39;", "'")
        clean = re.sub(r"&[a-zA-Z]+;", " ", clean)  # catch any other entities
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    @staticmethod
    def to_cents(amount_str: str) -> int:
        """Convert '12.34' or 'S$12.34' to 1234 cents (negative by default)."""
        cleaned = re.sub(r"[^\d.\-]", "", amount_str)
        try:
            return int(round(float(cleaned) * 100))
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert amount to cents: {amount_str!r}")

    @staticmethod
    def parse_date(date_str: str, email_date=None) -> str:
        """Try to parse various date formats into YYYY-MM-DD.

        If the date string has no year (e.g. '31 May'), falls back to
        the year from email_date header, then to current year.
        """
        # Try formats with full year first
        for fmt in [
            "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
            "%d %b %Y", "%d %B %Y",
            "%b %d, %Y", "%B %d, %Y",
            "%d-%b-%Y",
        ]:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Try 2-digit year formats
        for fmt in ["%d/%m/%y", "%d-%m-%y", "%m/%d/%y"]:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Try formats without year
        year = datetime.now().year
        if email_date:
            year = email_date.year
        for fmt in ["%d %b", "%d %B", "%d/%m", "%d-%m", "%b %d", "%B %d"]:
            try:
                dt = datetime.strptime(f"{date_str.strip()} {year}", f"{fmt} %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # If all formats fail, raise rather than silently importing a wrong date
        raise ValueError(f"Cannot parse date: {date_str!r}")
