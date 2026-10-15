## Simplified learner view

The Notion hub now has exactly four tabs: Schedule, Questions, Results and Timer.
The 56 schedule dates are preserved, with no book-page fields or technical
instructions in the learner view. The former large plan, Wrong Question Bank
and Weekly Review databases were moved to Notion Trash at the user's request.
Their source IDs are no longer used by the runtime simple profile.

Wrong-question archives and weekly retries remain in SQLite/Telegram.
Notion /sync now updates Results and the ordinary Questions collection only.
It does not recreate a wrong-question bank or weekly database, and it preserves
Schedule study status, Minutes and Notes.

The Timer tab contains an interactive Start/Pause timer with daily totals
(India time) and a downloadable study log. Persistence depends on browser storage
being available in the Notion preview; a warning appears if it is unavailable.
These totals are device/browser local and do not write to Schedule automatically.
The timer controls and reload persistence were tested in a local browser preview;
the logged-in Notion embed could not be browser-tested in this session.

## Live Notion hub

The hub was created and verified on 15 October 2026:
https://app.notion.com/p/3fa16643962f811da7d2ee7a062acb45

It contains 56 dated daily tasks, 9 weekly reviews, the simplified tracker tabs. It starts private;
invite your friend with Can edit. No quiz scores or reading progress were invented.

The existing workspace IDs are saved in `app/data/notion_workspace.json`.
After setting the deployed bot's own `NOTION_TOKEN` and sharing the hub with that
integration, `/notion_setup` binds to these existing databases and validates them.
Leave `NOTION_PARENT_PAGE_ID` empty to use this hub by default, or set it to the
hub ID above. It will not create another copy of the hub in that case.
The connected Codex Notion app does not provide the runtime bot its credential.

# Study tracker and Monday revision

The existing bot now saves quizzes and first answers in SQLite. `/result` and
`/review` also work for the latest completed quiz. Only `/sync` contacts Notion
for result snapshots; recording answers never contacts Notion.

## Daily use

1. Before uploading, label the quiz with the date its concepts were studied:
   `/topic 2026-10-20 | Enzymes and enzyme kinetics`.
2. Upload your usual question JSON and press **Start Quiz**. Its optional
   `topic` and `study_date` fields override the saved label. The label persists
   until changed or `/topic clear`; it does not rename existing sessions.
3. Your friend answers. The first authorized respondent binds the quiz to their
   ID; another admin cannot add answers to that session. Set `LEARNER_USER_ID`
   if you want to enforce her ID from the beginning. The same score is visible
   to both authorized admins.
4. `/result` shows the saved result. It does not sync or archive anything anew.
5. `/sync` updates quizzes started or answered today (India time), the ordinary Questions collection and Results.
   `/sync all` catches up everything, including quizzes from earlier days.
   `/sync 2026-10-20`, `/sync week` and `/sync lastweek` are also supported.
6. `/wrong today` downloads today's mistakes as a JSON file. Other choices:
   `yesterday`, `week`, `lastweek`, or `YYYY-MM-DD`. It works before completion
   too. Questions not yet answered are not wrong questions.

### Monday

Use `/retryweek` to prepare all unique wrong questions answered during the previous
Monday-Sunday week, then press **Start weekly retry**. This creates a new revision
session and keeps all original scores. Alternatively `/wrong lastweek` gives a
single consolidated JSON file you can re-upload. You do not have to save and
merge daily files manually. A question answered wrongly again in a retry appears
in that new week's mistake set. Merely retrying correctly never deletes history.

Weeks and days use `STUDY_TIMEZONE` (default `Asia/Kolkata`). Grouping follows the
actual answer timestamp, not the upload/study date. Source identities deduplicate
repeat attempts in the same export. Keep the exported `source_id`, `source_topic`
and `quiz_kind: "revision"` when re-uploading. Otherwise a hand-edited re-upload
may be treated as a new original quiz.

`/plan` shows today's scheduled entry; `/plan 2026-10-20` shows a chosen date.
`/backup` downloads a consistent full SQLite backup including WAL contents.

## Notion connection and one-time setup

The Codex Notion plugin's login is **not** a credential for your deployed bot.
The bot needs its own Notion integration token available in its environment:

- `NOTION_TOKEN`: put it in `.env` locally or the host's secret environment UI.
  Do not send it in Telegram or commit it.
- `NOTION_PARENT_PAGE_ID`: the ID of a chosen parent page. Share that page with
  the integration using Notion's Connections menu. The token requires read,
  insert and update capabilities for that page.
- `DATABASE_PATH`: a path on durable storage (see below).

After deploying, run `/notion_setup`, or run `python -m app.notion_setup` locally
with the same database and environment as the bot. This creates/resumes:

| Database | What one row represents | Who updates it |
| --- | --- | --- |
| Schedule | One date, 16 Oct-10 Dec 2026; 56 dated tasks | Friend edits status, Minutes and Notes |
| Questions | One distinct practice question | Manual /sync |
| Results | One original/revision quiz session | Manual /sync; linked to its study day |

The 30 first-pass weekdays cover all 65 listed chapters / 529 estimated content
pages by 26 November. Ten weekday revision slots finish 10 December. There are
8 Saturday PYQ tasks and 8 Sunday mock tasks. The plan covers the five supplied
book parts; it does not claim full exam syllabus coverage or verify the exam date.

Your friend can edit **Study status, Minutes and Notes** directly in Schedule.
Quiz sync never overwrites these fields. Study completion is not inferred from
accuracy. The Timer tab keeps its own daily history; it does not fill Schedule's
Minutes column automatically.

Setup is resumable: stable keys locate existing rows, successful writes are
kept, and retries do not add duplicate dated tasks/results. Existing mismatched
schemas are reported instead of rewritten. A failed sync leaves local data safe;
retry it. Run one bot instance and do not run setup concurrently in another process.
Changing the Notion parent on the same database is intentionally refused.

Share the created hub with your friend using **Share > Invite > Can edit**.
The simplified hub already contains its four tabs. Setup validates and reuses
the collections; it does not invite people automatically.

## Storage and deployment

SQLite survives a process restart **only if its file survives**. An ephemeral
hosting filesystem can discard it on service replacement/redeploy. The existing
Render free-web configuration has no durable disk. This change does not purchase
a hosting plan or attach a disk. For reliable history, mount durable storage and
set `DATABASE_PATH` to that mount (for example `/var/data/quizbot.db`), or deploy on
a persistent server. Keep `/backup` files as a separate recovery copy. Notion
snapshots are useful for reporting but are not a replacement for the full quiz DB.

To restore a backup, stop the bot, preserve its current database, and replace the
database at `DATABASE_PATH` with the downloaded backup before restarting. Keep
backups private. No uploaded Telegram file can overwrite the database.

The old in-memory version cannot recover answers already lost in previous
restarts. Existing SQLite tables are migrated additively. Legacy answers without
answer timestamps cannot reliably be assigned to a week; no dates are invented.
After a restart during publishing, posted polls continue to track answers;
`/reset` and re-upload if publication stopped part-way. Publication is not retried
automatically because a network interruption can leave an uncertain sent poll.

Deploy the modified code to your existing service, configure the Notion values,
and restart once. Startup registers a secret-authenticated Telegram webhook.
Use a group or private messages for identifiable quiz answers. If using `me`,
polls go to `LEARNER_USER_ID` when set, otherwise the person who starts the quiz.
The learner must have started a private chat with the bot before it can DM her.

## Validation

Automated tests use isolated temporary databases, mocked Telegram calls and a
stateful fake Notion HTTP server; they never send real questions or create live
Notion pages. Run `.venv/bin/python -m pytest -q`.

Notion API documentation:
- https://developers.notion.com/docs/upgrade-guide-2025-09-03
- https://developers.notion.com/reference/create-a-database
- https://developers.notion.com/reference/query-a-data-source
