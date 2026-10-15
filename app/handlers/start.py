"""
handlers/start.py – /start and /help commands.
"""

from telegram import Update
from telegram.ext import ContextTypes

from app.utils.helpers import admin_only

START_TEXT = """👋 Personal MCQ Quiz Bot

Upload a JSON file to create a quiz.

Available commands:

📋 /start   – Show this message
📊 /status  – Current quiz status
📈 /result  – Current quiz result
🔁 /reset   – Reset current quiz
📝 /review  – Review wrong answers
📚 /history – Quiz history
📉 /stats   – Overall statistics
🗓 /plan    – Planned topic for today
🏷 /topic   – Label the next upload with topic + study date
💾 /sync    – Update Notion stats explicitly
❌ /wrong   – Export wrong questions as JSON
🔁 /retryweek – Prepare last week's mistakes as a new quiz
🗄 /backup  – Download the saved quiz database
⚙ /notion_setup – Create/resume the Notion tracker
❓ /help    – Show help"""

HELP_TEXT = """TRACKING

/topic 2026-10-20 | Enzyme kinetics
Upload the quiz JSON after setting its study date/topic.
/result only displays the score. Answers are saved locally automatically.
/sync sends today's quiz updates to Notion; /sync all catches up everything.
/wrong today or /wrong lastweek exports reusable JSON.
/retryweek prepares last week's mistakes for a new Monday quiz.
/backup downloads the persistent database.

📖 HOW TO USE

1️⃣  Prepare your MCQ JSON file.
    • Use an AI to extract questions from book images.
    • See examples/sample_quiz.json for the format.

2️⃣  Send the JSON file to this bot (as a document).

3️⃣  The bot validates and shows a summary.
    • Press 🚀 Start Quiz to publish to your channel.
    • Press ❌ Cancel to discard.

4️⃣  Go to your Telegram channel and answer the Quiz Polls.

5️⃣  Use /result to see your score anytime.
    • The bot will also auto-report when all questions are answered.

6️⃣  Use /review to see which questions you got wrong.

7️⃣  Use /history to browse past quiz results.

⚙️  Other commands:
    /status  – Progress of the current quiz
    /reset   – Cancel and reset the current quiz
    /stats   – Overall statistics across all quizzes"""


@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


@admin_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)
