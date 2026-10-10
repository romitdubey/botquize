"""
database.py – SQLite persistence layer.

All database operations live here.  The rest of the application talks
to the database only through this module's functions.
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from app.config import DATABASE_PATH
from app.models import (
    HistoryEntry,
    QuizQuestion,
    QuizSession,
    SessionStatus,
)

logger = logging.getLogger(__name__)


# ─── Connection management ────────────────────────────────────────────────────

def get_db_path() -> str:
    os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)
    return DATABASE_PATH


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Schema ───────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                session_id       TEXT PRIMARY KEY,
                quiz_title       TEXT NOT NULL,
                description      TEXT NOT NULL DEFAULT '',
                total_questions  INTEGER NOT NULL,
                current_question INTEGER NOT NULL DEFAULT 0,
                status           TEXT NOT NULL DEFAULT 'READY',
                started_at       TEXT,
                completed_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS questions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id           TEXT NOT NULL REFERENCES quiz_sessions(session_id),
                question_index       INTEGER NOT NULL,
                question_text        TEXT NOT NULL,
                options              TEXT NOT NULL,   -- JSON array
                correct_option       INTEGER NOT NULL,
                explanation          TEXT,
                telegram_poll_id     TEXT,
                telegram_message_id  INTEGER,
                user_answer          INTEGER,         -- NULL = unattempted
                is_correct           INTEGER,         -- NULL / 0 / 1
                UNIQUE(session_id, question_index)
            );

            CREATE TABLE IF NOT EXISTS overall_stats (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                quizzes_completed  INTEGER NOT NULL DEFAULT 0,
                questions_attempted INTEGER NOT NULL DEFAULT 0,
                total_correct      INTEGER NOT NULL DEFAULT 0,
                total_wrong        INTEGER NOT NULL DEFAULT 0,
                best_accuracy      REAL NOT NULL DEFAULT 0.0
            );

            INSERT OR IGNORE INTO overall_stats (id) VALUES (1);

            CREATE TABLE IF NOT EXISTS history (
                session_id      TEXT PRIMARY KEY,
                quiz_title      TEXT NOT NULL,
                total_questions INTEGER NOT NULL,
                attempted       INTEGER NOT NULL,
                correct         INTEGER NOT NULL,
                wrong           INTEGER NOT NULL,
                accuracy        REAL NOT NULL,
                completed_at    TEXT NOT NULL
            );
        """)
    logger.info("Database initialised at %s", get_db_path())


# ─── Session CRUD ─────────────────────────────────────────────────────────────

def save_session(session: QuizSession) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO quiz_sessions
            (session_id, quiz_title, description, total_questions,
             current_question, status, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session.session_id,
            session.quiz_title,
            session.description,
            session.total_questions,
            session.current_question,
            session.status.value,
            session.started_at.isoformat() if session.started_at else None,
            session.completed_at.isoformat() if session.completed_at else None,
        ))
        for q in session.questions:
            _upsert_question(conn, session.session_id, q)


def _upsert_question(conn: sqlite3.Connection, session_id: str, q: QuizQuestion) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO questions
        (session_id, question_index, question_text, options, correct_option,
         explanation, telegram_poll_id, telegram_message_id, user_answer, is_correct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        q.question_index,
        q.question_text,
        json.dumps(q.options),
        q.correct_option,
        q.explanation,
        q.telegram_poll_id,
        q.telegram_message_id,
        q.user_answer,
        None if q.is_correct is None else int(q.is_correct),
    ))


def update_session_status(session_id: str, status: SessionStatus,
                          current_question: Optional[int] = None,
                          completed_at: Optional[datetime] = None) -> None:
    with get_conn() as conn:
        if current_question is not None and completed_at is not None:
            conn.execute("""
                UPDATE quiz_sessions
                SET status=?, current_question=?, completed_at=?
                WHERE session_id=?
            """, (status.value, current_question,
                  completed_at.isoformat(), session_id))
        elif current_question is not None:
            conn.execute("""
                UPDATE quiz_sessions
                SET status=?, current_question=?
                WHERE session_id=?
            """, (status.value, current_question, session_id))
        else:
            conn.execute("""
                UPDATE quiz_sessions SET status=? WHERE session_id=?
            """, (status.value, session_id))


def update_question_poll(session_id: str, question_index: int,
                         poll_id: str, message_id: int) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE questions
            SET telegram_poll_id=?, telegram_message_id=?
            WHERE session_id=? AND question_index=?
        """, (poll_id, message_id, session_id, question_index))


def record_answer(session_id: str, poll_id: str,
                  user_answer: int, is_correct: bool) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE questions
            SET user_answer=?, is_correct=?
            WHERE session_id=? AND telegram_poll_id=?
        """, (user_answer, int(is_correct), session_id, poll_id))


def advance_current_question(session_id: str, new_index: int) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE quiz_sessions SET current_question=? WHERE session_id=?
        """, (new_index, session_id))


def load_active_session() -> Optional[QuizSession]:
    """Load the single active (READY/RUNNING) session if one exists."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM quiz_sessions
            WHERE status IN ('READY', 'RUNNING')
            ORDER BY rowid DESC LIMIT 1
        """).fetchone()
        if row is None:
            return None
        return _row_to_session(conn, row)


def load_session(session_id: str) -> Optional[QuizSession]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM quiz_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_session(conn, row)


def _row_to_session(conn: sqlite3.Connection, row: sqlite3.Row) -> QuizSession:
    q_rows = conn.execute("""
        SELECT * FROM questions WHERE session_id=? ORDER BY question_index
    """, (row["session_id"],)).fetchall()

    questions = []
    for qr in q_rows:
        is_correct_val = qr["is_correct"]
        questions.append(QuizQuestion(
            question_index=qr["question_index"],
            question_text=qr["question_text"],
            options=json.loads(qr["options"]),
            correct_option=qr["correct_option"],
            explanation=qr["explanation"],
            telegram_poll_id=qr["telegram_poll_id"],
            telegram_message_id=qr["telegram_message_id"],
            user_answer=qr["user_answer"],
            is_correct=None if is_correct_val is None else bool(is_correct_val),
        ))

    return QuizSession(
        session_id=row["session_id"],
        quiz_title=row["quiz_title"],
        description=row["description"],
        total_questions=row["total_questions"],
        current_question=row["current_question"],
        status=SessionStatus(row["status"]),
        questions=questions,
        started_at=_parse_dt(row["started_at"]),
        completed_at=_parse_dt(row["completed_at"]),
    )


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if val is None:
        return None
    return datetime.fromisoformat(val)


# ─── History ──────────────────────────────────────────────────────────────────

def save_history(session: QuizSession) -> None:
    entry = HistoryEntry(
        session_id=session.session_id,
        quiz_title=session.quiz_title,
        total_questions=session.total_questions,
        attempted=session.attempted,
        correct=session.correct,
        wrong=session.wrong,
        accuracy=session.accuracy,
        completed_at=session.completed_at or datetime.utcnow(),
    )
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO history
            (session_id, quiz_title, total_questions, attempted, correct, wrong, accuracy, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.session_id, entry.quiz_title, entry.total_questions,
            entry.attempted, entry.correct, entry.wrong, entry.accuracy,
            entry.completed_at.isoformat(),
        ))
        # update overall stats
        conn.execute("""
            UPDATE overall_stats SET
                quizzes_completed  = quizzes_completed + 1,
                questions_attempted = questions_attempted + ?,
                total_correct      = total_correct + ?,
                total_wrong        = total_wrong + ?,
                best_accuracy      = MAX(best_accuracy, ?)
            WHERE id = 1
        """, (entry.attempted, entry.correct, entry.wrong, entry.accuracy))


def get_history(page: int = 0, page_size: int = 5) -> list[HistoryEntry]:
    offset = page * page_size
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM history ORDER BY completed_at DESC LIMIT ? OFFSET ?
        """, (page_size, offset)).fetchall()
        return [_row_to_history(r) for r in rows]


def get_history_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]


def _row_to_history(row: sqlite3.Row) -> HistoryEntry:
    return HistoryEntry(
        session_id=row["session_id"],
        quiz_title=row["quiz_title"],
        total_questions=row["total_questions"],
        attempted=row["attempted"],
        correct=row["correct"],
        wrong=row["wrong"],
        accuracy=row["accuracy"],
        completed_at=datetime.fromisoformat(row["completed_at"]),
    )


# ─── Overall stats ────────────────────────────────────────────────────────────

def get_overall_stats() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM overall_stats WHERE id=1").fetchone()
        attempted = row["questions_attempted"]
        correct   = row["total_correct"]
        overall_acc = round(correct / attempted * 100, 2) if attempted else 0.0
        return {
            "quizzes_completed": row["quizzes_completed"],
            "questions_attempted": attempted,
            "total_correct": correct,
            "total_wrong": row["total_wrong"],
            "best_accuracy": row["best_accuracy"],
            "overall_accuracy": overall_acc,
        }


# ─── Poll-ID lookup ───────────────────────────────────────────────────────────

def find_session_by_poll(poll_id: str) -> Optional[tuple[str, int, int]]:
    """Return (session_id, question_index, correct_option) for a poll_id."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT q.session_id, q.question_index, q.correct_option
            FROM questions q
            JOIN quiz_sessions s ON s.session_id = q.session_id
            WHERE q.telegram_poll_id = ?
              AND s.status IN ('RUNNING', 'COMPLETED')
        """, (poll_id,)).fetchone()
        if row is None:
            return None
        return row["session_id"], row["question_index"], row["correct_option"]
