"""Study labels, explicit Notion snapshots, and reusable mistake exports."""
import io
import json
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import ContextTypes

from app import database as db
from app.services import notion_sync
from app.services.mistakes import export_wrong
from app.services.planner import today, plan_rows, date_window
from app.utils.helpers import admin_only


def _selector(context,default='today'):
    value=context.args[0] if context.args else default
    if len(context.args)>1:raise ValueError('Use one date or period.')
    if value!='all':date_window(value)
    return value


@admin_only
async def topic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw=' '.join(context.args).strip()
    if not raw:
        current=db.get_setting(f'topic:{update.effective_user.id}',{})
        await update.message.reply_text('Before uploading: /topic YYYY-MM-DD | Topic name\n'
            'Use the date she studied that topic, even if its quiz is tomorrow.\n'
            '/topic clear removes the label.\nCurrent: '+json.dumps(current,ensure_ascii=False))
        return
    if raw=='clear':
        db.set_setting(f'topic:{update.effective_user.id}',{})
        await update.message.reply_text('Topic label cleared.');return
    if '|' in raw:
        date_text,topic=map(str.strip,raw.split('|',1))
        try:date_text=date.fromisoformat(date_text).isoformat()
        except ValueError:
            await update.message.reply_text('Date format: /topic 2026-10-20 | Enzyme kinetics');return
    else:date_text,topic=today().isoformat(),raw
    if not topic or len(topic)>500:
        await update.message.reply_text('Topic must be 1-500 characters.');return
    db.set_setting(f'topic:{update.effective_user.id}',{'topic':topic,'study_date':date_text})
    await update.message.reply_text(f'Next uploads labelled: {topic}\nStudy date: {date_text}\nChange /topic before a different topic. Existing quizzes are unchanged.')


@admin_only
async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected=context.args[0] if context.args else today().isoformat()
    if selected=='today':selected=today().isoformat()
    row=next((r for r in plan_rows() if r['date']==selected),None)
    if not row:
        await update.message.reply_text('No planned entry. Use /plan YYYY-MM-DD (16 Oct - 10 Dec 2026).');return
    pages=f"\nBook pp. {row['page_start']}-{row['page_end']}" if 'page_start' in row else ''
    await update.message.reply_text(f"{row['date']} | {row['kind']}\n{row['topic']}{pages}\n\nMonday: /retryweek for last week's mistakes.\n/topic {row['date']} | {row['topic']}")


@admin_only
async def wrong_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    default='lastweek' if today().weekday()==0 else 'today'
    try:
        selector=_selector(context,default)
        if selector=='all':raise ValueError('Choose a day or week.')
        payload=export_wrong(selector)
    except ValueError:
        await update.message.reply_text('Use /wrong today, yesterday, week, lastweek, or YYYY-MM-DD.');return
    if not payload['questions']:
        await update.message.reply_text(f'No recorded wrong answers for {selector}.');return
    data=io.BytesIO(json.dumps(payload,ensure_ascii=False,indent=2).encode())
    await update.message.reply_document(document=InputFile(data,filename=f'wrong_{selector}_{today()}.json'),
        caption=f"{len(payload['questions'])} unique wrong questions. Re-upload this JSON to run a separate revision quiz.")


@admin_only
async def retryweek_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db.load_active_session():
        await update.message.reply_text('Finish or /reset the current quiz before preparing the weekly retry.');return
    payload=export_wrong('lastweek')
    if not payload['questions']:
        await update.message.reply_text('No wrong answers recorded last week.');return
    payload.update(study_date=today().isoformat(),topic='Weekly wrong-answer revision')
    context.user_data['pending_quiz_data']=payload
    await update.message.reply_text(f"Last week's {len(payload['questions'])} unique mistakes are ready. Original results stay unchanged.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Start weekly retry',callback_data='quiz:start')],
                                           [InlineKeyboardButton('Cancel',callback_data='quiz:cancel')]]))


@admin_only
async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:selector=_selector(context)
    except ValueError:
        await update.message.reply_text('Use /sync, /sync YYYY-MM-DD, /sync week, /sync lastweek or /sync all.');return
    if notion_sync.SYNC_LOCK.locked():
        await update.message.reply_text('A Notion operation is already running. Please wait for its result.');return
    status=await update.message.reply_text('Syncing the selected quiz stats to Notion...')
    async with notion_sync.SYNC_LOCK:
        try:
            async with notion_sync.NotionClient() as client:
                count=await notion_sync.sync_results(client,selector)
        except notion_sync.NotionError as exc:
            await status.edit_text(str(exc));return
    await status.edit_text(f'Notion synced: {count} quiz snapshots ({selector}). Study progress and notes were preserved.')


@admin_only
async def notion_setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if notion_sync.SYNC_LOCK.locked():
        await update.message.reply_text('A Notion operation is already running.');return
    status=await update.message.reply_text('Preparing the Notion hub and the dated study plan. This can take a few minutes...')
    async with notion_sync.SYNC_LOCK:
        try:
            async with notion_sync.NotionClient() as client:
                url=await notion_sync.setup_hub(client)
        except notion_sync.NotionError as exc:
            await status.edit_text(str(exc));return
    await status.edit_text('Study hub ready: '+url+'\nShare this hub with your friend (Can edit). Use /sync when you want quiz stats updated.')


@admin_only
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # SQLite's backup API includes committed WAL contents; copying just the .db can lose them.
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'quizbot-backup.db'
        with db.get_conn() as source:
            target=sqlite3.connect(path)
            try:source.backup(target)
            finally:target.close()
        with path.open('rb') as stream:
            await update.message.reply_document(document=InputFile(stream,filename=f'quizbot-backup-{today()}.db'),
                caption='Full local quiz database backup. Keep it privately; it contains answer history.')
