"""
handlers/quiz.py – poll_answer handler.

Telegram sends a PollAnswer update whenever a user answers a non-anonymous poll.
We listen here, verify the user is admin, record the answer, and check completion.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import state as db
from app.config import ADMIN_USER_IDS
from app.services import quiz_service
from app.services.statistics import format_result

logger = logging.getLogger(__name__)


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming poll_answer updates."""
    poll_answer = update.poll_answer
    if poll_answer is None or poll_answer.user is None:
        return

    # Only track authorized users
    if poll_answer.user.id not in ADMIN_USER_IDS:
        return

    poll_id = poll_answer.poll_id
    option_ids = poll_answer.option_ids  # list of chosen option indices

    # Look up which session+question this poll belongs to
    lookup = db.find_session_by_poll(poll_id)
    if lookup is None:
        logger.debug("Received poll_answer for unknown poll_id %s", poll_id)
        return

    session_id, _question_index, _correct = lookup

    # Record the answer and get updated session
    session = quiz_service.record_poll_answer(session_id, poll_id, option_ids)
    if session is None:
        return

    # Check if all published questions are answered
    if quiz_service.check_completion(session):
        quiz_service.mark_completed(session)
        result_text = format_result(session)
        try:
            await context.bot.send_message(
                chat_id=poll_answer.user.id,
                text=result_text + (
                    "\n\nUse /review to see which questions you got wrong.\n"
                    "Use /history to see past quizzes."
                ),
            )
        except Exception as e:
            logger.error("Failed to send completion message: %s", e)
