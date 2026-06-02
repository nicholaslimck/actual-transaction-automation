"""Local dedup cache for imported transactions using SQLite.

Tracks imported_id + account_id pairs so we never re-send
a transaction that Actual already absorbed.

Usage:
    cache = DedupCache()
    known = cache.check(account_id, imported_ids)  # returns set of known ids
    cache.record(account_id, imported_ids)         # mark as imported

The cache auto-prunes entries older than PRUNE_DAYS on each open().
"""

import sqlite3
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_PATH = os.path.join(DB_DIR, "dedup.db")
PRUNE_DAYS = 90  # keep last 90 days of history


class DedupCache:
    """SQLite-backed dedup cache for imported transaction IDs."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or DB_PATH
        self._conn: sqlite3.Connection | None = None

    def open(self):
        """Open DB, create table if needed, prune old entries."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS processed (
                imported_id TEXT NOT NULL,
                account_id  TEXT NOT NULL,
                processed_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (imported_id, account_id)
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_processed_at ON processed(processed_at)")
        self._prune_old()
        logger.debug("Dedup cache opened: %s", self._db_path)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _prune_old(self):
        cutoff = (datetime.now() - timedelta(days=PRUNE_DAYS)).isoformat()
        deleted = self._conn.execute(
            "DELETE FROM processed WHERE processed_at < ?", (cutoff,)
        ).rowcount
        self._conn.commit()
        if deleted:
            logger.debug("Pruned %d old dedup entries", deleted)

    def check(self, account_id: str, imported_ids: list[str]) -> set[str]:
        """Return the subset of imported_ids already known for this account."""
        if not imported_ids or not self._conn:
            return set()
        placeholders = ",".join("?" * len(imported_ids))
        rows = self._conn.execute(
            f"SELECT imported_id FROM processed WHERE account_id = ? AND imported_id IN ({placeholders})",
            [account_id, *imported_ids],
        ).fetchall()
        return {row[0] for row in rows}

    def record(self, account_id: str, imported_ids: list[str]):
        """Mark imported_ids as processed for this account."""
        if not imported_ids or not self._conn:
            return
        now = datetime.now().isoformat()
        rows = [(iid, account_id, now) for iid in imported_ids]
        self._conn.executemany(
            "INSERT OR IGNORE INTO processed (imported_id, account_id, processed_at) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()
        logger.debug("Recorded %d dedup entries for account %s", len(rows), account_id[:8])
