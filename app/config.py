"""
config.py – Central configuration loaded from environment variables.
"""

import os
import hashlib
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Running without dotenv is fine when env vars are set externally (e.g. Render)

logger = logging.getLogger(__name__)

# ─── Required ──────────────────────────────────────────────────────────────────

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

def _parse_admin_ids(raw: str) -> set[int]:
    result = set()
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if item.isdigit():
            result.add(int(item))
    return result

ADMIN_USER_IDS: set[int] = _parse_admin_ids(os.environ.get("ADMIN_USER_ID", "0"))
ADMIN_USER_ID: int = next(iter(ADMIN_USER_IDS)) if ADMIN_USER_IDS else 0
CHANNEL_ID: str = os.environ.get("CHANNEL_ID", "")

# ─── Optional / Deployment ─────────────────────────────────────────────────────

WEBHOOK_URL: str = os.environ.get("WEBHOOK_URL", "")
PORT: int = int(os.environ.get("PORT", "8080"))
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "./data/quizbot.db")

# ─── Quiz Settings ─────────────────────────────────────────────────────────────

QUESTION_DELAY: float = float(os.environ.get("QUESTION_DELAY", "2"))
MAX_JSON_SIZE_MB: float = float(os.environ.get("MAX_JSON_SIZE_MB", "10"))
REVIEW_PAGE_SIZE: int = int(os.environ.get("REVIEW_PAGE_SIZE", "3"))
HISTORY_PAGE_SIZE: int = int(os.environ.get("HISTORY_PAGE_SIZE", "5"))

# ─── Validation ────────────────────────────────────────────────────────────────

def validate_config() -> None:
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is not set")
    if ADMIN_USER_ID == 0:
        errors.append("ADMIN_USER_ID is not set or is 0")
    if not CHANNEL_ID:
        errors.append("CHANNEL_ID is not set")
    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        raise RuntimeError(
            "Missing required environment variables:\n" + "\n".join(f"  - {e}" for e in errors)
        )

# Optional single learner; when absent each session binds to its first answerer.
LEARNER_USER_ID: int = int(os.environ.get("LEARNER_USER_ID", "0"))
STUDY_TIMEZONE: str = os.environ.get("STUDY_TIMEZONE", "Asia/Kolkata")
NOTION_TOKEN: str = os.environ.get("NOTION_TOKEN", "")
NOTION_PARENT_PAGE_ID: str = os.environ.get("NOTION_PARENT_PAGE_ID", "")
NOTION_API_VERSION: str = "2025-09-03"

# Telegram authenticates webhook deliveries with this token-derived secret by default.
WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "") or hashlib.sha256(
    ("quizbot-webhook:" + BOT_TOKEN).encode()
).hexdigest()
