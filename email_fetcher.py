import imaplib
import email as email_lib
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class EmailFetcher:
    """Connects to Gmail via IMAP and fetches unread bank alert emails."""

    def __init__(self, config: dict):
        self.server = config["email"]["imap_server"]
        self.port = config["email"]["imap_port"]
        self.email = config["email"]["email"]
        self.password = config["email"]["app_password"]
        self.unseen_only = config["email"].get("unseen_only", True)
        self.conn = None

    def connect(self):
        """Open IMAP connection."""
        self.conn = imaplib.IMAP4_SSL(self.server, self.port)
        self.conn.login(self.email, self.password)
        self.conn.select("INBOX")
        logger.info("Connected to IMAP")

    def disconnect(self):
        if self.conn:
            try:
                self.conn.close()
                self.conn.logout()
            except Exception:
                pass
            self.conn = None

    def fetch_unread_from(self, sender: str, lookback_days: int = 7) -> list[dict]:
        """Fetch unread (or recent) emails from a specific sender.

        Returns list of dicts with keys: subject, body_text, body_html, date, message_id
        """
        if not self.conn:
            raise RuntimeError("Not connected. Call connect() first.")

        # Build search criteria
        unseen_flag = "UNSEEN " if self.unseen_only else ""
        search_criteria = f'({unseen_flag}FROM "{sender}" SINCE {self._date_days_ago(lookback_days)})'
        status, msg_ids = self.conn.search(None, search_criteria)
        if status != "OK" or not msg_ids[0]:
            return []

        messages = []
        for mid in msg_ids[0].split():
            status, data = self.conn.fetch(mid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            raw_email = data[0][1]
            msg = email_lib.message_from_bytes(raw_email)

            subject = self._decode_header(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")

            body_text = ""
            body_html = ""

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        body_text = self._decode_payload(part)
                    elif content_type == "text/html":
                        body_html = self._decode_payload(part)
            else:
                content_type = msg.get_content_type()
                if content_type == "text/plain":
                    body_text = self._decode_payload(msg)
                elif content_type == "text/html":
                    body_html = self._decode_payload(msg)

            # Parse email Date header to get the full date (for parsers that need the year)
            email_date_parsed = None
            try:
                email_date_parsed = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                pass

            messages.append({
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "date": date_str,
                "message_id": message_id,
                "email_date": email_date_parsed,
                "raw_id": mid.decode(),
            })

        return messages

    def mark_as_seen(self, raw_id: str):
        """Mark a message as read so we don't re-process it."""
        if self.conn:
            try:
                self.conn.store(raw_id, "+FLAGS", "\\Seen")
            except Exception:
                logger.warning("Failed to mark message %s as seen", raw_id, exc_info=True)

    @staticmethod
    def _decode_header(value):
        parts = decode_header(value)
        return "".join(
            part.decode(charset or "utf-8") if isinstance(part, bytes) else part
            for part, charset in parts
        )

    @staticmethod
    def _decode_payload(part):
        charset = part.get_content_charset() or "utf-8"
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                return ""
            return payload.decode(charset, errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _date_days_ago(days: int) -> str:
        d = datetime.now() - timedelta(days=days)
        return d.strftime("%d-%b-%Y")
