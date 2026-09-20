"""SQLite 去重：以 url 的 sha256 为唯一键，数据库随仓库提交留档。"""
import hashlib
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from . import config

log = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS posted (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT UNIQUE,
            url TEXT,
            title TEXT,
            posted_at TEXT
        )"""
    )
    return conn


def _hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()


def is_posted(url: str) -> bool:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM posted WHERE url_hash = ?", (_hash(url),)
        ).fetchone()
        return row is not None


def mark_posted(url: str, title: str):
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO posted (url_hash, url, title, posted_at) VALUES (?, ?, ?, ?)",
                (
                    _hash(url),
                    url,
                    title,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
