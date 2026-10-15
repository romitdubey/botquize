# Study Grove — mobile website + Telegram admin

Everything is in this repository. The website replaces the Notion tracker and Telegram quiz polls. Supabase stores the questions, full explanations, attempts, study time and wrong-answer history. Vercel serves the frontend and Python API together.

## 1. Connect Supabase

1. In your existing Supabase project, open **SQL Editor**, paste `supabase/schema.sql`, and run it. This creates three private tables and a private diagram bucket.
2. Under **Authentication → Users**, create your friend's email/password account. Use the dashboard's create-user option with email confirmed. The website has sign-in only; no public sign-up screen.
3. Copy the variables from `.env.web.example` into your local `.env`. Preserve your existing `BOT_TOKEN` and `ADMIN_USER_ID`.
4. Get the project URL, public anon/publishable key, and server secret/service-role key from the Supabase project API settings. The server key must stay in `.env`/Vercel settings. It is never included in website JavaScript.
5. Set `STUDY_ALLOWED_EMAILS` to your friend's exact login email. You can allow multiple emails separated by commas; each account has independent study records. For your own read-only mentor login, create a second Auth user, include both emails in `STUDY_ALLOWED_EMAILS`, set `STUDY_MENTOR_EMAIL` to your email and `STUDY_LEARNER_ID` to her Auth user UUID. You will see her timer, schedule and results while her login can study/take tests.

The schema deliberately grants no direct anonymous/authenticated browser access to question keys or study tables. The API verifies the Supabase login and email allowlist before every request.

## 2. Run locally

```bash
.venv/bin/python -m pip install -r requirements.txt
npm run build
npm run dev
```

Open `http://localhost:8080`. No Node dependencies are required. Node only copies the static frontend for Vercel.

`http://localhost:8080/?demo=1` is an **explicit sample-data preview**, including a short test. It never writes to Supabase. Production sign-in has no demo fallback.

## 3. Deploy to Vercel

Import this repository in Vercel. Set the **root directory to this folder** and framework preset to **Other**. The committed `vercel.json` builds `web/` into `dist/` and packages `api/index.py` as the same-origin Python API. Do not select the old Render entry point.

Add **all variables from `.env.web.example`** in Vercel Settings → Environment Variables. Use the same existing Telegram token/admin ID. `APP_URL` must be your final HTTPS Vercel address. Deploy/redeploy after setting variables.

Visit `/api/health` (should show `{"status":"ok"}`), then sign in and open Schedule. The readiness health route does not validate Supabase credentials; successful sign-in + loading the dashboard is the real database check.

Once the deployed website works, update local `APP_URL` to that address and run:

```bash
.venv/bin/python scripts/setup_webhook.py
```

This intentionally switches the existing bot from its old webhook to the new website backend and replaces the Telegram command menu. It checks the new API first. No webhook changes happen merely from starting the website locally. Keep this webhook on the production domain when making Vercel preview deployments.

## 4. Your daily Telegram workflow

Send these in your **private admin bot chat**:

```text
/topic 2026-10-16 | Enzymes and Coenzymes
```

Upload the same JSON file as before:

```json
{
  "quiz_title": "Enzymes and Coenzymes",
  "duration_minutes": 45,
  "questions": [
    {
      "question": "Which statement is correct?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_option": 1,
      "explanation": "Full explanation, without Telegram's old length limit.",
      "image_url": ""
    }
  ]
}
```

`correct_option` is **zero based**: 0=A, 1=B, 2=C, 3=D. `duration_minutes` is optional (default 90 seconds/question, minimum 10 minutes). Upload limits: 1–1,000 questions and 10 MB JSON, with bounded field lengths. Long questions/options/explanations remain intact.

The date labels the **study day**, not the date of upload. It is not an automatic release time. When she has studied the topic, use `/open` the following day. Until then the bank remains a private draft. No question is posted to a Telegram group/channel.

- `/image 12` → send the diagram/photo → it attaches to the **12th item in the uploaded array**. For best quality send as an image document. PNG/JPEG/WebP supported, max 10 MB. `/open` after adding diagrams.
- A standalone diagram question: `/question {"question":"...","options":["A","B"],"correct_option":0,"explanation":"..."}` → send its image → `/open`. This creates a **separate one-question draft**, not an append to an already open test. Select `/topic` first.
- `/tests` lists IDs. `/select ID` selects an older upload before `/image`, `/open` or `/close`.
- `/close` prevents new attempts. An already started attempt can finish using its immutable question snapshot.
- Identical reuploads for the same topic/study date do not duplicate or close the existing bank. If content is revised, it becomes a new draft. Existing attempts preserve the original question/explanation snapshot.
- `/status`, `/plan`, `/help` explain current selection and today's topic.

## 5. Her mobile workflow

Open the Vercel link, sign in, optionally **Add to Home Screen** from the phone browser.

- **My day**: Start studying, choose the topic, pause when finished; mark today's study complete.
- **Schedule**: all dates 16 October–10 December, with Saturday PYQ/Sunday mock and the original weekday topics. No book pages or implementation details in the study screens.
- **Practice**: open tests, a live exam clock, question palette, review flags, autosaved answers, save-and-exit, and final submission.
- **Results**: scores and every question's correct answer/explanation after submission. Score is 1 per correct answer and 0 otherwise. This is practice scoring, not the official variable CSIR section/negative-marking scheme.
- **Mistakes**: all historically wrong submitted answers, with explanations and retry. Correct retries do not erase original mistakes or results.

The Monday retry is built automatically when the dashboard is first loaded for that week, using the previous **Monday through Friday in India time**, deduplicated by question. Saturday/Sunday test mistakes remain in the all-mistakes bank but are excluded from this weekday retry. Each Monday snapshot is created once; no Vercel paid cron is needed. No mistakes means no empty quiz.

## Timer behaviour

Time saves to Supabase every 30 seconds and when paused, with time per topic recorded as well. Schedule → Study starts a focus session for that topic; the logged calendar day is always the actual day in India. It resumes from saved totals on another signed-in device. Hiding the tab/app pauses the study timer; reopening does not silently restart it. If a browser is killed/offline before a pause reaches the server, time is capped at the last successful heartbeat plus 90 seconds, and reconciled on the next visit. This avoids counting an abandoned timer all night. India-midnight sessions split into the correct daily totals. Marking 'studied' is separate from logged time.

Exam clocks continue when leaving a test. Only answers saved before its server deadline count; expired tests finalize on the next dashboard/attempt request. Submissions are idempotent. Answers and flags autosave; a failed save is visible and must be retried. Explanation keys never appear in active-test API responses.

## Notes

- Supabase/Vercel accounts and credentials still need to be configured by you; the repository does not create cloud projects or deploy itself.
- Both have free plans, subject to their current quotas/eligibility. No paid API or AI dependency is built into this app. Keep an eye on storage for many large diagrams and database size for long-term history.
- The old SQLite/Notion modules and data remain for reference. New website data does not automatically import old SQLite attempts or the old browser-only timer. The website uses the existing canonical schedule.
- `Procfile`/`render.yaml` now use the website backend too, if you prefer Render later. The old `app.bot:fastapi_app` / `python -m app.bot` entry points now also default to the website backend. Historical poll handlers are retained only behind the explicit `LEGACY_TELEGRAM_POLLS=true` opt-in. Leave that flag unset.

Validation:

```bash
.venv/bin/python -m pytest -q
npm run check
npm run build
```
