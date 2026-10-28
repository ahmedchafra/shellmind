from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from shellmind.core.models import SessionTurn


@dataclass(frozen=True)
class SessionSummary:
    id: str
    title: str
    created_at: str
    updated_at: str
    cwd: str
    turn_count: int


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cwd TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                user_query TEXT NOT NULL,
                commands_json TEXT NOT NULL,
                output TEXT NOT NULL,
                exit_code INTEGER NOT NULL,
                cwd TEXT,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
            """)
        self.connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_session(self, title: str, cwd: str) -> str:
        session_id = uuid.uuid4().hex[:12]
        now = self._now()
        self.connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, cwd) VALUES (?, ?, ?, ?, ?)",
            (session_id, title[:120] or "ShellMind session", now, now, cwd),
        )
        self.connection.commit()
        return session_id

    def session_exists(self, session_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row is not None

    def save_turn(self, session_id: str, turn: SessionTurn) -> None:
        now = self._now()
        self.connection.execute(
            """
            INSERT INTO turns (
                session_id, created_at, user_query, commands_json,
                output, exit_code, cwd, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                now,
                turn.user_query,
                json.dumps(turn.commands),
                turn.output,
                turn.exit_code,
                turn.cwd,
                json.dumps(turn.metadata),
            ),
        )
        self.connection.execute(
            """
            UPDATE sessions
            SET updated_at = ?, cwd = ?,
                title = CASE WHEN title = 'ShellMind session' THEN ? ELSE title END
            WHERE id = ?
            """,
            (now, turn.cwd or "", turn.user_query[:120], session_id),
        )
        self.connection.commit()

    def load_turns(self, session_id: str, limit: int = 100) -> list[SessionTurn]:
        rows = self.connection.execute(
            """
            SELECT * FROM (
                SELECT * FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
        return [self._row_to_turn(row) for row in rows]

    def latest_turn(self) -> SessionTurn | None:
        row = self.connection.execute("SELECT * FROM turns ORDER BY id DESC LIMIT 1").fetchone()
        return self._row_to_turn(row) if row else None

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        rows = self.connection.execute(
            """
            SELECT s.*, COUNT(t.id) AS turn_count
            FROM sessions s
            LEFT JOIN turns t ON t.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            SessionSummary(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                cwd=row["cwd"],
                turn_count=row["turn_count"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> SessionTurn:
        return SessionTurn(
            user_query=row["user_query"],
            commands=json.loads(row["commands_json"]),
            output=row["output"],
            exit_code=row["exit_code"],
            cwd=row["cwd"],
            metadata=json.loads(row["metadata_json"]),
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SessionStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
