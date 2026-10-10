"""
quiz_service.py – Business logic for quiz sessions.

This module is the single source of truth for all quiz state mutations.
It talks to the database and is called by handlers.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from app import state as db
from app.config import CHANNEL_ID, QUESTION_DELAY
from app.models import QuizQuestion, QuizSession, SessionStatus

logger = logging.getLogger(__name__)


# ─── Session creation ─────────────────────────────────────────────────────────

def create_session(quiz_data: dict) -> QuizSession:
    """Build a QuizSession from parsed JSON and persist it."""
    session_id = str(uuid.uuid4())[:8]
    raw_questions = quiz_data["questions"]

    questions = [
        QuizQuestion(
            question_index=i,
            question_text=q["question"].strip(),
            options=[o.strip() for o in q["options"]],
            correct_option=int(q["correct_option"]),
            explanation=q.get("explanation", "").strip() or None,
        )
        for i, q in enumerate(raw_questions)
    ]

    session = QuizSession(
        session_id=session_id,
        quiz_title=quiz_data.get("quiz_title", "Quiz").strip(),
        description=quiz_data.get("description", "").strip(),
        total_questions=len(questions),
        questions=questions,
        status=SessionStatus.READY,
    )
    db.save_session(session)
    return session


# ─── Publishing ───────────────────────────────────────────────────────────────

async def publish_quiz(bot: Bot, session: QuizSession,
                       admin_chat_id: int, start_index: int = 0) -> None:
    """
    Publish all questions (or from start_index) to the channel.
    This is called in the background via asyncio.create_task().
    """
    # Mark as RUNNING
    session.status = SessionStatus.RUNNING
    session.started_at = datetime.utcnow()
    session.current_question = start_index
    db.update_session_status(session.session_id, SessionStatus.RUNNING,
                             current_question=start_index)

    for i in range(start_index, session.total_questions):
        q = session.questions[i]

        # Skip already-published questions (restart recovery)
        if q.telegram_poll_id is not None:
            session.current_question = i + 1
            db.advance_current_question(session.session_id, i + 1)
            continue

        caption = (
            f"📚 {session.quiz_title}\n\n"
            f"Question {i + 1}/{session.total_questions}"
        )

        poll_msg = await _send_quiz_poll_with_retry(
            bot=bot,
            chat_id=CHANNEL_ID,
            question=q.question_text,
            options=q.options,
            correct_option_id=q.correct_option,
            explanation=q.explanation,
        )

        if poll_msg is None:
            # Fatal error, abort and notify admin
            await bot.send_message(
                chat_id=admin_chat_id,
                text=(
                    f"❌ Failed to send question {i + 1}. Quiz aborted.\n"
                    "Check bot channel permissions and try /reset then start again."
                ),
            )
            db.update_session_status(session.session_id, SessionStatus.CANCELLED)
            return

        # Persist poll association
        db.update_question_poll(
            session.session_id,
            q.question_index,
            poll_msg.poll.id,
            poll_msg.message_id,
        )
        q.telegram_poll_id = poll_msg.poll.id
        q.telegram_message_id = poll_msg.message_id

        # Advance pointer
        session.current_question = i + 1
        db.advance_current_question(session.session_id, i + 1)

        # Delay between questions
        if i < session.total_questions - 1:
            await asyncio.sleep(QUESTION_DELAY)

    # All questions published — wait for answers before marking complete
    await bot.send_message(
        chat_id=admin_chat_id,
        text=(
            f"✅ All {session.total_questions} questions published to the channel!\n\n"
            "Go answer them and use /result anytime to see your score.\n"
            "I'll automatically send the final report once all are answered."
        ),
    )
    logger.info("All questions published for session %s", session.session_id)


async def _send_quiz_poll_with_retry(
    bot: Bot,
    chat_id: str,
    question: str,
    options: list[str],
    correct_option_id: int,
    explanation: Optional[str],
    max_retries: int = 3,
):
    """Send a quiz poll, handling Telegram RetryAfter gracefully."""
    for attempt in range(max_retries):
        try:
            msg = await bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=options,
                type="quiz",
                correct_option_id=correct_option_id,
                is_anonymous=False,
                explanation=explanation,
                allows_multiple_answers=False,
            )
            return msg
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning("Rate limited; waiting %s seconds (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
        except TelegramError as e:
            logger.error("Telegram error sending poll (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2)
    return None


# ─── Answer recording ─────────────────────────────────────────────────────────

def record_poll_answer(session_id: str, poll_id: str,
                       option_ids: list[int]) -> Optional[QuizSession]:
    """
    Record an answer from a poll_answer update.
    Returns the updated session.  Returns None if the session is not found.
    """
    session = db.load_session(session_id)
    if session is None:
        return None

    if not option_ids:
        return session  # Telegram can send empty list when user retracts

    chosen = option_ids[0]  # quiz polls only allow one answer

    # Find the question
    question = next(
        (q for q in session.questions if q.telegram_poll_id == poll_id), None
    )
    if question is None:
        return session

    # Avoid double-recording
    if question.user_answer is not None:
        return session

    is_correct = chosen == question.correct_option
    db.record_answer(session_id, poll_id, chosen, is_correct)
    question.user_answer = chosen
    question.is_correct = is_correct

    return session


# ─── Completion check ─────────────────────────────────────────────────────────

def check_completion(session: QuizSession) -> bool:
    """Return True if all published questions have been answered."""
    published = [q for q in session.questions if q.telegram_poll_id is not None]
    if not published:
        return False
    return all(q.user_answer is not None for q in published)


def mark_completed(session: QuizSession) -> None:
    session.status = SessionStatus.COMPLETED
    session.completed_at = datetime.utcnow()
    db.update_session_status(
        session.session_id, SessionStatus.COMPLETED,
        completed_at=session.completed_at
    )
    db.save_history(session)


# ─── Reset ────────────────────────────────────────────────────────────────────

def reset_session(session: QuizSession) -> None:
    db.update_session_status(session.session_id, SessionStatus.CANCELLED)


# ─── Channel permission check ─────────────────────────────────────────────────

async def check_channel_permissions(bot: Bot) -> tuple[bool, str]:
    """Try to verify the bot can post to the channel."""
    try:
        chat = await bot.get_chat(CHANNEL_ID)
        member = await bot.get_chat_member(CHANNEL_ID, bot.id)
        can_post = getattr(member, "can_post_messages", True)
        if not can_post:
            return False, (
                "❌ Cannot post to the channel.\n\n"
                "Please make sure:\n"
                "1. Bot is added as administrator.\n"
                "2. Bot has permission to post messages.\n"
                "3. CHANNEL_ID is correct."
            )
        return True, f"✅ Channel access confirmed: {chat.title or CHANNEL_ID}"
    except TelegramError as e:
        return False, (
            f"❌ Cannot post to the channel.\n\nError: {e}\n\n"
            "Please make sure:\n"
            "1. Bot is added as administrator.\n"
            "2. Bot has permission to post messages.\n"
            "3. CHANNEL_ID is correct."
        )
