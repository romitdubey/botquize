"""
handlers/callbacks.py – Inline keyboard callback handler.

Handles:
  quiz:start   – Start the quiz (publish all questions)
  quiz:test    – Publish only the first question as a test
  quiz:cancel  – Discard pending quiz data
  quiz:reset_confirm – Confirmed reset
  quiz:reset_cancel  – Cancelled reset
  review:page:<n>    – Paginate /review
  history:page:<n>   – Paginate /history
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app import state as db
from app.services import quiz_service
from app.services.statistics import format_review_page, format_history_page
from app.utils.helpers import is_admin
from app.models import SessionStatus

logger = logging.getLogger(__name__)

PENDING_KEY = "pending_quiz_data"


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    user = update.effective_user
    if user is None or not is_admin(user.id):
        await query.answer("⛔ Unauthorized user.", show_alert=True)
        return

    await query.answer()  # dismiss the loading spinner

    data = query.data or ""

    # ── Quiz start/cancel ──────────────────────────────────────────────────
    if data == "quiz:start":
        await _handle_start(query, context)

    elif data == "quiz:test":
        await _handle_test(query, context)

    elif data == "quiz:cancel":
        context.user_data.pop(PENDING_KEY, None)
        await query.edit_message_text("❌ Quiz cancelled.")

    # ── Reset confirmation ────────────────────────────────────────────────
    elif data == "quiz:reset_confirm":
        await _handle_reset_confirm(query)

    elif data == "quiz:reset_cancel":
        await query.edit_message_text("Reset cancelled.")

    # ── Review pagination ─────────────────────────────────────────────────
    elif data.startswith("review:page:"):
        page = int(data.split(":")[2])
        session = db.load_active_session() or db.load_latest_session()
        if session is None:
            await query.edit_message_text("ℹ️ No active quiz.")
            return
        text, total_pages = format_review_page(session, page)
        kb = _review_keyboard(page, total_pages)
        await query.edit_message_text(text, reply_markup=kb)

    # ── History pagination ────────────────────────────────────────────────
    elif data.startswith("history:page:"):
        page = int(data.split(":")[2])
        text, total_pages = format_history_page(page)
        kb = _history_keyboard(page, total_pages)
        await query.edit_message_text(text, reply_markup=kb)

    elif data == "noop":
        return
    else:
        logger.warning("Unknown callback data: %s", data)


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _handle_start(query, context):
    pending = context.user_data.get(PENDING_KEY)
    if pending is None:
        await query.edit_message_text(
            "⚠️ No pending quiz data. Please upload a JSON file first."
        )
        return

    # Check again for active session
    active = db.load_active_session()
    if active and active.status.value == "RUNNING":
        await query.edit_message_text(
            "⚠️ A quiz is already running. Please /reset before starting a new one."
        )
        return

    session = quiz_service.create_session(pending)
    db.update_session_status(session.session_id, SessionStatus.RUNNING)
    context.user_data.pop(PENDING_KEY, None)

    await query.edit_message_text(
        f"🚀 Publishing {session.total_questions} questions to the channel…\n\n"
        f"Quiz: {session.quiz_title}"
    )

    admin_chat_id = query.from_user.id
    context.application.create_task(
        quiz_service.publish_quiz(query.get_bot(), session, admin_chat_id)
    )


async def _handle_test(query, context):
    pending = context.user_data.get(PENDING_KEY)
    if pending is None:
        await query.edit_message_text(
            "⚠️ No pending quiz data. Please upload a JSON file first."
        )
        return

    if db.load_active_session():
        await query.edit_message_text("A quiz is active. Finish or /reset it first.")
        return
    # A preview must not create a scored session or publish the entire set.
    from app.config import CHANNEL_ID, LEARNER_USER_ID
    q = pending["questions"][0]
    target = (LEARNER_USER_ID or query.from_user.id) if CHANNEL_ID in ("", "me", "private") else CHANNEL_ID
    message, error = await quiz_service._send_quiz_poll_with_retry(
        query.get_bot(), target, q["question"], q["options"], q["correct_option"], q.get("explanation"))
    if message is None:
        await query.edit_message_text(f"Preview failed: {error}")
        return
    await query.edit_message_text("First-question preview sent (not scored). Start the full quiz when ready.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Start full quiz", callback_data="quiz:start")]]))


async def _handle_reset_confirm(query):
    session = db.load_active_session()
    if session is None:
        await query.edit_message_text("ℹ️ No active quiz to reset.")
        return
    quiz_service.reset_session(session)
    await query.edit_message_text(
        f"🔁 Quiz \"{session.quiz_title}\" has been reset.\n\n"
        "Upload a new JSON file to start again."
    )


# ─── Keyboard builders ────────────────────────────────────────────────────────

def _review_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton(
            "◀ Previous", callback_data=f"review:page:{current_page - 1}"
        ))
    buttons.append(InlineKeyboardButton(
        f"{current_page + 1}/{total_pages}", callback_data="noop"
    ))
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton(
            "Next ▶", callback_data=f"review:page:{current_page + 1}"
        ))
    return InlineKeyboardMarkup([buttons])


def _history_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton(
            "◀ Previous", callback_data=f"history:page:{current_page - 1}"
        ))
    buttons.append(InlineKeyboardButton(
        f"{current_page + 1}/{total_pages}", callback_data="noop"
    ))
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton(
            "Next ▶", callback_data=f"history:page:{current_page + 1}"
        ))
    return InlineKeyboardMarkup([buttons])
