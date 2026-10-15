"""
quiz_service.py – Business logic for quiz sessions.

This module is the single source of truth for all quiz state mutations.
It talks to the database and is called by handlers.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from app import state as db
from app.config import CHANNEL_ID, QUESTION_DELAY, LEARNER_USER_ID
from app.services.planner import today
from app.models import QuizQuestion, QuizSession, SessionStatus

logger = logging.getLogger(__name__)


# ─── Session creation ─────────────────────────────────────────────────────────

def create_session(quiz_data: dict) -> QuizSession:
    """Build a QuizSession from parsed JSON and persist it."""
    session_id = str(uuid.uuid4())
    raw_questions = quiz_data["questions"]

    questions = [
        QuizQuestion(
            question_index=i,
            question_text=q["question"].strip(),
            options=[o.strip() for o in q["options"]],
            correct_option=int(q["correct_option"]),
            explanation=(q.get("explanation") or "").strip() or None,
            image_url=(q.get("image_url") or "").strip() or None,
            source_id=q.get("source_id", ""),
            source_topic=q.get("source_topic") or quiz_data.get("topic") or quiz_data.get("quiz_title", "Quiz"),
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
        topic=quiz_data.get("topic") or quiz_data.get("quiz_title", "Quiz"),
        study_date=quiz_data.get("study_date") or today().isoformat(),
        quiz_kind=quiz_data.get("quiz_kind", "book"),
        learner_user_id=LEARNER_USER_ID or None,
    )
    db.save_session(session)
    return session


# ─── Publishing ───────────────────────────────────────────────────────────────

async def publish_quiz(bot: Bot, session: QuizSession,
                       admin_chat_id: int, start_index: int = 0) -> None:
    """
    Publish all questions (or from start_index) to the channel.
    Run as a managed background task on the Telegram Application.
    """
    persisted = db.load_session(session.session_id)
    if persisted is None or persisted.status == SessionStatus.CANCELLED:
        return
    # Mark as RUNNING
    session.status = SessionStatus.RUNNING
    session.started_at = datetime.now(timezone.utc)
    session.current_question = start_index
    db.save_session(session)

    # Target chat: if CHANNEL_ID is 'me', 'private', or unset, post directly to admin DM
    target_chat = (session.learner_user_id or admin_chat_id) if CHANNEL_ID in ("", "me", "private", str(admin_chat_id)) else CHANNEL_ID

    for i in range(start_index, session.total_questions):
        current = db.load_session(session.session_id)
        if current is None or current.status != SessionStatus.RUNNING:
            return
        q = session.questions[i]

        # Skip already-published questions (restart recovery)
        if q.telegram_poll_id is not None:
            session.current_question = i + 1
            db.advance_current_question(session.session_id, i + 1)
            continue

        # If question has an image, send the photo first
        if q.image_url:
            try:
                await bot.send_photo(
                    chat_id=target_chat,
                    photo=q.image_url,
                    caption=f"📸 Question {i + 1} Diagram/Figure",
                )
            except Exception as e:
                logger.warning("Could not send image for Q%d: %s", i + 1, e)

        poll_msg, error_detail = await _send_quiz_poll_with_retry(
            bot=bot,
            chat_id=target_chat,
            question=q.question_text,
            options=q.options,
            correct_option_id=q.correct_option,
            explanation=q.explanation,
        )

        if poll_msg is None:
            # Fatal error, abort and notify admin with exact detail
            if error_detail and "channel chats" in error_detail.lower():
                err_explanation = (
                    "💡 Telegram channels ONLY allow anonymous polls.\n"
                    "However, to track your personal score, Telegram requires polls to be non-anonymous!\n\n"
                    "To fix this, choose either:\n"
                    "👉 1. Create a Private Telegram GROUP (not channel), add the bot, and set CHANNEL_ID to the group ID.\n"
                    "👉 2. Or set CHANNEL_ID=me in Render environment variables to have polls posted directly in this private chat!"
                )
            else:
                err_explanation = (
                    "Common fixes:\n"
                    "1. Ensure the bot is added as an ADMINISTRATOR in the chat.\n"
                    "2. Give the bot 'Post Messages' permission.\n"
                    "3. Ensure CHANNEL_ID is correct."
                )

            await bot.send_message(
                chat_id=admin_chat_id,
                text=(
                    f"❌ Failed to send question {i + 1}. Quiz aborted.\n\n"
                    f"Telegram Error: {error_detail}\n\n"
                    f"{err_explanation}\n\n"
                    "Use /reset to start over."
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

    # Answers can arrive while publishing; finish only when the whole set is posted.
    current = db.load_session(session.session_id)
    if current is None or current.status == SessionStatus.CANCELLED:
        return
    if current and check_completion(current) and mark_completed(current):
        from app.services.statistics import format_result
        await bot.send_message(chat_id=current.learner_user_id or admin_chat_id, text=format_result(current))
        return

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
) -> tuple[Optional[any], Optional[str]]:
    """Send a quiz poll, handling Telegram RetryAfter gracefully. Returns (message, error_string)."""
    last_error = None
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
            return msg, None
        except RetryAfter as e:
            last_error = f"Flood rate limited: retry after {e.retry_after}s"
            wait = e.retry_after + 1
            logger.warning("Rate limited; waiting %s seconds (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
        except TelegramError as e:
            last_error = str(e)
            logger.error("Telegram error sending poll (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return None, last_error
            await asyncio.sleep(2)
    return None, last_error


# ─── Answer recording ─────────────────────────────────────────────────────────

def record_poll_answer(session_id: str, poll_id: str,
                       option_ids: list[int], user_id: Optional[int] = None) -> Optional[QuizSession]:
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

    if not 0 <= chosen < len(question.options):
        return None
    is_correct = chosen == question.correct_option
    if not db.record_answer(session_id, poll_id, chosen, is_correct, user_id=user_id):
        return None
    return db.load_session(session_id)


# ─── Completion check ─────────────────────────────────────────────────────────

def check_completion(session: QuizSession) -> bool:
    """Return True only after the entire quiz is published and answered."""
    return (session.status == SessionStatus.RUNNING
            and session.current_question == session.total_questions
            and bool(session.questions)
            and all(q.telegram_poll_id is not None and q.user_answer is not None for q in session.questions))


def mark_completed(session: QuizSession) -> bool:
    if not db.complete_session(session.session_id):
        return False
    refreshed = db.load_session(session.session_id)
    session.status = refreshed.status
    session.completed_at = refreshed.completed_at
    return True


# ─── Reset ────────────────────────────────────────────────────────────────────

def reset_session(session: QuizSession) -> None:
    db.update_session_status(session.session_id, SessionStatus.CANCELLED)


# ─── Channel permission check ─────────────────────────────────────────────────

async def check_channel_permissions(bot: Bot) -> tuple[bool, str]:
    """Try to verify the bot can post to the target chat/channel."""
    if CHANNEL_ID in ("", "me", "private"):
        return True, "✅ Target chat: Private DM with Bot"
    try:
        chat = await bot.get_chat(CHANNEL_ID)
        if chat.type == "channel":
            return False, (
                "⚠️ Warning: Selected target is a Telegram CHANNEL.\n"
                "Telegram channels do not support non-anonymous polls needed for score tracking.\n"
                "Please use a Telegram GROUP ID or set CHANNEL_ID=me instead."
            )
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
