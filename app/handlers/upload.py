"""
handlers/upload.py – Handles JSON file uploads and pre-quiz confirmation.

Flow:
  User sends .json file
       ↓
  Validate JSON
       ↓
  Show summary + [🚀 Start Quiz] [🧪 Test First] [❌ Cancel]
       ↓
  User confirms → quiz_service.create_session + publish
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app import state as db
from app.config import MAX_JSON_SIZE_MB
from app.services import json_validator
from app.services.quiz_service import check_channel_permissions
from app.utils.helpers import admin_only

logger = logging.getLogger(__name__)

PENDING_KEY = "pending_quiz_data"   # key in context.user_data


@admin_only
async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle an uploaded document.  Only .json files are accepted."""
    doc = update.message.document

    # ── Basic file checks ──────────────────────────────────────────────────
    if not doc.file_name or not doc.file_name.lower().endswith(".json"):
        await update.message.reply_text(
            "⚠️ Please send a valid .json file."
        )
        return

    size_mb = (doc.file_size or 0) / (1024 * 1024)
    if size_mb > MAX_JSON_SIZE_MB:
        await update.message.reply_text(
            f"⚠️ File too large ({size_mb:.1f} MB). "
            f"Maximum allowed: {MAX_JSON_SIZE_MB} MB."
        )
        return

    # ── Check for active quiz ─────────────────────────────────────────────
    active = db.load_active_session()
    if active and active.status.value in ("RUNNING",):
        await update.message.reply_text(
            "⚠️ A quiz is currently active.\n\n"
            "Please finish or /reset the current quiz before starting a new one."
        )
        return

    # ── Download & parse ──────────────────────────────────────────────────
    status_msg = await update.message.reply_text("⏳ Downloading and validating JSON…")

    try:
        tg_file = await doc.get_file()
        raw = await tg_file.download_as_bytearray()
    except Exception as e:
        logger.error("Failed to download file: %s", e)
        await status_msg.edit_text("❌ Failed to download the file. Please try again.")
        return

    result, data = json_validator.load_and_validate(bytes(raw))

    if not result.ok:
        error_text = result.format_errors()
        await status_msg.edit_text(error_text[:4096])
        return

    # ── Check channel perms (non-blocking, just a warning) ────────────────
    ok, perm_msg = await check_channel_permissions(update.get_bot())
    perm_note = "" if ok else f"\n\n⚠️ {perm_msg}"

    preferences = db.get_setting(f"topic:{update.effective_user.id}", {})
    for key in ("topic", "study_date"):
        if key not in data and key in preferences:
            data[key] = preferences[key]
    if "topic" in data:
        data["quiz_title"] = data["topic"]

    # ── Store pending data in user_data ───────────────────────────────────
    context.user_data[PENDING_KEY] = data

    summary = (
        f"📄 JSON received.\n\n"
        f"Quiz: {data['quiz_title']}\n"
        f"Study date: {data.get('study_date', 'today')}\n"
        f"Questions: {result.question_count}\n"
        f"{f'Description: {result.description}' if result.description else ''}\n\n"
        f"✅ JSON validation successful.\n"
        f"Ready to publish.{perm_note}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Start Quiz", callback_data="quiz:start"),
            InlineKeyboardButton("🧪 Test First Q", callback_data="quiz:test"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="quiz:cancel")],
    ])

    await status_msg.edit_text(summary, reply_markup=keyboard)
