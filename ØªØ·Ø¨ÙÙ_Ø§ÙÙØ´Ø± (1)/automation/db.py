from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import mask_proxy

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('x','tiktok','instagram','telegram')),
    username TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 0,
    auto_publish INTEGER NOT NULL DEFAULT 0,
    review_required INTEGER NOT NULL DEFAULT 1,
    proxy_url TEXT,
    phone_replacement TEXT NOT NULL DEFAULT '',
    monitor_interval_sec INTEGER NOT NULL DEFAULT 900,
    min_delay_sec INTEGER NOT NULL DEFAULT 45,
    max_delay_sec INTEGER NOT NULL DEFAULT 180,
    settings_json TEXT NOT NULL DEFAULT '{}',
    session_status TEXT NOT NULL DEFAULT 'missing',
    last_error TEXT,
    last_monitor_at TEXT,
    last_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK(platform IN ('x','tiktok','instagram')),
    handle TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_seen_id TEXT,
    last_sync_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, platform, handle)
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    external_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    raw_text TEXT NOT NULL DEFAULT '',
    processed_text TEXT NOT NULL DEFAULT '',
    media_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',
    ai_decision TEXT,
    ai_reason TEXT,
    ai_confidence REAL,
    category TEXT,
    important INTEGER NOT NULL DEFAULT 0,
    user_comment TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at_target TEXT,
    UNIQUE(account_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_account_status ON posts(account_id, status, created_at DESC);
CREATE TABLE IF NOT EXISTS dedup (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    post_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(account_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_dedup_fingerprint ON dedup(account_id, fingerprint);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    post_id TEXT REFERENCES posts(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    category TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_account ON feedback(account_id, created_at DESC);
CREATE TABLE IF NOT EXISTS instructions (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instructions_active ON instructions(account_id, active, created_at DESC);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    dialect TEXT NOT NULL DEFAULT '',
    topics_json TEXT NOT NULL DEFAULT '[]',
    style_notes TEXT NOT NULL DEFAULT '',
    profile_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
    post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    run_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    locked_at TEXT,
    last_error TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, run_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_unique
ON jobs(kind, account_id, ifnull(post_id,'')) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _dict(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _account(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
        item = Database._dict(row)
        if item:
            item["settings"] = loads(item.pop("settings_json", "{}"), {})
            item["enabled"] = bool(item["enabled"])
            item["auto_publish"] = bool(item["auto_publish"])
            item["review_required"] = bool(item["review_required"])
        return item

    @staticmethod
    def public_account(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        source = dict(row)
        item = Database._account(source) if "settings" not in source else source
        item = item or {}
        item["proxy_masked"] = mask_proxy(item.get("proxy_url"))
        item["proxy_configured"] = bool(item.get("proxy_url"))
        item.pop("proxy_url", None)
        return item

    @staticmethod
    def _source(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
        item = Database._dict(row)
        if item:
            item["config"] = loads(item.pop("config_json", "{}"), {})
            item["enabled"] = bool(item["enabled"])
        return item

    @staticmethod
    def _post(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
        item = Database._dict(row)
        if item:
            item["media"] = loads(item.pop("media_json", "[]"), [])
            item["raw"] = loads(item.pop("raw_json", "{}"), {})
            item["important"] = bool(item.get("important"))
        return item

    def create_account(self, data: dict[str, Any]) -> dict[str, Any]:
        now, account_id = utcnow(), new_id()
        values = {
            "id": account_id, "name": data["name"].strip(), "platform": data["platform"],
            "username": data.get("username", "").strip(), "enabled": int(data.get("enabled", False)),
            "auto_publish": int(data.get("auto_publish", False)),
            "review_required": int(data.get("review_required", True)),
            "proxy_url": data.get("proxy_url") or None,
            "phone_replacement": data.get("phone_replacement", ""),
            "monitor_interval_sec": data.get("monitor_interval_sec", 900),
            "min_delay_sec": data.get("min_delay_sec", 45),
            "max_delay_sec": data.get("max_delay_sec", 180),
            "settings_json": dumps(data.get("settings", {})), "created_at": now, "updated_at": now,
        }
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO accounts(id,name,platform,username,enabled,auto_publish,review_required,
                proxy_url,phone_replacement,monitor_interval_sec,min_delay_sec,max_delay_sec,settings_json,created_at,updated_at)
                VALUES(:id,:name,:platform,:username,:enabled,:auto_publish,:review_required,:proxy_url,
                :phone_replacement,:monitor_interval_sec,:min_delay_sec,:max_delay_sec,:settings_json,:created_at,:updated_at)""",
                values,
            )
        (self.path.parent / "accounts" / account_id).mkdir(parents=True, exist_ok=True)
        return self.get_account(account_id)  # type: ignore[return-value]

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._account(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())

    def list_accounts(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM accounts" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY created_at"
        with self.connect() as conn:
            return [self._account(r) for r in conn.execute(query).fetchall()]  # type: ignore[misc]

    def update_account(self, account_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "name", "username", "enabled", "auto_publish", "review_required", "proxy_url",
            "phone_replacement", "monitor_interval_sec", "min_delay_sec", "max_delay_sec",
            "session_status", "last_error", "last_monitor_at", "last_run_at",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "settings" in data:
            updates["settings_json"] = dumps(data["settings"])
        for key in ("enabled", "auto_publish", "review_required"):
            if key in updates and updates[key] is not None:
                updates[key] = int(updates[key])
        if not updates:
            return self.get_account(account_id)
        updates["updated_at"] = utcnow()
        assignments = ",".join(f"{key}=:{key}" for key in updates)
        updates["id"] = account_id
        with self.transaction() as conn:
            conn.execute(f"UPDATE accounts SET {assignments} WHERE id=:id", updates)
        return self.get_account(account_id)

    def delete_account(self, account_id: str) -> bool:
        with self.transaction() as conn:
            return conn.execute("DELETE FROM accounts WHERE id=?", (account_id,)).rowcount > 0

    def add_source(self, account_id: str, data: dict[str, Any]) -> dict[str, Any]:
        source_id, now = new_id(), utcnow()
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO sources(id,account_id,platform,handle,url,enabled,config_json,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (source_id, account_id, data["platform"], data["handle"].strip().lstrip("@"),
                 data["url"].strip(), int(data.get("enabled", True)), dumps(data.get("config", {})), now),
            )
        return self.get_source(source_id)  # type: ignore[return-value]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._source(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())

    def list_sources(self, account_id: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
        clauses, params = [], []
        if account_id:
            clauses.append("account_id=?"); params.append(account_id)
        if enabled_only:
            clauses.append("enabled=1")
        query = "SELECT * FROM sources" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at"
        with self.connect() as conn:
            return [self._source(r) for r in conn.execute(query, params).fetchall()]  # type: ignore[misc]

    def update_source(self, source_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        updates = {k: v for k, v in data.items() if k in {"handle", "url", "enabled", "last_seen_id", "last_sync_at", "last_error"}}
        if "config" in data:
            updates["config_json"] = dumps(data["config"])
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        if not updates:
            return self.get_source(source_id)
        updates["id"] = source_id
        assignments = ",".join(f"{key}=:{key}" for key in updates)
        with self.transaction() as conn:
            conn.execute(f"UPDATE sources SET {assignments} WHERE id=:id", updates)
        return self.get_source(source_id)

    def delete_source(self, source_id: str) -> bool:
        with self.transaction() as conn:
            return conn.execute("DELETE FROM sources WHERE id=?", (source_id,)).rowcount > 0

    @staticmethod
    def fingerprint(account_id: str, external_id: str, url: str, text: str) -> str:
        basis = f"{account_id}|{external_id or url}|{text.strip()[:500]}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def insert_discovered_post(self, account_id: str, source_id: str | None, post: dict[str, Any]) -> str | None:
        now = utcnow()
        external_id = str(post["external_id"])
        fingerprint = self.fingerprint(account_id, external_id, post.get("url", ""), post.get("text", ""))
        post_id = new_id()
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT post_id FROM dedup WHERE account_id=? AND external_id=?", (account_id, external_id)
            ).fetchone()
            if existing:
                conn.execute("UPDATE dedup SET last_seen_at=? WHERE account_id=? AND external_id=?", (now, account_id, external_id))
                return None
            conn.execute(
                """INSERT INTO posts(id,account_id,source_id,external_id,fingerprint,url,author,published_at,
                raw_text,processed_text,media_json,status,raw_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,'new',?,?,?)""",
                (post_id, account_id, source_id, external_id, fingerprint, post.get("url", ""),
                 post.get("author", ""), post.get("published_at"), post.get("text", ""),
                 post.get("text", ""), dumps(post.get("media", [])), dumps(post.get("raw", {})), now, now),
            )
            conn.execute(
                "INSERT INTO dedup(account_id,external_id,fingerprint,post_id,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)",
                (account_id, external_id, fingerprint, post_id, now, now),
            )
        return post_id

    def get_post(self, post_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._post(conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())

    def list_posts(self, account_id: str | None = None, status: str | None = None,
                   limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        clauses, params = [], []
        if account_id:
            clauses.append("p.account_id=?"); params.append(account_id)
        if status:
            if "," in status:
                statuses = [s for s in status.split(",") if s]
                clauses.append(f"p.status IN ({','.join('?' * len(statuses))})"); params.extend(statuses)
            else:
                clauses.append("p.status=?"); params.append(status)
        query = """SELECT p.*,s.handle AS source_handle,a.name AS account_name,a.platform
                   FROM posts p JOIN accounts a ON a.id=p.account_id
                   LEFT JOIN sources s ON s.id=p.source_id"""
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self.connect() as conn:
            return [self._post(r) for r in conn.execute(query, params).fetchall()]  # type: ignore[misc]

    def update_post(self, post_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "status", "processed_text", "ai_decision", "ai_reason", "ai_confidence", "category",
            "important", "user_comment", "error", "published_at_target", "raw_text",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if "media" in data:
            updates["media_json"] = dumps(data["media"])
        if "raw" in data:
            updates["raw_json"] = dumps(data["raw"])
        if "important" in updates:
            updates["important"] = int(updates["important"])
        if not updates:
            return self.get_post(post_id)
        updates["updated_at"] = utcnow(); updates["id"] = post_id
        assignments = ",".join(f"{key}=:{key}" for key in updates)
        with self.transaction() as conn:
            conn.execute(f"UPDATE posts SET {assignments} WHERE id=:id", updates)
        return self.get_post(post_id)

    def add_feedback(self, account_id: str, post_id: str | None, action: str, reason: str, category: str | None = None) -> str:
        feedback_id = new_id()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO feedback(id,account_id,post_id,action,reason,category,created_at) VALUES(?,?,?,?,?,?,?)",
                (feedback_id, account_id, post_id, action, reason.strip(), category, utcnow()),
            )
        return feedback_id

    def add_instruction(self, account_id: str | None, text: str) -> str:
        instruction_id = new_id()
        with self.transaction() as conn:
            conn.execute("INSERT INTO instructions(id,account_id,text,created_at) VALUES(?,?,?,?)",
                         (instruction_id, account_id, text.strip(), utcnow()))
        return instruction_id

    def add_chat(self, account_id: str | None, role: str, text: str) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO chat_messages(id,account_id,role,text,created_at) VALUES(?,?,?,?,?)",
                         (new_id(), account_id, role, text, utcnow()))

    def list_chat(self, account_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if account_id:
            query, params = ("SELECT * FROM chat_messages WHERE account_id=? "
                             "ORDER BY created_at DESC,rowid DESC LIMIT ?"), (account_id, limit)
        else:
            query, params = "SELECT * FROM chat_messages ORDER BY created_at DESC,rowid DESC LIMIT ?", (limit,)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()][::-1]

    def learning_context(self, account_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            instructions = [r["text"] for r in conn.execute(
                """SELECT text FROM instructions WHERE active=1 AND (account_id=? OR account_id IS NULL)
                   ORDER BY created_at DESC LIMIT 30""", (account_id,)).fetchall()]
            feedback = [dict(r) for r in conn.execute(
                "SELECT action,reason,category,created_at FROM feedback WHERE account_id=? ORDER BY created_at DESC LIMIT 15",
                (account_id,)).fetchall()]
            profile = conn.execute("SELECT * FROM profiles WHERE account_id=?", (account_id,)).fetchone()
        return {"instructions": instructions, "feedback": feedback, "profile": self._dict(profile) or {}}

    def save_profile(self, account_id: str, profile: dict[str, Any]) -> None:
        now = utcnow()
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO profiles(account_id,dialect,topics_json,style_notes,profile_json,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET dialect=excluded.dialect,
                topics_json=excluded.topics_json,style_notes=excluded.style_notes,
                profile_json=excluded.profile_json,updated_at=excluded.updated_at""",
                (account_id, str(profile.get("dialect", "")), dumps(profile.get("topics", [])),
                 str(profile.get("style_notes", "")), dumps(profile), now),
            )

    def enqueue(self, kind: str, account_id: str | None = None, post_id: str | None = None,
                delay_seconds: float = 0, max_attempts: int = 3, payload: dict[str, Any] | None = None) -> str | None:
        job_id, now = new_id(), utcnow()
        run_at = (datetime.now(UTC) + timedelta(seconds=max(0, delay_seconds))).isoformat(timespec="seconds")
        try:
            with self.transaction() as conn:
                conn.execute(
                    """INSERT INTO jobs(id,account_id,post_id,kind,run_at,max_attempts,payload_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (job_id, account_id, post_id, kind, run_at, max_attempts, dumps(payload or {}), now, now),
                )
            return job_id
        except sqlite3.IntegrityError:
            return None

    def claim_job(self) -> dict[str, Any] | None:
        now = utcnow()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' AND run_at<=? ORDER BY run_at LIMIT 1", (now,)
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,locked_at=?,updated_at=? WHERE id=?",
                (now, now, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        item = dict(claimed)
        item["payload"] = loads(item.pop("payload_json", "{}"), {})
        return item

    def complete_job(self, job_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE jobs SET status='done',last_error=NULL,updated_at=? WHERE id=?", (utcnow(), job_id))

    def fail_job(self, job: dict[str, Any], error: str, retry: bool = True) -> None:
        now = utcnow()
        can_retry = retry and job["attempts"] < job["max_attempts"]
        delay = min(300, 5 * (2 ** max(0, job["attempts"] - 1)))
        run_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(timespec="seconds")
        with self.transaction() as conn:
            if can_retry:
                conn.execute("UPDATE jobs SET status='queued',run_at=?,last_error=?,locked_at=NULL,updated_at=? WHERE id=?",
                             (run_at, error[:2000], now, job["id"]))
            else:
                conn.execute("UPDATE jobs SET status='failed',last_error=?,updated_at=? WHERE id=?",
                             (error[:2000], now, job["id"]))

    def recover_stale_jobs(self, older_than_seconds: int = 1800) -> int:
        cutoff = (datetime.now(UTC) - timedelta(seconds=older_than_seconds)).isoformat(timespec="seconds")
        with self.transaction() as conn:
            cursor = conn.execute(
                """UPDATE jobs SET status='queued',locked_at=NULL,last_error='استُرجعت بعد توقف غير متوقع',updated_at=?
                   WHERE status='running' AND locked_at<?""", (utcnow(), cutoff))
            return cursor.rowcount

    def add_event(self, event: str, message: str, account_id: str | None = None,
                  level: str = "info", metadata: dict[str, Any] | None = None) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events(id,account_id,level,event,message,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (new_id(), account_id, level, event, message, dumps(metadata or {}), utcnow()),
            )

    def list_events(self, account_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = """SELECT e.*,a.name AS account_name FROM events e LEFT JOIN accounts a ON a.id=e.account_id"""
        params: list[Any] = []
        if account_id:
            query += " WHERE e.account_id=?"; params.append(account_id)
        query += " ORDER BY e.created_at DESC LIMIT ?"; params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            rows = []
            for row in conn.execute(query, params).fetchall():
                item = dict(row); item["metadata"] = loads(item.pop("metadata_json", "{}"), {}); rows.append(item)
            return rows

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key)
                   DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
                (key, dumps(value), utcnow()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return loads(row["value_json"], default) if row else default

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            accounts = conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
            enabled = conn.execute("SELECT COUNT(*) c FROM accounts WHERE enabled=1").fetchone()["c"]
            sources = conn.execute("SELECT COUNT(*) c FROM sources WHERE enabled=1").fetchone()["c"]
            published = conn.execute("SELECT COUNT(*) c FROM posts WHERE status='published'").fetchone()["c"]
            pending = conn.execute("SELECT COUNT(*) c FROM posts WHERE status='pending_review'").fetchone()["c"]
            ignored = conn.execute("SELECT COUNT(*) c FROM posts WHERE status IN ('ignored','rejected')").fetchone()["c"]
            ready = conn.execute("SELECT COUNT(*) c FROM posts WHERE status='ready'").fetchone()["c"]
            failed = conn.execute("SELECT COUNT(*) c FROM posts WHERE status IN ('failed','publish_unknown')").fetchone()["c"]
            jobs = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status IN ('queued','running')").fetchone()["c"]
        return {"accounts": accounts, "enabled_accounts": enabled, "sources": sources,
                "published": published, "pending": pending, "ignored": ignored,
                "ready": ready, "failed": failed, "active_jobs": jobs}

    def cleanup(self, days: int = 90) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        result: dict[str, int] = {}
        with self.transaction() as conn:
            for table, column in (("events", "created_at"), ("jobs", "created_at"), ("feedback", "created_at")):
                extra = " AND status IN ('done','failed')" if table == "jobs" else ""
                result[table] = conn.execute(f"DELETE FROM {table} WHERE {column}<?{extra}", (cutoff,)).rowcount
            result["chat_messages"] = conn.execute("DELETE FROM chat_messages WHERE created_at<?", (cutoff,)).rowcount
            result["posts"] = conn.execute(
                """DELETE FROM posts WHERE created_at<? AND status IN ('ignored','rejected','published','failed')
                   AND id NOT IN (SELECT post_id FROM jobs WHERE post_id IS NOT NULL)""", (cutoff,)).rowcount
            result["inactive_instructions"] = conn.execute("DELETE FROM instructions WHERE active=0 AND created_at<?", (cutoff,)).rowcount
        return result
