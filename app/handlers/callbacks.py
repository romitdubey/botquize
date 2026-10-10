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
        session = db.load_active_session()
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
    context.user_data.pop(PENDING_KEY, None)

    await query.edit_message_text(
        f"🚀 Publishing {session.total_questions} questions to the channel…\n\n"
        f"Quiz: {session.quiz_title}"
    )

    admin_chat_id = query.from_user.id
    asyncio.create_task(
        quiz_service.publish_quiz(query.get_bot(), session, admin_chat_id)
    )


async def _handle_test(query, context):
    pending = context.user_data.get(PENDING_KEY)
    if pending is None:
        await query.edit_message_text(
            "⚠️ No pending quiz data. Please upload a JSON file first."
        )
        return

    session = quiz_service.create_session(pending)
    # Don't clear pending — user may still want to start the full quiz

    await query.edit_message_text(
        f"🧪 Sending the first question as a test…\n\nQuiz: {session.quiz_title}\n\n"
        "After confirming, upload the JSON again and press 🚀 Start Quiz to publish all."
    )

    admin_chat_id = query.from_user.id
    asyncio.create_task(
        quiz_service.publish_quiz(query.get_bot(), session, admin_chat_id,
                                  start_index=0)
    )


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
