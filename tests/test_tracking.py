import importlib
import json
import sqlite3
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import database as db
from app.models import QuizQuestion, QuizSession, SessionStatus
from app.services import quiz_service
from app.services.json_validator import load_and_validate
from app.services.mistakes import export_wrong
from app.services.planner import date_window, plan_rows


def running(n=2,session_id='quiz',kind='book',study_date='2026-10-16'):
    s=QuizSession(session_id=session_id,quiz_title='Enzymes',description='',total_questions=n,
        topic='Enzymes',study_date=study_date,quiz_kind=kind,status=SessionStatus.RUNNING,
        questions=[QuizQuestion(i,f'Question {i}?',['A','B'],0,image_url='https://example.com/image.png',source_topic='Enzymes') for i in range(n)])
    db.save_session(s)
    for i in range(n):db.update_question_poll(s.session_id,i,f'{session_id}-poll-{i}',100+i)
    db.advance_current_question(s.session_id,n)
    return db.load_session(s.session_id)


def test_restart_keeps_questions_answers_images_and_metadata(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DATABASE_PATH", db.DATABASE_PATH)
    s=running()
    assert db.record_answer(s.session_id,'quiz-poll-0',1,False,123)
    importlib.reload(db)
    loaded=db.load_session(s.session_id)
    assert loaded.wrong==1 and loaded.learner_user_id==123
    assert loaded.questions[0].image_url=='https://example.com/image.png'
    assert loaded.questions[0].answer_user_id==123
    assert loaded.questions[0].answered_at.tzinfo is not None
    assert loaded.study_date=='2026-10-16' and loaded.topic=='Enzymes'
    assert db.find_session_by_poll('quiz-poll-0')==('quiz',0,0)


def test_completion_waits_for_every_question_to_publish():
    s=running()
    db.advance_current_question(s.session_id,1)
    db.record_answer(s.session_id,'quiz-poll-0',0,True,123)
    assert not quiz_service.check_completion(db.load_session('quiz'))
    assert not db.complete_session('quiz')
    db.record_answer(s.session_id,'quiz-poll-1',1,False,123)
    db.advance_current_question('quiz',2)
    assert db.complete_session('quiz')
    assert not db.complete_session('quiz')
    assert db.get_history_count()==1
    assert db.get_overall_stats()['quizzes_completed']==1
    assert db.load_session('quiz').completed_at is not None


def test_duplicate_updates_and_second_user_do_not_change_score():
    s=running()
    assert db.record_answer('quiz','quiz-poll-0',1,False,123)
    assert not db.record_answer('quiz','quiz-poll-0',0,True,123)
    assert not db.record_answer('quiz','quiz-poll-1',0,True,987)
    assert db.load_session('quiz').attempted==1


def test_reset_keeps_mistakes_but_ignores_later_answers():
    running()
    assert db.record_answer('quiz','quiz-poll-0',1,False,123)
    db.update_session_status('quiz',SessionStatus.CANCELLED)
    assert not db.record_answer('quiz','quiz-poll-1',1,False,123)
    assert db.find_session_by_poll('quiz-poll-1') is None
    assert len(export_wrong('today')['questions'])==1


def test_india_week_boundaries_and_friday_answers():
    start,end=date_window('lastweek',date(2026,10,26))
    assert start.isoformat()=='2026-10-18T18:30:00+00:00'
    assert end.isoformat()=='2026-10-25T18:30:00+00:00'
    running(2)
    db.record_answer('quiz','quiz-poll-0',1,False,123,datetime(2026,10,25,18,29,tzinfo=timezone.utc))
    db.record_answer('quiz','quiz-poll-1',1,False,123,datetime(2026,10,25,18,30,tzinfo=timezone.utc))
    exported=export_wrong('lastweek',date(2026,10,26))
    assert [q['question'] for q in exported['questions']]==['Question 0?']


def test_wrong_export_roundtrips_and_deduplicates_retests():
    running(1)
    answered=datetime(2026,10,20,6,tzinfo=timezone.utc)
    db.record_answer('quiz','quiz-poll-0',1,False,123,answered)
    payload=export_wrong('week',date(2026,10,21))
    result,data=load_and_validate(json.dumps(payload).encode())
    assert result.ok and data['quiz_kind']=='revision'
    retry=quiz_service.create_session(data)
    db.update_session_status(retry.session_id,SessionStatus.RUNNING)
    db.update_question_poll(retry.session_id,0,'retry-poll',456)
    db.record_answer(retry.session_id,'retry-poll',1,False,123,answered)
    assert len(export_wrong('week',date(2026,10,21))['questions'])==1
    assert db.load_session('quiz').wrong==1
    assert export_wrong('week',date(2026,10,21))['questions'][0]['source_topic']=='Enzymes'


def test_retest_success_preserves_original_mistake():
    running(1)
    db.record_answer('quiz','quiz-poll-0',1,False,123)
    payload=export_wrong('today')
    retry=quiz_service.create_session(payload)
    db.update_session_status(retry.session_id,SessionStatus.RUNNING)
    db.update_question_poll(retry.session_id,0,'retry',11)
    db.record_answer(retry.session_id,'retry',0,True,123)
    assert len(export_wrong('today')['questions'])==1
    assert db.load_session(retry.session_id).correct==1
    assert db.load_session('quiz').wrong==1


def test_revised_plan_preserves_history_weekends_and_covers_all_units():
    from app.services.planner import _original_book_rows
    rows=plan_rows();original=_original_book_rows()
    assert len(rows)==56
    assert [r for r in rows if r['date']<='2026-10-22']==[r for r in original if r['date']<='2026-10-22']
    assert [r for r in rows if r['kind'] in ('PYQ','Mock')]==[r for r in original if r['kind'] in ('PYQ','Mock')]
    future=[r for r in rows if r['date']>'2026-10-22' and r['kind'] not in ('PYQ','Mock')]
    assert len(future)==35
    assert future[0]['date']=='2026-10-23' and future[0]['topic'].startswith('Electron Transport & Oxidative Phosphorylation; Pentose Phosphate Pathway; Photosynthesis')
    assert not any(r['topic']=='Citric Acid Cycle; Vitamins and Minerals' for r in future)
    assert {r['unit'] for r in future if r['unit'] is not None}==set(range(1,15))
    assert all('page_start' not in r and r['pages']==0 for r in future)
    assert [r['date'] for r in future if r['kind']=='Revision']==['2026-12-10']
    assert len({r['date'] for r in rows})==56
    assert sum(r['kind']=='PYQ' for r in rows)==8
    assert sum(r['kind']=='Mock' for r in rows)==8



@pytest.mark.parametrize('extra',[{'study_date':'bad'},{'study_date':'20261020'},{'topic':None},{'quiz_kind':'bad'}])
def test_invalid_tracking_metadata_rejected(extra):
    payload={'quiz_title':'Q','questions':[{'question':'Q?','options':['A','B'],'correct_option':0}],**extra}
    assert not load_and_validate(json.dumps(payload).encode())[0].ok


@pytest.mark.asyncio
async def test_result_is_read_only_and_available_after_completion():
    from app.handlers.commands import result_command
    running(1)
    db.record_answer('quiz','quiz-poll-0',1,False,123)
    assert db.complete_session('quiz')
    update=SimpleNamespace(effective_user=SimpleNamespace(id=123456789),message=SimpleNamespace(reply_text=AsyncMock()))
    with patch('app.services.notion_sync.sync_results',new_callable=AsyncMock) as sync:
        await result_command(update,SimpleNamespace())
        sync.assert_not_called()
    assert 'QUIZ COMPLETED' in update.message.reply_text.call_args.args[0]
    assert db.get_history_count()==1


@pytest.mark.asyncio
async def test_reset_stops_background_publisher(monkeypatch):
    s=running(2)
    # Clear poll associations so the fake publisher really sends polls.
    with db.get_conn() as conn:conn.execute('UPDATE questions SET telegram_poll_id=NULL')
    s=db.load_session('quiz')
    bot=SimpleNamespace(send_photo=AsyncMock(),send_message=AsyncMock(),send_poll=AsyncMock())
    async def send(**kwargs):
        db.update_session_status('quiz',SessionStatus.CANCELLED)
        return SimpleNamespace(poll=SimpleNamespace(id='new'),message_id=12)
    bot.send_poll.side_effect=send
    monkeypatch.setattr(quiz_service,'QUESTION_DELAY',0)
    await quiz_service.publish_quiz(bot,s,123)
    assert bot.send_poll.await_count==1
    assert db.load_session('quiz').status==SessionStatus.CANCELLED
    bot.send_message.assert_not_called()


def test_legacy_sqlite_migration_preserves_existing_records(tmp_path,monkeypatch):
    path=tmp_path/'legacy.db'
    conn=sqlite3.connect(path)
    conn.executescript('''CREATE TABLE quiz_sessions(session_id TEXT PRIMARY KEY,quiz_title TEXT NOT NULL,
        description TEXT NOT NULL,total_questions INTEGER NOT NULL,current_question INTEGER NOT NULL,
        status TEXT NOT NULL,started_at TEXT,completed_at TEXT);
        CREATE TABLE questions(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,
        question_index INTEGER NOT NULL,question_text TEXT NOT NULL,options TEXT NOT NULL,correct_option INTEGER NOT NULL,
        explanation TEXT,telegram_poll_id TEXT,telegram_message_id INTEGER,user_answer INTEGER,is_correct INTEGER,
        UNIQUE(session_id,question_index));
        INSERT INTO quiz_sessions VALUES('old','Old quiz','',1,1,'RUNNING','2026-10-20T06:00:00',NULL);
        INSERT INTO questions(session_id,question_index,question_text,options,correct_option,telegram_poll_id)
        VALUES('old',0,'Old Q?','["A","B"]',0,'old-poll');''')
    conn.commit();conn.close();monkeypatch.setattr(db,'DATABASE_PATH',str(path))
    db.init_db();db.init_db()
    assert db.load_session('old').questions[0].question_text=='Old Q?'
    assert db.record_answer('old','old-poll',1,False,123)
    assert len(export_wrong('today')['questions'])==1


@pytest.mark.asyncio
async def test_preview_sends_only_one_unscored_question():
    from app.handlers.callbacks import _handle_test
    pending={'quiz_title':'Preview','questions':[{'question':f'Q{i}?','options':['A','B'],'correct_option':0} for i in range(3)]}
    bot=SimpleNamespace(send_poll=AsyncMock(return_value=SimpleNamespace(poll=SimpleNamespace(id='preview'),message_id=99)))
    query=SimpleNamespace(from_user=SimpleNamespace(id=123456789),get_bot=lambda:bot,edit_message_text=AsyncMock())
    context=SimpleNamespace(user_data={'pending_quiz_data':pending})
    await _handle_test(query,context)
    assert bot.send_poll.await_count==1
    assert db.load_active_session() is None
    assert len(context.user_data['pending_quiz_data']['questions'])==3


@pytest.mark.asyncio
async def test_weekly_retry_prepares_separate_revision_and_keeps_original(monkeypatch):
    from app.handlers import tracking
    from app.services import mistakes
    running(1)
    db.record_answer('quiz','quiz-poll-0',1,False,123,datetime(2026,10,20,6,tzinfo=timezone.utc))
    db.complete_session('quiz')
    monkeypatch.setattr(tracking,'today',lambda:date(2026,10,26))
    monkeypatch.setattr(tracking,'export_wrong',lambda selector:mistakes.export_wrong(selector,date(2026,10,26)))
    update=SimpleNamespace(effective_user=SimpleNamespace(id=123456789),message=SimpleNamespace(reply_text=AsyncMock()))
    context=SimpleNamespace(user_data={})
    await tracking.retryweek_command(update,context)
    payload=context.user_data['pending_quiz_data']
    assert payload['quiz_kind']=='revision' and payload['study_date']=='2026-10-26'
    assert len(payload['questions'])==1
    assert db.load_session('quiz').wrong==1


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_export_database():
    from app.handlers.tracking import backup_command
    update=SimpleNamespace(effective_user=SimpleNamespace(id=777),message=SimpleNamespace(reply_text=AsyncMock(),reply_document=AsyncMock()))
    await backup_command(update,SimpleNamespace())
    update.message.reply_document.assert_not_called()
    assert 'Unauthorized' in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_registered_commands_include_manual_sync_and_retry():
    from app.bot import build_application
    application=build_application()
    commands={command for handlers in application.handlers.values() for handler in handlers for command in getattr(handler,'commands',[])}
    assert {'sync','wrong','retryweek','topic','notion_setup','backup','plan','result'} <= commands
    await application.bot.shutdown()
