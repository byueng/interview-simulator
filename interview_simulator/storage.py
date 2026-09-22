from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from interview_simulator.models import Progress, Session, Turn


class SessionNotFoundError(KeyError):
    """SQLite 中不存在指定面试会话。"""


class SQLiteStorage:
    """本地练习记录的唯一持久化入口。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS interview_sessions (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL,
                    knowledge_id TEXT,
                    mode TEXT NOT NULL CHECK (mode IN ('single', 'deep')),
                    source_hash TEXT NOT NULL,
                    title TEXT NOT NULL,
                    current_question TEXT,
                    status TEXT NOT NULL CHECK (status IN ('active', 'completed')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    final_score REAL,
                    final_evaluation_json TEXT
                );
                CREATE TABLE IF NOT EXISTS interview_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES interview_sessions(id),
                    round_no INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    feedback TEXT NOT NULL,
                    next_question TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, round_no)
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_question_started
                    ON interview_sessions(question_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_turns_session_round
                    ON interview_turns(session_id, round_no ASC);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(interview_sessions)")}
            if "knowledge_id" not in columns:
                connection.execute("ALTER TABLE interview_sessions ADD COLUMN knowledge_id TEXT")
            connection.execute(
                "UPDATE interview_sessions SET knowledge_id = question_id WHERE knowledge_id IS NULL OR knowledge_id = ''"
            )

    def create_session(
        self, question_id: str, knowledge_id: str, mode: str, source_hash: str, title: str
    ) -> Session:
        if mode not in {"single", "deep"}:
            raise ValueError("mode 必须是 single 或 deep")
        session = Session(
            id=str(uuid.uuid4()),
            question_id=question_id,
            knowledge_id=knowledge_id,
            mode=mode,
            source_hash=source_hash,
            title=title,
            current_question=title,
            status="active",
            started_at=_timestamp(),
            ended_at=None,
            final_score=None,
            final_evaluation=None,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO interview_sessions
                    (id, question_id, knowledge_id, mode, source_hash, title, current_question, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.question_id,
                    session.knowledge_id,
                    session.mode,
                    session.source_hash,
                    session.title,
                    session.current_question,
                    session.status,
                    session.started_at,
                ),
            )
        return session

    def append_turn(
        self,
        session_id: str,
        round_no: int,
        question: str,
        answer: str,
        feedback: str,
        next_question: str | None,
    ) -> Turn:
        turn = Turn(round_no, question, answer, feedback, next_question, _timestamp())
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE interview_sessions SET current_question = ? WHERE id = ? AND status = 'active'",
                (next_question, session_id),
            )
            if updated.rowcount != 1:
                raise SessionNotFoundError(session_id)
            connection.execute(
                """
                INSERT INTO interview_turns
                    (session_id, round_no, question, answer, feedback, next_question, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, turn.round_no, turn.question, turn.answer, turn.feedback, turn.next_question, turn.created_at),
            )
        return turn

    def finish_session(self, session_id: str, score: float, evaluation: dict[str, Any]) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE interview_sessions
                SET status = 'completed', current_question = NULL, ended_at = ?, final_score = ?, final_evaluation_json = ?
                WHERE id = ? AND status = 'active'
                """,
                (_timestamp(), score, json.dumps(evaluation, ensure_ascii=False), session_id),
            )
            if updated.rowcount != 1:
                raise SessionNotFoundError(session_id)

    def get_session(self, session_id: str) -> Session:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise SessionNotFoundError(session_id)
            turns = connection.execute(
                "SELECT * FROM interview_turns WHERE session_id = ? ORDER BY round_no ASC", (session_id,)
            ).fetchall()
        return _session_from_row(row, tuple(_turn_from_row(turn) for turn in turns))

    def list_sessions(self, limit: int = 100) -> list[Session]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM interview_sessions ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_session_from_row(row, ()) for row in rows]

    def latest_progress(self, question_id: str) -> Progress | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT question_id, final_score, ended_at
                FROM interview_sessions
                WHERE question_id = ? AND status = 'completed'
                ORDER BY ended_at DESC, rowid DESC LIMIT 1
                """,
                (question_id,),
            ).fetchone()
        if row is None:
            return None
        return Progress(
            question_id=row["question_id"],
            practiced=True,
            latest_score=row["final_score"],
            latest_practiced_at=row["ended_at"],
        )
def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _turn_from_row(row: sqlite3.Row) -> Turn:
    return Turn(
        round_no=row["round_no"],
        question=row["question"],
        answer=row["answer"],
        feedback=row["feedback"],
        next_question=row["next_question"],
        created_at=row["created_at"],
    )


def _session_from_row(row: sqlite3.Row, turns: tuple[Turn, ...]) -> Session:
    evaluation = row["final_evaluation_json"]
    return Session(
        id=row["id"],
        question_id=row["question_id"],
        knowledge_id=row["knowledge_id"] or row["question_id"],
        mode=row["mode"],
        source_hash=row["source_hash"],
        title=row["title"],
        current_question=row["current_question"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        final_score=row["final_score"],
        final_evaluation=json.loads(evaluation) if evaluation else None,
        turns=turns,
    )
