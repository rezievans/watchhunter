import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional
from scrapers.base import Listing

logger = logging.getLogger(__name__)

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hash        TEXT    UNIQUE NOT NULL,
    source      TEXT    NOT NULL,
    search_term TEXT,
    title       TEXT    NOT NULL,
    price       TEXT,
    url         TEXT    NOT NULL,
    found_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    notified    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_status (
    source       TEXT PRIMARY KEY,
    last_checked DATETIME,
    last_success DATETIME,
    last_error   TEXT,
    check_count  INTEGER DEFAULT 0,
    error_count  INTEGER DEFAULT 0,
    total_found  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_listings_hash     ON listings(hash);
CREATE INDEX IF NOT EXISTS idx_listings_source   ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_found_at ON listings(found_at DESC);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(_local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            _local.conn = conn
        return conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.commit()

    def insert_listing(self, listing: Listing) -> bool:
        """Insert listing. Returns True if it was new (not a duplicate)."""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO listings (hash, source, search_term, title, price, url) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (listing.hash, listing.source, listing.search_term,
                 listing.title, listing.price, listing.url)
            )
            conn.commit()
            return cur.lastrowid is not None and cur.rowcount > 0
        except Exception as e:
            logger.error("DB insert error: %s", e)
            return False

    def mark_notified(self, listing_hash: str):
        conn = self._get_conn()
        conn.execute("UPDATE listings SET notified=1 WHERE hash=?", (listing_hash,))
        conn.commit()

    def get_all_listings(self, limit: int = 500) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT source, search_term, title, price, url, found_at "
            "FROM listings ORDER BY found_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_source_status(self) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT source, last_checked, last_success, last_error, "
            "check_count, error_count, total_found FROM source_status ORDER BY source"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE date(found_at) = date('now')"
        ).fetchone()[0]
        return {"total": total, "today": today}

    def update_source_status(self, source: str, success: bool,
                              new_count: int = 0, error: Optional[str] = None):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO source_status (source, last_checked, check_count) VALUES (?, ?, 1) "
            "ON CONFLICT(source) DO UPDATE SET "
            "last_checked=excluded.last_checked, "
            "check_count=check_count+1",
            (source, now)
        )
        if success:
            conn.execute(
                "UPDATE source_status SET last_success=?, last_error=NULL, "
                "total_found=total_found+? WHERE source=?",
                (now, new_count, source)
            )
        else:
            conn.execute(
                "UPDATE source_status SET last_error=?, error_count=error_count+1 WHERE source=?",
                (error or "unknown error", source)
            )
        conn.commit()
