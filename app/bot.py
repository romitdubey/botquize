"""
bot.py – Main application entry point.

Architecture:
  • FastAPI HTTP server (health endpoints, Telegram webhook receiver)
  • python-telegram-bot Application (webhook mode)

Render maps $PORT → the FastAPI server.
Telegram delivers updates via WEBHOOK_URL/webhook.
"""

import logging
import secrets
import sys

import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    filters,
    MessageHandler,
    PollAnswerHandler,
)

from app.config import (
    BOT_TOKEN,
    PORT,
    WEBHOOK_URL,
    WEBHOOK_SECRET,
    validate_config,
)
from app import state as db
from app.handlers.callbacks import callback_handler
from app.handlers.commands import (
    history_command,
    reset_command,
    result_command,
    review_command,
    stats_command,
    status_command,
)
from app.handlers.quiz import poll_answer_handler
from app.handlers.start import help_command, start_command
from app.handlers.upload import document_handler
from app.handlers.tracking import (topic_command, plan_command, wrong_command, retryweek_command,
    sync_command, notion_setup_command, backup_command)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ─── Build the PTB Application ────────────────────────────────────────────────

def build_application() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start",   start_command))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("status",  status_command))
    app.add_handler(CommandHandler("result",  result_command))
    app.add_handler(CommandHandler("reset",   reset_command))
    app.add_handler(CommandHandler("review",  review_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("stats",   stats_command))

    for name, handler in {"topic": topic_command, "plan": plan_command, "wrong": wrong_command,
                          "retryweek": retryweek_command, "sync": sync_command,
                          "notion_setup": notion_setup_command, "backup": backup_command}.items():
        app.add_handler(CommandHandler(name, handler, block=name not in {"sync", "notion_setup"}))

    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    return app


# ─── FastAPI setup ────────────────────────────────────────────────────────────

fastapi_app = FastAPI(title="Telegram MCQ Quiz Bot")
ptb_app: Application | None = None


@fastapi_app.get("/")
async def root():
    return Response(content="Telegram MCQ Bot is running.", media_type="text/plain")


@fastapi_app.get("/health")
async def health():
    return {"status": "ok"}


@fastapi_app.post("/webhook")
async def webhook(request: Request):
    global ptb_app
    if not secrets.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), WEBHOOK_SECRET):
        return Response(status_code=403)
    if ptb_app is None:
        return Response(status_code=503)
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=200)


# ─── Startup / shutdown ───────────────────────────────────────────────────────

@fastapi_app.on_event("startup")
async def startup():
    global ptb_app
    try:
        validate_config()
    except RuntimeError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    db.init_db()
    # Published polls keep tracking after restart. For incomplete publication,
    # operators can reset and upload again without silently duplicating polls.

    ptb_app = build_application()
    await ptb_app.initialize()
    await ptb_app.start()

    if WEBHOOK_URL:
        webhook_endpoint = WEBHOOK_URL.rstrip("/") + "/webhook"
        try:
            await ptb_app.bot.set_webhook(
                url=webhook_endpoint,
                secret_token=WEBHOOK_SECRET,
                allowed_updates=["message", "callback_query", "poll_answer"],
                drop_pending_updates=False,
            )
            logger.info("Webhook set to: %s", webhook_endpoint)
        except Exception as e:
            logger.error("Failed to set webhook: %s", e)
    else:
        logger.warning(
            "WEBHOOK_URL is not set. "
            "The bot will not receive updates until a webhook URL is configured."
        )


@fastapi_app.on_event("shutdown")
async def shutdown():
    global ptb_app
    if ptb_app:
        await ptb_app.stop()
        await ptb_app.shutdown()
    logger.info("Bot shut down.")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.bot:fastapi_app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
