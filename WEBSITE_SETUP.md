# Study Grove — mobile website + Telegram admin

Everything is in this repository. The website replaces the Notion tracker and Telegram quiz polls. Supabase stores the questions, full explanations, attempts, quiz time and wrong-answer history. Vercel serves the frontend and Python API together.

## 1. Connect Supabase

1. In your existing Supabase project, open **SQL Editor**, paste `supabase/schema.sql`, and run it. This creates the private study tables and file buckets.
2. Under **Authentication → Users**, create your friend's email/password account. Use the dashboard's create-user option with email confirmed. The website has sign-in only; no public sign-up screen.
3. Copy the variables from `.env.web.example` into your local `.env`. Preserve your existing `BOT_TOKEN` and `ADMIN_USER_ID`.
4. Get the project URL, public anon/publishable key, and server secret/service-role key from the Supabase project API settings. The server key must stay in `.env`/Vercel settings. It is never included in website JavaScript.
5. Set `STUDY_ALLOWED_EMAILS` to your friend's exact login email. You can allow multiple emails separated by commas; each account has independent study records. For your own read-only mentor login, create a second Auth user, include both emails in `STUDY_ALLOWED_EMAILS`, set `STUDY_MENTOR_EMAIL` to your email and `STUDY_LEARNER_ID` to her Auth user UUID. You will see her quiz time, schedule and results while her login can study/take tests.

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

`correct_option` is **zero based**: 0=A, 1=B, 2=C, 3=D. Daily quizzes have **no deadline or question-count cap**. Upload limit: **10 MB per JSON file**, with bounded field lengths. An old `duration_minutes` field is accepted but ignored for daily practice. Long questions/options/explanations remain intact.

The date labels the **study day**, not the date of upload. Use `/open` to approve the quiz. It becomes available no earlier than the following calendar day in India; you can approve it in advance. Until approval the bank remains a private draft. No question is posted to a Telegram group/channel.

- `/image 12` → send the diagram/photo → it attaches to printed question **12** (use `/image #12` for the 12th array item). For best quality send as an image document. PNG/JPEG/WebP supported, max 10 MB. `/open` after adding diagrams.
- A standalone diagram question: `/question {"question":"...","options":["A","B"],"correct_option":0,"explanation":"..."}` → send its image → `/open`. This creates a **separate one-question draft**, not an append to an already open test. Select `/topic` first.
- `/tests` lists IDs. `/select ID` selects an older upload before `/image`, `/open` or `/close`.
- `/close` prevents new attempts. An already started attempt can finish using its immutable question snapshot.
- Identical reuploads for the same topic/study date do not duplicate or close the existing bank. If content is revised, it becomes a new draft. Existing attempts preserve the original question/explanation snapshot.
- `/status`, `/plan`, `/help` explain current selection and today's topic.

## 5. Her mobile workflow

Open the Vercel link, sign in, optionally **Add to Home Screen** from the phone browser.

- **My day**: Vishu sees today's topic and can open its material. Marking studied asks “Vishu, padh liya na? 💚” before saving. There is no study timer.
- **Schedule**: future days stay locked. Today and previous dates open their Material/Quiz tabs. PDFs/photos can be opened or downloaded; earlier material remains available. Only today's completion can be changed.
- **Practice**: daily quizzes count active time upward, with no deadline or marks. Pause/Save & exit saves answers and time. Resume later, even another day. Completed quizzes open their saved result.
- **Full PYQ exam**: a separate three-hour countdown, A/B/C section navigation, official attempt limits and negative marking. Leaving does not pause the deadline.
- **Results**: daily accuracy/correct/wrong/skipped and active time; full exam marks out of 200 with section totals. Every submitted question retains its correct answer and explanation.
- **Mistakes**: historical wrong answers and fresh practice retries. Retrying does not erase earlier results.

The Monday retry is built automatically when the dashboard is first loaded for that week, using the previous **Monday through Friday in India time**, deduplicated by question. Saturday/Sunday test mistakes remain in the all-mistakes bank but are excluded from this weekday retry. Each Monday snapshot is created once; no Vercel paid cron is needed. No mistakes means no empty quiz.

## Quiz timing

Daily practice saves active time every 20 seconds, on Pause, Save & exit, and submission. Hiding the tab/app pauses it; returning requires Resume. If a browser is killed/offline before the pause reaches the server, counting stops at the last successful heartbeat plus 60 seconds, reconciled on the next request. Multiple unfinished quizzes retain independent answers; starting/resuming another pauses the previous practice clock. Practice never auto-submits. Existing unfinished daily countdown attempts become resumable practice without losing answers; their previous active time cannot be reconstructed, so the new active clock starts at zero.

Full exams have a server-controlled **180-minute deadline** that continues outside the website. Expired attempts finalize on the next dashboard/attempt request, using saved answers only. An active full exam must finish before starting another test. Submissions are idempotent; correct keys and explanations remain private until submission.

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

## Daily flow update: notes and date locks

For an existing Supabase project, run **`supabase/002_daily_notes.sql`** once in the SQL Editor. New installations can use the full updated `schema.sql` instead. This adds a private notes table and a separate private PDF/photo bucket; it does not delete existing study data.

In Telegram:

```text
/notes 2026-10-16 | Introduction to Biochemistry
```

Send one or more PDFs/photos (each up to 10 MB). They are attached to that study date. Then:

```text
/done
/topic 2026-10-16 | Introduction to Biochemistry
```

Upload the normal quiz JSON, attach any diagrams with `/image NUMBER`, and use `/open`. `/open` approves publication; the quiz is hidden until **17 October India time**, the day after its study date. You may prepare notes and approve quizzes in advance. Correct answers/explanations are still hidden until submission.

On the website, today's date opens Material and Quiz tabs, with a sweet study-completion confirmation. Future days are locked; earlier material and released quizzes remain accessible. No study timer is shown. The dashboard highlights yesterday's released topic quiz, today's PYQ and Monday retries. Older quizzes and results remain accessible.

### If Telegram still targets Render

Set local **and Vercel** `APP_URL=https://botquize.vercel.app` (or your production domain). Keep `BOT_TOKEN` and `WEBHOOK_SECRET` consistent locally and in Vercel. After redeploying:

```bash
.venv/bin/python scripts/check_webhook.py
.venv/bin/python scripts/check_webhook.py --repair
.venv/bin/python scripts/setup_webhook.py
```

The check validates the production endpoint with an empty authenticated update before switching. It reports delivery errors/pending updates without printing tokens and retains pending Telegram updates. `/start` and `/help` work even when the study database setup needs attention.

## Bulk daily questions with any number of diagrams

Your existing full-paper JSON uploads still work. `/bulk` explicitly enters JSON upload mode after setting `/topic DATE | Topic`. `correct_option` stays zero based; explanations remain intact. A sample is in `examples/diagram_paper.json`.

For reliable image matching, include a **printed question number** in each question:

```json
{
  "question_number": 12,
  "question": "Identify X in the diagram.",
  "options": ["A", "B", "C", "D"],
  "correct_option": 2,
  "explanation": "Full explanation.",
  "image_url": ""
}
```

After uploading the full JSON paper:

```text
/images
```

Send whichever diagram files your questions need as **documents** named `Q12.png`, `Q27.jpg`, `question_42.webp`, etc. Each filename identifies its question. You can send multiple individually named documents together. If sending compressed photos instead, put `Q12`, `Q27`, etc. in **each photo's caption**; one album caption does not label every image. `/image Q12` followed by a photo is another option.

Numbering precedence is `question_number`, then `number`, then a numeric `id`, then a printed number such as `21. ...` at the beginning of the question text, otherwise the 1-based array position. If the printed number differs from its array position, use `Q59` for printed question 59 or `/image #12` for the 12th array item. Ambiguous duplicate numbers are rejected rather than guessing.

Finish with `/done`, then `/open`. Only the questions that have images display a diagram between the question and its answer options. Unillustrated questions have no image placeholder. `/question {JSON}` creates a standalone draft question and attaches the next image to it.

Run the **updated `supabase/002_daily_notes.sql`** once before using diagram attachments: it now also creates the private atomic image-attachment function. It is safe to rerun and preserves existing data. This prevents concurrent album uploads from replacing each other's question images. Existing attempts retain their original snapshots; attach diagrams before opening a test for learners.


## Separate full PYQ upload

Existing projects must run **`supabase/003_pyq_mode.sql`** after `002_daily_notes.sql`. It only extends the quiz type constraint; it does not remove study data. New projects can run the updated full `schema.sql` instead.

```text
/pyq 2026-10-17 | CSIR Life Sciences PYQ
```

Upload JSON in the **separate section format** shown in `examples/pyq_paper.json`:

```json
{"quiz_title":"Paper title","sections":{"A":["20 question objects"],"B":["50 question objects"],"C":["75 question objects"]}}
```

The strings above describe the arrays, not valid questions. The example file contains a complete, structurally valid **145-question sample template**; replace every sample with your actual paper. Each object uses `question_number`, `question`, four `options`, zero-based `correct_option`, and `explanation`, just like daily questions. Use unique numbers **1–145 across the whole paper**. Do not restart numbering at 1 in each section; this keeps diagram matching unambiguous.

Then `/images` → send `Q7.png`, `Q83.jpg`, etc. (or captions Q7, Q83), `/done`, `/open`. The PYQ opens on its scheduled paper date, rather than the following day. Prepare/upload before opening so started attempts include every image. There is no image-count cap. Use `/topic DATE | Topic` to return to daily JSON format; `/bulk` preserves the current daily/PYQ upload selection.

Official LS/BT pattern: A has 20 questions, evaluate first 15 answered (+2/−0.5); B has 50, first 35 (+2/−0.5); C has 75, first 25 (+4/−1). Total 200 marks, 180 minutes. Extra answered questions are excluded in **paper order**, not the order clicked. Unanswered/excluded questions earn zero; excluded answers are labelled separately and do not enter the wrong-answer bank. The UI shows answered/limit per section; review includes section scores. Daily and Monday retry quizzes have no marks/negative marking.

Source: [NTA December 2026 Information Bulletin, scheme pp.18–19](https://cdnbbsr.s3waas.gov.in/s3efdf562ce2fb0ad460fd8e9d33e57f57/uploads/2026/10/202610071407707951.pdf). Verify future pattern changes against the relevant official bulletin before using this for another exam cycle. The sidebar counts down to the **10 December revision goal**, not an assumed exam date.

## Two separate accounts: test first, then copy to Vishu

1. In **Supabase → Authentication → Users**, create two confirmed email/password users: your own and Vishu's. Keep passwords out of Telegram/chat.
2. Set `STUDY_ALLOWED_EMAILS=your@email.com,her@email.com` in Vercel and redeploy. Run **`supabase/004_account_notes.sql`** for an existing project (after the earlier migrations). Fresh projects can use the updated full schema.
3. Bind the existing logins once in your private admin bot:

```text
/account me your@email.com
/account vishu her@email.com
/account me
```

After binding, just `/account me` or `/account vishu` switches the upload destination. Account selection persists across server restarts. Switching clears the selected quiz, pending diagram, topic/date and notes upload mode so an image cannot accidentally land in the previous account. Select your destination before `/topic`, `/notes` or uploads. Both aliases must use different logins. Account commands do not create Auth users or change their passwords.

Use the usual `/topic DATE | Topic`, JSON, `/images`, `/open` flow while `me` is selected. Sign in to the website with your own login to test. There is a **Your test account** banner. Practice answers, results, studied days, timers, mistakes and Monday retry snapshots stay under your own user ID. Even if your email used to be configured as a read-only mentor, binding it as `me` gives it its own independent test progress; it no longer maps to Vishu's learner ID. Vishu's UI and schedule remain the same.

Daily release rules still apply to your test login: a quiz labelled with yesterday's study date opens today. PYQ papers open on their labelled date. Switching accounts does not bypass date locks.

When satisfied, keep the source quiz selected in your account:

```text
/copyto vishu
```

The bot returns a **Copy ID**. Questions, full explanations, attached diagrams and all your notes from that study date are copied to Vishu. The quiz is a draft; no attempt, score, wrong-answer history, timer or studied-day mark is copied. The original study date is preserved, including its release rule. Copied files reuse the same private immutable storage objects; the banks/notes have separate rows and do not expose public buckets. Later diagram replacements on the source quiz do not modify the copied quiz or existing attempts.

```text
/account vishu
/select COPY-ID-FROM-BOT
/open
```

Repeated copies of the same question snapshot are idempotent: they reuse the same destination copy and preserve its current open/closed status and any learner attempts. An altered source question/diagram snapshot creates a new draft. Notes are immediately available to their destination on accessible study dates; copying does not wait for `/open` to release notes. You can instead select `/account vishu` before uploading a fresh normal bank directly.

Older unscoped uploads remain legacy content for Vishu; your `me` login hides those old shared quizzes/notes. Selecting Vishu allows management of legacy banks. New uploads require an explicit selected account. **A whole-database reset is unnecessary and would remove both accounts' study data.**

After deploying these command changes, run `scripts/setup_webhook.py` locally once to refresh Telegram's command menu. Typed commands work after redeployment even before the menu refresh.
