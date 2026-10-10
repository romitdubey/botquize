"""
state.py – In-memory application state.

Replaces SQLite entirely. All data lives in Python dicts in RAM.

⚠️  Trade-off: Data is lost when Render restarts the service.
    For a personal quiz bot where each quiz is a single session,
    this is acceptable and keeps the project dependency-free.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.models import QuizQuestion, QuizSession, SessionStatus, HistoryEntry

logger = logging.getLogger(__name__)

# ─── Global state ─────────────────────────────────────────────────────────────

_sessions: dict[str, QuizSession] = {}          # session_id → QuizSession
_history:  list[HistoryEntry]     = []           # ordered newest-first
_overall = {
    "quizzes_completed":   0,
    "questions_attempted": 0,
    "total_correct":       0,
    "total_wrong":         0,
    "best_accuracy":       0.0,
}

# poll_id → (session_id, question_index, correct_option)
_poll_index: dict[str, tuple[str, int, int]] = {}


# ─── Init (no-op for in-memory) ───────────────────────────────────────────────

def init_db() -> None:
    logger.info("Using in-memory state (no database).")


# ─── Session CRUD ─────────────────────────────────────────────────────────────

def save_session(session: QuizSession) -> None:
    _sessions[session.session_id] = session


def load_session(session_id: str) -> Optional[QuizSession]:
    return _sessions.get(session_id)


def load_active_session() -> Optional[QuizSession]:
    """Return the most recent READY/RUNNING session, or None."""
    for session in reversed(list(_sessions.values())):
        if session.status in (SessionStatus.READY, SessionStatus.RUNNING):
            return session
    return None


def update_session_status(
    session_id: str,
    status: SessionStatus,
    current_question: Optional[int] = None,
    completed_at: Optional[datetime] = None,
) -> None:
    s = _sessions.get(session_id)
    if s is None:
        return
    s.status = status
    if current_question is not None:
        s.current_question = current_question
    if completed_at is not None:
        s.completed_at = completed_at


def update_question_poll(
    session_id: str, question_index: int, poll_id: str, message_id: int
) -> None:
    s = _sessions.get(session_id)
    if s is None:
        return
    q = s.questions[question_index]
    q.telegram_poll_id  = poll_id
    q.telegram_message_id = message_id
    _poll_index[poll_id] = (session_id, question_index, q.correct_option)


def record_answer(
    session_id: str, poll_id: str, user_answer: int, is_correct: bool
) -> None:
    s = _sessions.get(session_id)
    if s is None:
        return
    for q in s.questions:
        if q.telegram_poll_id == poll_id:
            q.user_answer = user_answer
            q.is_correct  = is_correct
            break


def advance_current_question(session_id: str, new_index: int) -> None:
    s = _sessions.get(session_id)
    if s:
        s.current_question = new_index


# ─── Poll-ID lookup ───────────────────────────────────────────────────────────

def find_session_by_poll(poll_id: str) -> Optional[tuple[str, int, int]]:
    """Return (session_id, question_index, correct_option) or None."""
    return _poll_index.get(poll_id)


# ─── History & overall stats ──────────────────────────────────────────────────

def save_history(session: QuizSession) -> None:
    entry = HistoryEntry(
        session_id      = session.session_id,
        quiz_title      = session.quiz_title,
        total_questions = session.total_questions,
        attempted       = session.attempted,
        correct         = session.correct,
        wrong           = session.wrong,
        accuracy        = session.accuracy,
        completed_at    = session.completed_at or datetime.utcnow(),
    )
    _history.insert(0, entry)          # newest first

    _overall["quizzes_completed"]   += 1
    _overall["questions_attempted"] += session.attempted
    _overall["total_correct"]       += session.correct
    _overall["total_wrong"]         += session.wrong
    if session.accuracy > _overall["best_accuracy"]:
        _overall["best_accuracy"]    = session.accuracy


def get_history(page: int = 0, page_size: int = 5) -> list[HistoryEntry]:
    start = page * page_size
    return _history[start: start + page_size]


def get_history_count() -> int:
    return len(_history)


def get_overall_stats() -> dict:
    att = _overall["questions_attempted"]
    cor = _overall["total_correct"]
    return {
        **_overall,
        "overall_accuracy": round(cor / att * 100, 2) if att else 0.0,
    }
