"""Small SQLite layer for short links, click counts, and conversion logs."""

from __future__ import annotations

import secrets
import sqlite3
import string
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import config

ALPHABET = string.ascii_letters + string.digits


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    with get_connection() as conn:
        # Existing short_links table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS short_links (
                code TEXT PRIMARY KEY,
                target_url TEXT NOT NULL,
                original_url TEXT,
                asin TEXT,
                created_at TEXT NOT NULL,
                clicks INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_short_links_target_url
            ON short_links(target_url)
            """
        )

        # Existing conversions table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                original_url TEXT NOT NULL,
                target_url TEXT NOT NULL,
                output_url TEXT NOT NULL,
                short_code TEXT,
                asin TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        # --------- Add new auto_post_channels table ---------
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_post_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                added_at TEXT NOT NULL
            )
            """
        )


def _new_code(length: int = 7) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def create_or_get_short_link(target_url: str, original_url: str = "", asin: str | None = None) -> str:
    """Return an existing short code for target_url or create a new one."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT code FROM short_links WHERE target_url = ? LIMIT 1", (target_url,)
        ).fetchone()
        if row:
            return str(row["code"])

        for length in (7, 8, 9, 10):
            for _ in range(10):
                code = _new_code(length)
                try:
                    conn.execute(
                        """
                        INSERT INTO short_links(code, target_url, original_url, asin, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (code, target_url, original_url, asin, utc_now()),
                    )
                    return code
                except sqlite3.IntegrityError:
                    continue
        raise RuntimeError("Could not generate a unique short code")


def get_target_url(code: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT target_url FROM short_links WHERE code = ?", (code,)).fetchone()
        return str(row["target_url"]) if row else None


def record_click(code: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE short_links SET clicks = clicks + 1 WHERE code = ?", (code,))


def log_conversion(
    *,
    chat_id: int | None,
    user_id: int | None,
    username: str | None,
    original_url: str,
    target_url: str,
    output_url: str,
    short_code: str | None,
    asin: str | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO conversions(
                chat_id, user_id, username, original_url, target_url,
                output_url, short_code, asin, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                user_id,
                username,
                original_url,
                target_url,
                output_url,
                short_code,
                asin,
                utc_now(),
            ),
        )


def get_stats() -> dict[str, int]:
    with get_connection() as conn:
        links = conn.execute("SELECT COUNT(*) AS c FROM short_links").fetchone()["c"]
        conversions = conn.execute("SELECT COUNT(*) AS c FROM conversions").fetchone()["c"]
        clicks = conn.execute("SELECT COALESCE(SUM(clicks), 0) AS c FROM short_links").fetchone()["c"]
        return {"links": int(links), "conversions": int(conversions), "clicks": int(clicks)}
        def add_auto_post_channel(chat_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO auto_post_channels(chat_id, added_at) VALUES (?, ?)",
            (chat_id, utc_now()),
        )
