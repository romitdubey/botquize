> **Study tracking update:** SQLite persistence, topic/date labels, explicit Notion
> sync, daily wrong-question JSON and Monday retries are implemented.
> Start with [TRACKING_SETUP.md](TRACKING_SETUP.md) for the new commands and hosting
> requirements. A durable database volume is required for reliable deployed storage.
> Older channel/free-hosting instructions below should be read with these updates.

# 📚 Personal Telegram MCQ Quiz Bot

A **personal, single-user** Telegram bot that posts quiz questions from your study books to a Telegram channel as native Quiz Polls, tracks your answers, and gives you detailed statistics — all for free on Render with SQLite.

---

## ✨ Features

- 📤 **JSON Upload** — Send a `.json` file containing MCQs; the bot validates and queues them
- 🔍 **JSON Validation** — Detailed error messages if your JSON has problems
- 📢 **Channel Quiz Polls** — Posts native Telegram Quiz Polls to your channel
- ✅ **Answer Tracking** — Tracks correct/wrong/unattempted automatically
- 📊 **Live Statistics** — `/result`, `/status` anytime during the quiz
- 📝 **Review Wrong Answers** — `/review` shows every question you got wrong with explanation
- 📚 **Quiz History** — `/history` lists all past quizzes with scores
- 📈 **Overall Stats** — `/stats` aggregates all-time performance
- 🔁 **Reset & Restart** — `/reset` to discard and start fresh
- 💾 **SQLite Persistence** — Data survives bot restarts
- 🔐 **Single-user Security** — Only your Telegram ID can operate the bot
- 🚀 **Render-Ready** — Webhook mode, health endpoint, `render.yaml` included

---

## 🏗️ Architecture

```
User (Telegram) ──────────► Bot (private chat)
                                    │
                     ┌──────────────┤
                     │              │
               Upload JSON      Commands
                     │         (/result, /review…)
                     ▼
             [JSON Validator]
                     │
              [Quiz Service]
                     │
         ┌───────────┴─────────────┐
         │                         │
    SQLite DB               Telegram Channel
    (sessions,               (Quiz Polls)
     questions,                   │
     answers,                     │
     history)              User answers poll
                                  │
                       [poll_answer update]
                                  │
                        [Record + check completion]
                                  │
                    Send result to bot private chat
```

**Stack:**
- Python 3.11+
- `python-telegram-bot` v21 (webhook mode)
- `FastAPI` + `uvicorn` (HTTP server)
- `SQLite` (via Python stdlib)
- `python-dotenv` (env vars)

---

## 📁 Project Structure

```
telegram-mcq-bot/
│
├── app/
│   ├── __init__.py
│   ├── bot.py              # Main entry point: FastAPI + PTB application
│   ├── config.py           # Environment variable loading
│   ├── database.py         # SQLite persistence layer
│   ├── models.py           # Dataclass models
│   │
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py        # /start, /help
│   │   ├── commands.py     # /status /result /reset /review /history /stats
│   │   ├── upload.py       # JSON file upload handler
│   │   ├── quiz.py         # poll_answer handler
│   │   └── callbacks.py    # Inline keyboard callbacks
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── json_validator.py  # JSON validation logic
│   │   ├── quiz_service.py    # Quiz session & publishing logic
│   │   └── statistics.py      # Statistics formatting
│   │
│   └── utils/
│       ├── __init__.py
│       └── helpers.py      # Admin-only decorator
│
├── data/                   # SQLite database (gitignored, created at runtime)
│   └── .gitkeep
│
├── examples/
│   └── sample_quiz.json    # Sample biology MCQ file
│
├── tests/
│   ├── __init__.py
│   ├── test_json_validator.py
│   └── test_statistics.py
│
├── AI_PROMPT.md            # Ready-to-use AI prompt for image → JSON
├── README.md               # This file
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
├── render.yaml
└── Procfile
```

---

## 🖥️ Local Installation

### Prerequisites
- Python 3.11 or newer
- A Telegram bot token (see below)
- Your Telegram user ID
- A Telegram channel

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/telegram-mcq-quiz-bot.git
cd telegram-mcq-quiz-bot

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env file
cp .env.example .env
# Edit .env and fill in your values

# 5. Run the bot
uvicorn app.bot:fastapi_app --host 0.0.0.0 --port 8080
```

> **Note for local development:** Without a public `WEBHOOK_URL`, Telegram cannot deliver updates to your local machine. For local testing use [ngrok](https://ngrok.com) or [localtunnel](https://theboroer.github.io/localtunnel-www/) to expose port 8080, then set `WEBHOOK_URL` to the ngrok URL.

---

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `ADMIN_USER_ID` | ✅ | Your numeric Telegram user ID |
| `CHANNEL_ID` | ✅ | Channel ID (e.g. `-1001234567890`) |
| `WEBHOOK_URL` | ✅ (production) | HTTPS URL of your deployment |
| `PORT` | ➖ | HTTP port (default: 8080; Render sets this) |
| `DATABASE_PATH` | ➖ | SQLite file path (default: `./data/quizbot.db`) |
| `QUESTION_DELAY` | ➖ | Seconds between questions (default: 2) |
| `MAX_JSON_SIZE_MB` | ➖ | Max upload size in MB (default: 10) |
| `REVIEW_PAGE_SIZE` | ➖ | Wrong questions per page (default: 3) |
| `HISTORY_PAGE_SIZE` | ➖ | History entries per page (default: 5) |

---

## 🤖 Telegram Bot Setup

### 1. Create a bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Choose a name (e.g. `My Quiz Bot`).
4. Choose a username ending in `bot` (e.g. `myquiz_bot`).
5. BotFather will reply with your **bot token** — copy it immediately.

### 2. Set bot commands (optional but recommended)

In BotFather, send `/setcommands` and paste:

```
start - Welcome message
help - Show help
status - Current quiz status
result - Current quiz result
reset - Reset current quiz
review - Review wrong answers
history - Quiz history
stats - Overall statistics
```

---

## 📢 Channel Setup

### 1. Create a channel

1. In Telegram: tap the pencil icon → **New Channel**.
2. Set a name and optionally make it **private**.
3. Skip adding members for now.

### 2. Add the bot as administrator

1. Open the channel.
2. Tap the channel name → **Administrators** → **Add Administrator**.
3. Search for your bot's username and add it.
4. Make sure **"Post Messages"** permission is enabled.
5. Save.

### 3. Get the Channel ID

**Method A — via @username_to_id_bot:**
1. Forward any message from your channel to `@username_to_id_bot`.
2. It will reply with the numeric channel ID (e.g., `-1001234567890`).

**Method B — via getUpdates:**
1. Temporarily add the bot and send a message to the channel.
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Look for `"chat": {"id": -100...}` in the response.

Channel IDs are always **negative numbers** starting with `-100`.

---

## 🪪 Getting Your Telegram User ID

**Method A — via @userinfobot:**
1. Open Telegram and search for `@userinfobot`.
2. Send `/start`.
3. It replies with your user ID (e.g., `123456789`).

**Method B — via @raw_data_bot or @getidsbot:**
1. Search for `@getidsbot` and send `/start`.

Your user ID is a plain positive integer (e.g., `987654321`). Set this as `ADMIN_USER_ID`.

---

## 📄 JSON Format

```json
{
  "quiz_title": "Biology Chapter 1",
  "description": "MCQs from pages 1-10",
  "questions": [
    {
      "question": "Which enzyme unwinds DNA during replication?",
      "options": [
        "DNA Polymerase",
        "Helicase",
        "Ligase",
        "Primase"
      ],
      "correct_option": 1,
      "explanation": "Helicase unwinds the double helix by breaking hydrogen bonds."
    }
  ]
}
```

### Rules
- `correct_option` is **0-based** (0 = first option, 1 = second, …)
- `explanation` is **optional**
- Minimum 2 options, maximum 10 options per question
- Questions and options must not be empty
- Any number of questions is supported

---

## 🤖 AI Image-to-JSON Workflow

1. Take clear photos or screenshots of 8–12 book pages.
2. Open the [`AI_PROMPT.md`](AI_PROMPT.md) file and copy the prompt inside.
3. Paste the prompt into an AI chat (GPT-4o, Gemini 1.5 Pro, Claude 3.5, etc.) **along with your images**.
4. The AI will return a JSON string.
5. Save it as `quiz.json`.
6. Send `quiz.json` to your Telegram bot.

---

## 🏃 Running Locally

```bash
# With ngrok for webhook delivery
ngrok http 8080

# In another terminal
WEBHOOK_URL=https://abc123.ngrok.io uvicorn app.bot:fastapi_app --port 8080
```

Or create a `.env` file and just run:
```bash
uvicorn app.bot:fastapi_app --port 8080
```

---

## 🚀 Deploying to Render

### Step 1 – Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/telegram-mcq-quiz-bot.git
git push -u origin main
```

### Step 2 – Create a Render Web Service

1. Go to [render.com](https://render.com) and sign up/log in.
2. Click **New → Web Service**.
3. Connect your GitHub repository.
4. Render will detect `render.yaml` automatically. If not, configure manually:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.bot:fastapi_app --host 0.0.0.0 --port $PORT`

### Step 3 – Set Environment Variables in Render Dashboard

In your Render service → **Environment** tab, add:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | Your bot token from BotFather |
| `ADMIN_USER_ID` | Your numeric Telegram user ID |
| `CHANNEL_ID` | Your channel ID (e.g. `-1001234567890`) |
| `WEBHOOK_URL` | `https://YOUR-APP-NAME.onrender.com` |
| `DATABASE_PATH` | `./data/quizbot.db` |
| `QUESTION_DELAY` | `2` |

### Step 4 – Deploy

Click **Create Web Service**. Render will build and deploy automatically.

Once deployed, your bot is live. Send `/start` in Telegram to verify.

### ⚠️ Render Free Tier Note

The free tier **spins down after 15 minutes of inactivity**. When Telegram sends the next update, it may take 30–60 seconds to wake up.

**Fix:** Use a free uptime service like [UptimeRobot](https://uptimerobot.com) to ping your `/health` endpoint every 5 minutes:
- URL: `https://YOUR-APP.onrender.com/health`
- Monitoring interval: 5 minutes

This keeps the service alive 24/7 within free tier limits.

---

## 🧪 Running Tests

```bash
pip install -r requirements.txt
pytest -v
```

Tests do **not** require a real Telegram bot token. All Telegram API calls are mocked.

---

## 🔄 How to Update the Bot

```bash
# Pull the latest changes
git pull

# If on Render, it auto-deploys on git push
git add .
git commit -m "Update description"
git push
```

Render will automatically rebuild and redeploy.

---

## 🔥 Complete Command Reference

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command list |
| `/help` | Full usage guide |
| `/status` | Current quiz progress |
| `/result` | Current score and statistics |
| `/reset` | Reset current quiz (with confirmation) |
| `/review` | Browse wrong answers with explanations |
| `/history` | Paginated list of past quizzes |
| `/stats` | All-time statistics |

**File Upload:** Send a `.json` file as a document to upload a new quiz.

---

## 🛠️ Troubleshooting

### Bot doesn't respond
- Check `BOT_TOKEN` is correct.
- Verify `ADMIN_USER_ID` matches your actual Telegram user ID.
- Check Render logs for startup errors.

### "Cannot post to channel"
- Make sure the bot is added as **Administrator** in the channel.
- The bot needs **"Post Messages"** permission.
- Verify `CHANNEL_ID` is the correct negative number.

### Poll answers not being tracked
- Make sure the channel is **not fully anonymous**. The bot uses non-anonymous polls.
- `ADMIN_USER_ID` must match the Telegram account you use to answer polls.
- Check Render logs for `poll_answer` updates being received.

### Bot goes offline / updates delayed (Render free tier)
- Set up UptimeRobot to ping `/health` every 5 minutes.

### "JSON Validation Failed"
- Check that `correct_option` is 0-based (0 = first option).
- Make sure no option is an empty string.
- Make sure `correct_option` is within range: `0` to `len(options) - 1`.

### Webhook not set
- Make sure `WEBHOOK_URL` is set in environment variables.
- The URL must use `https://` (Telegram requires HTTPS).
- Check the bot logs on startup for webhook confirmation.

---

## 🔒 Security Notes

- Only `ADMIN_USER_ID` can interact with the bot.
- Never commit `.env` to git (it's in `.gitignore`).
- Uploaded JSON is treated strictly as data — never executed.
- Bot token is never logged or exposed in responses.

---

## 📋 Common Telegram Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `CHAT_NOT_FOUND` | Wrong channel ID | Double-check `CHANNEL_ID` |
| `CHAT_WRITE_FORBIDDEN` | Bot not admin | Add bot as channel admin |
| `Flood wait` | Too many API calls | Handled automatically by the bot |
| `Unauthorized` | Wrong bot token | Verify `BOT_TOKEN` |
| `POLL_OPTION_INVALID` | Empty option or too long | Fix the JSON and re-upload |

---

*Built for personal study. Simple, reliable, and free to deploy.*
