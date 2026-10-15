"""
handlers/commands.py – All administrative bot commands.

/status  /result  /reset  /review  /history  /stats
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app import state as db
from app.services.statistics import (
    format_history_page,
    format_overall_stats,
    format_result,
    format_review_page,
    format_status,
)
from app.utils.helpers import admin_only

logger = logging.getLogger(__name__)


# ─── /status ─────────────────────────────────────────────────────────────────

@admin_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = db.load_active_session() or db.load_latest_session()
    if session is None:
        await update.message.reply_text("ℹ️ No active quiz.")
        return
    await update.message.reply_text(format_status(session))


# ─── /result ─────────────────────────────────────────────────────────────────

@admin_only
async def result_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = db.load_active_session() or db.load_latest_session()
    if session is None:
        await update.message.reply_text(
            "ℹ️ No active quiz. Use /history to see past results."
        )
        return
    await update.message.reply_text(format_result(session))


# ─── /reset ──────────────────────────────────────────────────────────────────

@admin_only
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = db.load_active_session()
    if session is None:
        await update.message.reply_text("ℹ️ No active quiz to reset.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Reset", callback_data="quiz:reset_confirm"),
            InlineKeyboardButton("❌ Cancel",     callback_data="quiz:reset_cancel"),
        ]
    ])
    await update.message.reply_text(
        f"⚠️ Are you sure you want to reset the current quiz?\n\n"
        f"Quiz: {session.quiz_title}\n"
        f"Progress: {session.current_question}/{session.total_questions}",
        reply_markup=keyboard,
    )


# ─── /review ─────────────────────────────────────────────────────────────────

@admin_only
async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = db.load_active_session() or db.load_latest_session()
    if session is None:
        await update.message.reply_text(
            "ℹ️ No active quiz. Use /history for past quizzes."
        )
        return

    text, total_pages = format_review_page(session, page=0)
    kb = _review_keyboard(0, total_pages)
    await update.message.reply_text(text, reply_markup=kb)


# ─── /history ────────────────────────────────────────────────────────────────

@admin_only
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, total_pages = format_history_page(page=0)
    kb = _history_keyboard(0, total_pages)
    await update.message.reply_text(text, reply_markup=kb)


# ─── /stats ──────────────────────────────────────────────────────────────────

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(format_overall_stats())


# ─── Keyboard helpers ─────────────────────────────────────────────────────────

def _review_keyboard(current_page: int, total_pages: int):
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


def _history_keyboard(current_page: int, total_pages: int):
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
