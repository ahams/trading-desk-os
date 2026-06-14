from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Union

from config.settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Optional[Union[str, Path]] = None):
    path = Path(db_path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "tdo") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def init_db(db_path: Optional[Union[str, Path]] = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                monthly_credit_limit INTEGER NOT NULL DEFAULT 100,
                is_active INTEGER NOT NULL DEFAULT 1,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                key_prefix TEXT NOT NULL,
                label TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                endpoint TEXT NOT NULL,
                credits_used INTEGER NOT NULL,
                request_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_requests (
                request_id TEXT PRIMARY KEY,
                user_id INTEGER,
                endpoint TEXT NOT NULL,
                status_code INTEGER,
                latency_ms REAL,
                error TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                decision TEXT,
                setup_type TEXT,
                final_score REAL,
                expected_return REAL,
                entry REAL,
                stop REAL,
                target1 REAL,
                target2 REAL,
                risk_reward REAL,
                position_size REAL,
                regime TEXT,
                theme TEXT,
                thesis TEXT,
                payload_json TEXT
            );

            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                report_date TEXT NOT NULL,
                title TEXT,
                html_path TEXT,
                markdown_path TEXT,
                csv_path TEXT,
                payload_json TEXT
            );

            CREATE TABLE IF NOT EXISTS billing_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            """
        )


def create_user(email: str, name: str = "", plan: str = "free", monthly_credit_limit: Optional[int] = None) -> Dict[str, Any]:
    init_db()
    now = utc_now()
    if monthly_credit_limit is None:
        monthly_credit_limit = settings.default_free_monthly_credits if plan == "free" else settings.default_paid_monthly_credits
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO users(email, name, plan, monthly_credit_limit, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name,
                plan=excluded.plan,
                monthly_credit_limit=excluded.monthly_credit_limit,
                updated_at=excluded.updated_at
            """,
            (email, name, plan, int(monthly_credit_limit), now, now),
        )
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row)


def create_api_key_for_user(email: str, label: str = "default") -> Dict[str, Any]:
    init_db()
    user = create_user(email=email) if not get_user_by_email(email) else get_user_by_email(email)
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO api_keys(user_id, key_hash, key_prefix, label, created_at) VALUES(?,?,?,?,?)",
            (user["id"], key_hash, raw_key[:12], label, now),
        )
    return {"api_key": raw_key, "user": user, "label": label}


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    init_db()
    key_hash = hash_api_key(api_key)
    now = utc_now()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT u.*, k.id AS api_key_id
            FROM api_keys k
            JOIN users u ON u.id = k.user_id
            WHERE k.key_hash=? AND k.is_active=1 AND u.is_active=1
            """,
            (key_hash,),
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now, row["api_key_id"]))
        return dict(row)


def usage_this_month(user_id: int) -> int:
    init_db()
    month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(credits_used),0) AS credits FROM api_usage WHERE user_id=? AND substr(created_at,1,7)=?",
            (user_id, month_prefix),
        ).fetchone()
        return int(row["credits"] or 0)


def record_usage(user_id: int, endpoint: str, credits: int, request_id: Optional[str] = None) -> int:
    init_db()
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO api_usage(user_id, endpoint, credits_used, request_id, created_at) VALUES(?,?,?,?,?)",
            (user_id, endpoint, int(credits), request_id, now),
        )
    return usage_this_month(user_id)


def record_request(request_id: str, endpoint: str, user_id: Optional[int], status_code: int, latency_ms: float, error: Optional[str] = None) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO api_requests(request_id, user_id, endpoint, status_code, latency_ms, error, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (request_id, user_id, endpoint, status_code, latency_ms, error, utc_now()),
        )


def list_usage(user_id: int, limit: int = 200) -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM api_usage WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
