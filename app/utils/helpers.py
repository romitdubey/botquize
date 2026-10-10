"""
helpers.py – Small shared utilities.
"""

from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from app.config import ADMIN_USER_ID


def admin_only(func: Callable) -> Callable:
    """Decorator: reject non-admin users with a plain message."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or user.id != ADMIN_USER_ID:
            if update.message:
                await update.message.reply_text("⛔ Unauthorized user.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Unauthorized user.", show_alert=True)
            return
        return await func(update, context)
    return wrapper


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID
