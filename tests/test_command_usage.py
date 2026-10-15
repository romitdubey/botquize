"""Exercise each user-visible command against isolated data and mocked Telegram."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import database as db
from app.handlers import commands, start, tracking
from app.handlers.callbacks import _handle_reset_confirm
from app.models import SessionStatus
from tests.test_tracking import running


def chat(args=()):
    status=SimpleNamespace(edit_text=AsyncMock())
    message=SimpleNamespace(reply_text=AsyncMock(return_value=status),reply_document=AsyncMock())
    update=SimpleNamespace(effective_user=SimpleNamespace(id=123456789),message=message)
    context=SimpleNamespace(args=list(args),user_data={})
    return update,context,status


@pytest.mark.asyncio
@pytest.mark.parametrize('handler,phrase',[
    (start.start_command,'/notion_setup'),
    (start.help_command,'/sync all'),
    (commands.status_command,'No active quiz'),
    (commands.result_command,'No active quiz'),
    (commands.review_command,'No active quiz'),
    (commands.reset_command,'No active quiz'),
    (commands.history_command,'No quiz history'),
    (commands.stats_command,'OVERALL STATISTICS'),
    (tracking.topic_command,'/topic YYYY-MM-DD'),
    (tracking.wrong_command,'No recorded wrong answers'),
    (tracking.retryweek_command,'No wrong answers recorded'),
])
async def test_commands_with_no_quiz_give_clear_responses(handler,phrase):
    update,context,_=chat()
    await handler(update,context)
    assert phrase in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_topic_labels_are_saved_and_can_be_cleared():
    update,context,_=chat(['2026-10-16','|','Biochemistry'])
    await tracking.topic_command(update,context)
    assert db.get_setting('topic:123456789')=={'topic':'Biochemistry','study_date':'2026-10-16'}
    context.args=['clear']
    await tracking.topic_command(update,context)
    assert db.get_setting('topic:123456789')=={}


@pytest.mark.asyncio
async def test_plan_retrieves_a_scheduled_day():
    update,context,_=chat(['2026-10-16'])
    await tracking.plan_command(update,context)
    assert 'Introduction to Biochemistry' in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_completed_quiz_status_results_review_history_and_stats():
    running(2)
    assert db.record_answer('quiz','quiz-poll-0',1,False,123)
    assert db.record_answer('quiz','quiz-poll-1',0,True,123)
    assert db.complete_session('quiz')
    for handler,expected in [(commands.status_command,'Enzymes'),(commands.result_command,'QUIZ COMPLETED'),
                             (commands.review_command,'WRONG QUESTIONS'),(commands.history_command,'Enzymes'),
                             (commands.stats_command,'OVERALL STATISTICS')]:
        update,context,_=chat()
        await handler(update,context)
        assert expected in update.message.reply_text.call_args.args[0]
    assert db.get_history_count()==1


@pytest.mark.asyncio
async def test_reset_requires_confirmation_and_retains_saved_answers():
    running(2)
    db.record_answer('quiz','quiz-poll-0',1,False,123)
    update,context,_=chat()
    await commands.reset_command(update,context)
    assert db.load_session('quiz').status==SessionStatus.RUNNING
    keyboard=update.message.reply_text.call_args.kwargs['reply_markup']
    assert keyboard.inline_keyboard[0][0].callback_data=='quiz:reset_confirm'
    query=SimpleNamespace(edit_message_text=AsyncMock())
    await _handle_reset_confirm(query)
    assert db.load_session('quiz').status==SessionStatus.CANCELLED
    assert db.load_session('quiz').wrong==1


@pytest.mark.asyncio
async def test_wrong_command_sends_reusable_json():
    running(2)
    db.record_answer('quiz','quiz-poll-0',1,False,123)
    update,context,_=chat(['today'])
    await tracking.wrong_command(update,context)
    file=update.message.reply_document.call_args.kwargs['document']
    payload=json.loads(file.input_file_content)
    assert payload['quiz_kind']=='revision'
    assert len(payload['questions'])==1
    assert payload['questions'][0]['correct_option']==0


@pytest.mark.asyncio
async def test_backup_contains_the_committed_sqlite_database():
    running(1)
    db.record_answer('quiz','quiz-poll-0',1,False,123)
    update,context,_=chat()
    await tracking.backup_command(update,context)
    file=update.message.reply_document.call_args.kwargs['document']
    assert file.input_file_content.startswith(b'SQLite format 3\x00')
    assert len(file.input_file_content)>4096


@pytest.mark.asyncio
@pytest.mark.parametrize('handler',[tracking.sync_command,tracking.notion_setup_command])
async def test_notion_commands_explain_missing_runtime_credentials(handler,monkeypatch):
    monkeypatch.setattr(tracking.notion_sync,'NOTION_TOKEN','')
    update,context,status=chat()
    await handler(update,context)
    assert 'NOTION_TOKEN' in status.edit_text.call_args.args[0]
