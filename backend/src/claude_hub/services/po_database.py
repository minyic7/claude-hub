"""SQLite persistence for PO Agent — one database per project.

Stores conversation history, cycle logs, and key-value state.
Redis owns ticket data; PO owns its own cognition here.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from claude_hub.config import settings

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS conversation (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    cycle_n   INTEGER
);

CREATE TABLE IF NOT EXISTS cycle_log (
    cycle_n         INTEGER PRIMARY KEY,
    triggered_by    TEXT,
    observe_summary TEXT,
    think_reasoning TEXT,
    actions_taken   TEXT,
    timestamp       TEXT
);

CREATE TABLE IF NOT EXISTS po_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

MAX_CONVERSATION_ROWS = 50
MAX_CYCLE_LOG_ROWS = 10


class PODatabase:
    """SQLite wrapper for a single PO agent's persistent state."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        db_dir = os.path.join(settings.data_dir, "po")
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, f"{project_id}.db")
        self._conn: sqlite3.Connection | None = None
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript(_CREATE_TABLES)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ─── Conversation ────────────────────────────────────────────────────

    def append_message(
        self, role: str, content: str, cycle_n: int | None = None
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO conversation (role, content, timestamp, cycle_n) VALUES (?, ?, ?, ?)",
            (role, content, datetime.now(timezone.utc).isoformat(), cycle_n),
        )
        # Enforce sliding window
        conn.execute(
            "DELETE FROM conversation WHERE id NOT IN "
            "(SELECT id FROM conversation ORDER BY id DESC LIMIT ?)",
            (MAX_CONVERSATION_ROWS,),
        )
        conn.commit()

    def load_conversation(self, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT role, content, timestamp, cycle_n FROM conversation "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"role": r["role"], "content": r["content"],
             "timestamp": r["timestamp"], "cycle_n": r["cycle_n"]}
            for r in reversed(rows)
        ]

    # ─── Cycle Log ───────────────────────────────────────────────────────

    def record_cycle(
        self,
        cycle_n: int,
        triggered_by: str,
        observe_summary: str,
        think_reasoning: str,
        actions_taken: list[dict],
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO cycle_log "
            "(cycle_n, triggered_by, observe_summary, think_reasoning, actions_taken, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                cycle_n,
                triggered_by,
                observe_summary,
                think_reasoning,
                json.dumps(actions_taken),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        # Keep only recent cycles
        conn.execute(
            "DELETE FROM cycle_log WHERE cycle_n NOT IN "
            "(SELECT cycle_n FROM cycle_log ORDER BY cycle_n DESC LIMIT ?)",
            (MAX_CYCLE_LOG_ROWS,),
        )
        conn.commit()

    def get_recent_cycles(self, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM cycle_log ORDER BY cycle_n DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for r in reversed(rows):
            d = dict(r)
            try:
                d["actions_taken"] = json.loads(d["actions_taken"])
            except (json.JSONDecodeError, TypeError):
                d["actions_taken"] = []
            result.append(d)
        return result

    # ─── Key-Value State ─────────────────────────────────────────────────

    def get_state(self, key: str | None = None) -> dict | str | None:
        conn = self._get_conn()
        if key is not None:
            row = conn.execute(
                "SELECT value FROM po_state WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        # Return all state as dict
        rows = conn.execute("SELECT key, value FROM po_state").fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result

    def set_state(self, key: str, value: object) -> None:
        conn = self._get_conn()
        serialized = json.dumps(value) if not isinstance(value, str) else value
        conn.execute(
            "INSERT OR REPLACE INTO po_state (key, value) VALUES (?, ?)",
            (key, serialized),
        )
        conn.commit()
