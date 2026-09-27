"""SQLite persistence for credentials, classifications, and job state."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.crypto import decrypt_json, encrypt_json


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Database:
    """Small thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self.lock:
            self.connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;
                PRAGMA busy_timeout = 5000;

                CREATE TABLE IF NOT EXISTS users (
                  email TEXT PRIMARY KEY,
                  encrypted_tokens TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS classifications (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
                  gmail_message_id TEXT NOT NULL,
                  thread_id TEXT NOT NULL,
                  received_at TEXT NOT NULL,
                  from_address TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  snippet TEXT NOT NULL,
                  suggested_category TEXT,
                  applied_category TEXT,
                  confidence REAL,
                  probabilities_json TEXT,
                  action_probability REAL,
                  urgency_score REAL,
                  model TEXT,
                  status TEXT NOT NULL CHECK(status IN ('labeled', 'review', 'approved', 'error')),
                  error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(user_email, gmail_message_id)
                );

                CREATE INDEX IF NOT EXISTS idx_classifications_user_updated
                  ON classifications(user_email, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_classifications_user_status
                  ON classifications(user_email, status);

                CREATE TABLE IF NOT EXISTS job_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  trigger_name TEXT NOT NULL,
                  status TEXT NOT NULL,
                  processed INTEGER NOT NULL DEFAULT 0,
                  labeled INTEGER NOT NULL DEFAULT 0,
                  review INTEGER NOT NULL DEFAULT 0,
                  failed INTEGER NOT NULL DEFAULT 0,
                  error TEXT,
                  started_at TEXT NOT NULL,
                  finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS job_locks (
                  name TEXT PRIMARY KEY,
                  expires_at INTEGER NOT NULL
                );
                """
            )
            existing = {
                row["name"] for row in self.connection.execute("PRAGMA table_info(classifications)")
            }
            for name in ("action_probability", "urgency_score"):
                if name not in existing:
                    self.connection.execute(f"ALTER TABLE classifications ADD COLUMN {name} REAL")
            self.connection.commit()

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.lock:
            cursor = self.connection.execute(statement, parameters)
            self.connection.commit()
            return cursor

    def one(self, statement: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(statement, parameters).fetchone()
            return dict(row) if row else None

    def all(self, statement: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self.connection.execute(statement, parameters).fetchall()]


_database: Database | None = None
_database_lock = threading.Lock()


def get_db() -> Database:
    global _database
    if _database is None:
        with _database_lock:
            if _database is None:
                _database = Database(config.database_path)
    return _database


def reset_database_for_tests(path: str = ":memory:") -> Database:
    global _database
    with _database_lock:
        if _database is not None:
            _database.connection.close()
        _database = Database(path)
        return _database


def upsert_user(email: str, tokens: dict[str, Any]) -> None:
    now = _now()
    get_db().execute(
        """
        INSERT INTO users(email, encrypted_tokens, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
          encrypted_tokens = excluded.encrypted_tokens,
          updated_at = excluded.updated_at
        """,
        (email.lower(), encrypt_json(tokens), now, now),
    )


def get_user_tokens(email: str) -> dict[str, Any] | None:
    row = get_db().one("SELECT encrypted_tokens FROM users WHERE email = ?", (email.lower(),))
    return decrypt_json(row["encrypted_tokens"]) if row else None


def delete_user(email: str) -> None:
    get_db().execute("DELETE FROM users WHERE email = ?", (email.lower(),))


def save_classification(record: dict[str, Any]) -> None:
    now = _now()
    get_db().execute(
        """
        INSERT INTO classifications (
          user_email, gmail_message_id, thread_id, received_at, from_address,
          subject, snippet, suggested_category, applied_category, confidence,
          probabilities_json, action_probability, urgency_score, model, status,
          error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_email, gmail_message_id) DO UPDATE SET
          suggested_category = excluded.suggested_category,
          applied_category = excluded.applied_category,
          confidence = excluded.confidence,
          probabilities_json = excluded.probabilities_json,
          action_probability = excluded.action_probability,
          urgency_score = excluded.urgency_score,
          model = excluded.model,
          status = excluded.status,
          error = excluded.error,
          updated_at = excluded.updated_at
        """,
        (
            record["user_email"],
            record["gmail_message_id"],
            record["thread_id"],
            record["received_at"],
            record["from_address"],
            record["subject"],
            record["snippet"],
            record.get("suggested_category"),
            record.get("applied_category"),
            record.get("confidence"),
            record.get("probabilities_json"),
            record.get("action_probability"),
            record.get("urgency_score"),
            record.get("model"),
            record["status"],
            record.get("error"),
            now,
            now,
        ),
    )


def get_classification(classification_id: int, email: str) -> dict[str, Any] | None:
    return get_db().one(
        "SELECT * FROM classifications WHERE id = ? AND user_email = ?",
        (classification_id, email),
    )


def approve_classification(classification_id: int, email: str, category: str) -> None:
    get_db().execute(
        """
        UPDATE classifications
        SET applied_category = ?, status = 'approved', error = NULL, updated_at = ?
        WHERE id = ? AND user_email = ?
        """,
        (category, _now(), classification_id, email),
    )


def list_classifications(email: str, limit: int = 100) -> list[dict[str, Any]]:
    return get_db().all(
        """
        SELECT * FROM classifications
        WHERE user_email = ? ORDER BY received_at DESC LIMIT ?
        """,
        (email, limit),
    )


def get_dashboard_stats(email: str) -> dict[str, int]:
    rows = get_db().all(
        """
        SELECT status, COUNT(*) AS count FROM classifications
        WHERE user_email = ? GROUP BY status
        """,
        (email,),
    )
    stats = {"total": 0, "labeled": 0, "review": 0, "errors": 0}
    for row in rows:
        count = int(row["count"])
        stats["total"] += count
        if row["status"] == "review":
            stats["review"] += count
        elif row["status"] == "error":
            stats["errors"] += count
        else:
            stats["labeled"] += count
    return stats


def acquire_job_lock(name: str, ttl_ms: int = 15 * 60_000) -> bool:
    now = int(time.time() * 1000)
    cursor = get_db().execute(
        """
        INSERT INTO job_locks(name, expires_at) VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET expires_at = excluded.expires_at
        WHERE job_locks.expires_at < ?
        """,
        (name, now + ttl_ms, now),
    )
    return cursor.rowcount > 0


def release_job_lock(name: str) -> None:
    get_db().execute("DELETE FROM job_locks WHERE name = ?", (name,))


def start_job(trigger: str) -> int:
    cursor = get_db().execute(
        """
        INSERT INTO job_runs(trigger_name, status, started_at)
        VALUES (?, 'running', ?)
        """,
        (trigger, _now()),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return a job id")
    return cursor.lastrowid


def finish_job(job_id: int, result: dict[str, int], error: str | None = None) -> None:
    get_db().execute(
        """
        UPDATE job_runs
        SET status = ?, processed = ?, labeled = ?, review = ?, failed = ?,
            error = ?, finished_at = ?
        WHERE id = ?
        """,
        (
            "failed" if error else "completed",
            result["processed"],
            result["labeled"],
            result["review"],
            result["failed"],
            error,
            _now(),
            job_id,
        ),
    )


def get_last_job() -> dict[str, Any] | None:
    return get_db().one("SELECT * FROM job_runs ORDER BY id DESC LIMIT 1")


def probabilities_json(probabilities: dict[str, float]) -> str:
    return json.dumps(probabilities, separators=(",", ":"), sort_keys=True)
