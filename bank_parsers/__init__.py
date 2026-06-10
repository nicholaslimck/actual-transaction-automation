"""Base parser class for bank transaction alert emails."""
from abc import ABC, abstractmethod
import hashlib
import html
import re
import logging
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Abstract base for bank email parsers.

    Each bank subclass must implement:
      - bank_name: human-friendly name
      - sender_pattern: regex to match sender email
      - _parse_alert(): extract one transaction from email text, or None

    Optional class attributes for subject-based pre-filtering:
      - subject_exclude_keywords: skip emails containing any of these (case-insensitive)
      - subject_include_keywords: only process emails containing at least one of these
    """

    subject_exclude_keywords: list[str] = []
    subject_include_keywords: list[str] = []

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
    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Parse email text into a transaction dict, or None if unrecognised."""
        ...

    def parse(self, email_data: dict) -> list[dict]:
        """Template method: filter by subject, extract text, call _parse_alert.

        Returned dicts contain: date, amount (cents, negative=outflow),
        payee_name, imported_id, notes, account_last4 (4-digit str or None).
        """
        subject = email_data.get("subject", "")
        subject_lower = subject.lower()

        # Subject-based pre-filtering
        if self.subject_exclude_keywords:
            if any(kw in subject_lower for kw in self.subject_exclude_keywords):
                logger.debug("Skipping %s email (excluded keyword): %s", self.bank_name, subject)
                return []
        if self.subject_include_keywords:
            if not any(kw in subject_lower for kw in self.subject_include_keywords):
                return []

        text = self.extract_text(email_data.get("body_text", ""), email_data.get("body_html", ""))
        logger.debug("%s raw text:\n%s", self.bank_name, text[:2000])
        txn = self._parse_alert(text, email_data)
        if not txn:
            logger.warning("Could not parse %s. Subject: %s", self.bank_name, subject)
        return [txn] if txn else []

    def can_handle(self, sender: str) -> bool:
        return bool(self._compiled_sender_pattern().search(sender))

    @lru_cache(maxsize=None)
    def _compiled_sender_pattern(self) -> re.Pattern:
        return re.compile(self.sender_pattern, re.IGNORECASE)

    @staticmethod
    def extract_text(body_text: str, body_html: str) -> str:
        """Use plain text if available, fall back to stripping HTML tags."""
        if body_text.strip():
            return body_text
        # Strip HTML tags for rough text extraction
        clean = re.sub(r"<[^>]+>", " ", body_html)
        # Decode HTML entities
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    @staticmethod
    def extract_last4(text: str) -> str | None:
        """Extract 4-digit card/account ending from common bank text snippets.

        Handles: 'ending 7654', 'ending in 7654', '****7654',
        'XXXX-XXXX-XXXX-7654'.  Returns None if no match.
        """
        if not text:
            return None
        m = re.search(
            r"(?:ending(?:\s+in)?\s+|[*xX]{2,}[\s-]*)(\d{4})\b",
            text, re.IGNORECASE,
        )
        return m.group(1) if m else None

    @staticmethod
    def _clean_merchant(raw: str) -> str:
        """Collapse whitespace, take first line, strip trailing dots/dashes."""
        m = re.sub(r"\s+", " ", raw).strip()
        m = m.split("\n")[0].strip()
        m = m.strip(".- ").strip()
        return m

    @staticmethod
    def to_cents(amount_str: str) -> int:
        """Convert '12.34' or 'S$12.34' to 1234 cents (always positive).

        Callers that need an outflow must negate: ``-self.to_cents(amount_str)``.
        """
        cleaned = re.sub(r"[^\d.\-]", "", amount_str)
        try:
            return int(round(float(cleaned) * 100))
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert amount to cents: {amount_str!r}")

    @staticmethod
    def parse_date(date_str: str, email_date: datetime | None = None) -> str:
        """Try to parse various date formats into YYYY-MM-DD.

        If the date string has no year (e.g. '31 May'), falls back to the year
        from email_date header, then to current year. A Dec/Jan rollover guard
        is applied: if the inferred date lands more than 2 days in the future
        relative to email_date (or now()), the year is rolled back by one to
        handle e.g. a 31-Dec txn in an email received on 1-Jan.
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

        # Try formats without year — use email_date for year anchor
        ref = email_date if email_date else datetime.now()
        year = ref.year
        for fmt in ["%d %b", "%d %B", "%d/%m", "%d-%m", "%b %d", "%B %d"]:
            try:
                dt = datetime.strptime(f"{date_str.strip()} {year}", f"{fmt} %Y")
            except ValueError:
                continue
            # Dec/Jan rollover guard: if the inferred date is more than 2 days
            # in the future AND falls in the last 60 days of the year (Nov/Dec),
            # the txn likely belongs to the prior year — e.g. a 31-Dec txn in an
            # email received 1-Jan. The 60-day window avoids false roll-backs for
            # ordinary dates earlier in the year.
            ref_naive = ref.replace(tzinfo=None)
            if (dt - ref_naive).days > 2 and dt.month >= 11:
                try:
                    dt = dt.replace(year=year - 1)
                except ValueError:          # e.g. Feb 29 on non-leap year
                    dt = dt - timedelta(days=365)
            return dt.strftime("%Y-%m-%d")

        # If all formats fail, raise rather than silently importing a wrong date
        raise ValueError(f"Cannot parse date: {date_str!r}")
