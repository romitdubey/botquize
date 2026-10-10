"""
models.py – Plain dataclass models for the quiz bot.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class QuizQuestion:
    """One MCQ question inside a quiz."""
    question_index: int          # 0-based position within the session
    question_text: str
    options: list[str]
    correct_option: int          # 0-based
    explanation: Optional[str] = None

    # Set after publishing to Telegram
    telegram_poll_id: Optional[str] = None
    telegram_message_id: Optional[int] = None

    # Set after user answers
    user_answer: Optional[int] = None   # 0-based; None = unattempted
    is_correct: Optional[bool] = None


@dataclass
class QuizSession:
    """Represents one complete quiz run."""
    session_id: str
    quiz_title: str
    description: str
    total_questions: int
    questions: list[QuizQuestion] = field(default_factory=list)
    current_question: int = 0    # index of next question to publish
    status: SessionStatus = SessionStatus.READY
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # ── Computed helpers ──────────────────────────────────────────────────────

    @property
    def attempted(self) -> int:
        return sum(1 for q in self.questions if q.user_answer is not None)

    @property
    def correct(self) -> int:
        return sum(1 for q in self.questions if q.is_correct is True)

    @property
    def wrong(self) -> int:
        return sum(1 for q in self.questions if q.is_correct is False)

    @property
    def unattempted(self) -> int:
        return sum(1 for q in self.questions if q.user_answer is None)

    @property
    def accuracy(self) -> float:
        if self.attempted == 0:
            return 0.0
        return round(self.correct / self.attempted * 100, 2)

    @property
    def wrong_questions(self) -> list[QuizQuestion]:
        return [q for q in self.questions if q.is_correct is False]


@dataclass
class HistoryEntry:
    """A summary record stored after a quiz session finishes."""
    session_id: str
    quiz_title: str
    total_questions: int
    attempted: int
    correct: int
    wrong: int
    accuracy: float
    completed_at: datetime
