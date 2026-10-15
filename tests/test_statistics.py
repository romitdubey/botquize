"""
tests/test_statistics.py – Unit tests for statistics and session calculations.
"""

import os
import tempfile
import pytest

# Point database to a temp file so we don't touch real data
os.environ.setdefault("BOT_TOKEN", "dummy")
os.environ.setdefault("ADMIN_USER_ID", "123456789")
os.environ.setdefault("CHANNEL_ID", "-100123")

import importlib


from app.models import QuizQuestion, QuizSession, SessionStatus
from app.services.statistics import format_result, format_status, format_review_page


def _make_session(answered: list[tuple[int, bool]]) -> QuizSession:
    """Build a QuizSession with some answered questions."""
    questions = []
    for i in range(5):
        q = QuizQuestion(
            question_index=i,
            question_text=f"Question {i + 1}?",
            options=["A", "B", "C", "D"],
            correct_option=0,
        )
        if i < len(answered):
            chosen, correct = answered[i]
            q.user_answer = chosen
            q.is_correct = correct
        questions.append(q)

    return QuizSession(
        session_id="test-session",
        quiz_title="Test Quiz",
        description="",
        total_questions=5,
        questions=questions,
        status=SessionStatus.RUNNING,
    )


# ─── Session properties ───────────────────────────────────────────────────────

class TestSessionProperties:
    def test_all_correct(self):
        session = _make_session([(0, True), (0, True), (0, True), (0, True), (0, True)])
        assert session.correct == 5
        assert session.wrong == 0
        assert session.unattempted == 0
        assert session.attempted == 5
        assert session.accuracy == 100.0

    def test_all_wrong(self):
        session = _make_session([(1, False), (1, False), (1, False), (1, False), (1, False)])
        assert session.correct == 0
        assert session.wrong == 5
        assert session.accuracy == 0.0

    def test_partial(self):
        session = _make_session([(0, True), (1, False), (0, True)])
        assert session.attempted == 3
        assert session.correct == 2
        assert session.wrong == 1
        assert session.unattempted == 2

    def test_accuracy_partial(self):
        # 3 correct out of 4 attempted
        session = _make_session([(0, True), (0, True), (0, True), (1, False)])
        assert session.accuracy == 75.0

    def test_accuracy_zero_attempted(self):
        session = _make_session([])
        assert session.accuracy == 0.0

    def test_accuracy_formula(self):
        # Accuracy = correct / attempted, NOT correct / total
        session = _make_session([(0, True), (0, True)])  # 2 attempted, 2 correct
        assert session.accuracy == 100.0   # not 40%

    def test_wrong_questions_list(self):
        session = _make_session([(0, True), (1, False), (0, True), (1, False)])
        wrong = session.wrong_questions
        assert len(wrong) == 2


# ─── Format functions (smoke tests) ──────────────────────────────────────────

class TestFormatFunctions:
    def test_format_result_contains_title(self):
        session = _make_session([(0, True), (1, False)])
        text = format_result(session)
        assert "Test Quiz" in text

    def test_format_result_contains_score(self):
        session = _make_session([(0, True), (1, False)])
        text = format_result(session)
        assert "1/5" in text

    def test_format_status(self):
        session = _make_session([(0, True)])
        text = format_status(session)
        assert "Test Quiz" in text

    def test_format_review_no_wrong(self):
        session = _make_session([(0, True), (0, True)])
        text, pages = format_review_page(session, 0)
        assert "No wrong answers" in text
        assert pages == 1

    def test_format_review_wrong_questions(self):
        session = _make_session([(1, False), (1, False)])
        text, pages = format_review_page(session, 0)
        assert "WRONG QUESTIONS" in text

    def test_format_review_pagination(self):
        # 6 wrong questions, page size 3 → 2 pages
        from app.config import REVIEW_PAGE_SIZE
        import app.config as cfg
        original = cfg.REVIEW_PAGE_SIZE
        cfg.REVIEW_PAGE_SIZE = 2

        import app.services.statistics as stats_mod
        # Reload to pick up patched config
        importlib.reload(stats_mod)

        session = _make_session([(1, False)] * 5)
        text, pages = stats_mod.format_review_page(session, 0)
        assert pages > 1

        cfg.REVIEW_PAGE_SIZE = original
        importlib.reload(stats_mod)


# ─── Database history/stats ───────────────────────────────────────────────────

class TestDatabaseStats:
    def test_overall_stats_empty(self):
        from app.state import get_overall_stats
        stats = get_overall_stats()
        assert stats["quizzes_completed"] == 0
        assert stats["questions_attempted"] == 0

    def test_save_history_updates_stats(self):
        from app import state as db
        from datetime import datetime

        session = _make_session([(0, True), (0, True), (1, False)])
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        db.save_session(session)
        db.save_history(session)

        stats = db.get_overall_stats()
        assert stats["quizzes_completed"] == 1
        assert stats["questions_attempted"] == 3
        assert stats["total_correct"] == 2
        assert stats["total_wrong"] == 1

    def test_history_count(self):
        from app import state as db
        from datetime import datetime

        for i in range(3):
            session = _make_session([(0, True)])
            session.session_id = f"session-{i}"
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.utcnow()
            db.save_session(session)
            db.save_history(session)

        assert db.get_history_count() == 3
