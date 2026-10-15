"""SQLite storage for quizzes, attributed answers, mistakes and sync identities."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from app.config import DATABASE_PATH
from app.models import HistoryEntry, QuizQuestion, QuizSession, SessionStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_db_path() -> str:
    os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)
    return DATABASE_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(get_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                session_id TEXT PRIMARY KEY, quiz_title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', total_questions INTEGER NOT NULL,
                current_question INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY',
                started_at TEXT, completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES quiz_sessions(session_id),
                question_index INTEGER NOT NULL, question_text TEXT NOT NULL,
                options TEXT NOT NULL, correct_option INTEGER NOT NULL, explanation TEXT,
                telegram_poll_id TEXT, telegram_message_id INTEGER, user_answer INTEGER,
                is_correct INTEGER, UNIQUE(session_id, question_index)
            );
            CREATE TABLE IF NOT EXISTS history (
                session_id TEXT PRIMARY KEY, quiz_title TEXT NOT NULL, total_questions INTEGER NOT NULL,
                attempted INTEGER NOT NULL, correct INTEGER NOT NULL, wrong INTEGER NOT NULL,
                accuracy REAL NOT NULL, completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notion_links (
                target TEXT NOT NULL, local_key TEXT NOT NULL, page_id TEXT NOT NULL,
                PRIMARY KEY(target, local_key)
            );
        ''')
        migrations = {
            'quiz_sessions': {'topic': "TEXT NOT NULL DEFAULT ''", 'study_date': "TEXT NOT NULL DEFAULT ''",
                              'quiz_kind': "TEXT NOT NULL DEFAULT 'book'", 'learner_user_id': 'INTEGER',
                              'created_at': "TEXT NOT NULL DEFAULT ''"},
            'questions': {'image_url': 'TEXT', 'source_id': "TEXT NOT NULL DEFAULT ''",
                          'answered_at': 'TEXT', 'answer_user_id': 'INTEGER', 'source_topic': "TEXT NOT NULL DEFAULT ''"},
        }
        for table, columns in migrations.items():
            existing = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        # Preserve old quizzes while filling stable identities introduced by tracking.
        for row in conn.execute("SELECT * FROM questions WHERE source_id='' ").fetchall():
            identity=question_identity(QuizQuestion(row['question_index'],row['question_text'],
                json.loads(row['options']),row['correct_option'],image_url=row['image_url']))
            conn.execute('UPDATE questions SET source_id=? WHERE id=?',(identity,row['id']))
        conn.execute("UPDATE quiz_sessions SET topic=quiz_title WHERE topic='' ")
        conn.execute("UPDATE quiz_sessions SET created_at=COALESCE(started_at,completed_at,?) WHERE created_at='' ",(_iso(utcnow()),))
        conn.execute("UPDATE questions SET source_topic=(SELECT topic FROM quiz_sessions WHERE session_id=questions.session_id) WHERE source_topic='' ")
        conn.execute('CREATE INDEX IF NOT EXISTS poll_lookup ON questions(telegram_poll_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS answers_by_date ON questions(answered_at)')


def question_identity(q: QuizQuestion) -> str:
    payload = json.dumps([q.question_text.strip(), q.options, q.correct_option, q.image_url], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def save_session(session: QuizSession) -> None:
    with get_conn() as conn:
        conn.execute('''INSERT INTO quiz_sessions
            (session_id,quiz_title,description,total_questions,current_question,status,started_at,completed_at,
             topic,study_date,quiz_kind,learner_user_id,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                quiz_title=excluded.quiz_title,description=excluded.description,
                current_question=excluded.current_question,status=excluded.status,
                started_at=excluded.started_at,completed_at=excluded.completed_at,
                topic=excluded.topic,study_date=excluded.study_date
        ''', (session.session_id,session.quiz_title,session.description,session.total_questions,
              session.current_question,session.status.value,_iso(session.started_at),_iso(session.completed_at),
              session.topic,session.study_date,session.quiz_kind,session.learner_user_id,_iso(session.created_at)))
        for q in session.questions:
            q.source_id = q.source_id or question_identity(q)
            conn.execute('''INSERT INTO questions
                (session_id,question_index,question_text,options,correct_option,explanation,image_url,source_id,
                 telegram_poll_id,telegram_message_id,user_answer,is_correct,answered_at,answer_user_id,source_topic)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id,question_index) DO NOTHING''',
                (session.session_id,q.question_index,q.question_text,json.dumps(q.options,ensure_ascii=False),
                 q.correct_option,q.explanation,q.image_url,q.source_id,q.telegram_poll_id,q.telegram_message_id,
                 q.user_answer,None if q.is_correct is None else int(q.is_correct),_iso(q.answered_at),q.answer_user_id,q.source_topic))


def _iso(dt):
    return dt.isoformat() if dt else None


def _dt(value):
    return datetime.fromisoformat(value) if value else None


def _row_to_session(conn, row):
    questions=[]
    for q in conn.execute('SELECT * FROM questions WHERE session_id=? ORDER BY question_index',(row['session_id'],)):
        questions.append(QuizQuestion(question_index=q['question_index'],question_text=q['question_text'],
            options=json.loads(q['options']),correct_option=q['correct_option'],explanation=q['explanation'],
            image_url=q['image_url'],source_id=q['source_id'],source_topic=q['source_topic'],telegram_poll_id=q['telegram_poll_id'],
            telegram_message_id=q['telegram_message_id'],user_answer=q['user_answer'],
            is_correct=None if q['is_correct'] is None else bool(q['is_correct']),
            answered_at=_dt(q['answered_at']),answer_user_id=q['answer_user_id']))
    return QuizSession(session_id=row['session_id'],quiz_title=row['quiz_title'],description=row['description'],
        total_questions=row['total_questions'],current_question=row['current_question'],status=SessionStatus(row['status']),
        questions=questions,started_at=_dt(row['started_at']),completed_at=_dt(row['completed_at']),
        topic=row['topic'],study_date=row['study_date'],quiz_kind=row['quiz_kind'],
        learner_user_id=row['learner_user_id'],created_at=_dt(row['created_at']) or utcnow())


def load_session(session_id: str) -> Optional[QuizSession]:
    with get_conn() as conn:
        row=conn.execute('SELECT * FROM quiz_sessions WHERE session_id=?',(session_id,)).fetchone()
        return _row_to_session(conn,row) if row else None


def load_active_session() -> Optional[QuizSession]:
    with get_conn() as conn:
        row=conn.execute("SELECT * FROM quiz_sessions WHERE status IN ('READY','RUNNING') ORDER BY rowid DESC LIMIT 1").fetchone()
        return _row_to_session(conn,row) if row else None


def load_latest_session() -> Optional[QuizSession]:
    with get_conn() as conn:
        row=conn.execute("SELECT * FROM quiz_sessions WHERE quiz_kind != 'test' ORDER BY rowid DESC LIMIT 1").fetchone()
        return _row_to_session(conn,row) if row else None


def list_sessions() -> list[QuizSession]:
    with get_conn() as conn:
        return [_row_to_session(conn,row) for row in conn.execute('SELECT * FROM quiz_sessions ORDER BY rowid')]


def update_session_status(session_id, status, current_question=None, completed_at=None):
    values={'status':status.value}
    if current_question is not None: values['current_question']=current_question
    if completed_at is not None: values['completed_at']=_iso(completed_at)
    with get_conn() as conn:
        conn.execute('UPDATE quiz_sessions SET '+','.join(f'{k}=?' for k in values)+' WHERE session_id=?',
                     (*values.values(),session_id))


def update_question_poll(session_id,question_index,poll_id,message_id):
    with get_conn() as conn:
        conn.execute('UPDATE questions SET telegram_poll_id=?,telegram_message_id=? WHERE session_id=? AND question_index=?',
                     (poll_id,message_id,session_id,question_index))


def advance_current_question(session_id,new_index):
    with get_conn() as conn:
        conn.execute('UPDATE quiz_sessions SET current_question=? WHERE session_id=?',(new_index,session_id))


def record_answer(session_id,poll_id,user_answer,is_correct,user_id=None,answered_at=None) -> bool:
    """Bind an unassigned quiz to its first respondent and atomically record once."""
    with get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        s=conn.execute('SELECT status,learner_user_id FROM quiz_sessions WHERE session_id=?',(session_id,)).fetchone()
        if not s or s['status']!='RUNNING': return False
        if s['learner_user_id'] is not None and user_id!=s['learner_user_id']: return False
        if s['learner_user_id'] is None and user_id is not None:
            conn.execute('UPDATE quiz_sessions SET learner_user_id=? WHERE session_id=?',(user_id,session_id))
        row=conn.execute('''UPDATE questions SET user_answer=?,is_correct=?,answer_user_id=?,answered_at=?
            WHERE session_id=? AND telegram_poll_id=? AND user_answer IS NULL''',
            (user_answer,int(is_correct),user_id,_iso(answered_at or utcnow()),session_id,poll_id))
        return row.rowcount==1


def find_session_by_poll(poll_id):
    with get_conn() as conn:
        row=conn.execute('''SELECT q.session_id,q.question_index,q.correct_option FROM questions q
            JOIN quiz_sessions s ON q.session_id=s.session_id
            WHERE q.telegram_poll_id=? AND s.status='RUNNING' ''',(poll_id,)).fetchone()
        return tuple(row) if row else None


def complete_session(session_id) -> bool:
    """Exactly-once transition, including the history snapshot in one transaction."""
    with get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM quiz_sessions WHERE session_id=?',(session_id,)).fetchone()
        if not row or row['status']!='RUNNING': return False
        s=_row_to_session(conn,row)
        if s.current_question<s.total_questions or any(q.telegram_poll_id is None or q.user_answer is None for q in s.questions):
            return False
        s.completed_at=utcnow()
        conn.execute("UPDATE quiz_sessions SET status='COMPLETED',completed_at=? WHERE session_id=?",(_iso(s.completed_at),session_id))
        if s.quiz_kind!='test': _save_history(conn,s)
        return True


def _save_history(conn,s):
    conn.execute('''INSERT INTO history VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
        attempted=excluded.attempted,correct=excluded.correct,wrong=excluded.wrong,accuracy=excluded.accuracy''',
        (s.session_id,s.quiz_title,s.total_questions,s.attempted,s.correct,s.wrong,s.accuracy,_iso(s.completed_at or utcnow())))


def save_history(session):
    with get_conn() as conn: _save_history(conn,session)


def get_history(page=0,page_size=5):
    with get_conn() as conn:
        rows=conn.execute('SELECT * FROM history ORDER BY completed_at DESC LIMIT ? OFFSET ?',(page_size,max(0,page)*page_size))
        return [HistoryEntry(**{**dict(r),'completed_at':_dt(r['completed_at'])}) for r in rows]


def get_history_count():
    with get_conn() as conn: return conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]


def get_overall_stats():
    with get_conn() as conn:
        row=conn.execute('''SELECT COUNT(*) quizzes_completed,COALESCE(SUM(attempted),0) questions_attempted,
            COALESCE(SUM(correct),0) total_correct,COALESCE(SUM(wrong),0) total_wrong,
            COALESCE(MAX(accuracy),0) best_accuracy FROM history''').fetchone()
        result=dict(row); result['overall_accuracy']=round(result['total_correct']/result['questions_attempted']*100,2) if result['questions_attempted'] else 0.0
        return result


def wrong_questions_between(start: datetime,end: datetime,user_id=None):
    """Use actual answer time, not upload/study date, for weekly mistake sets."""
    with get_conn() as conn:
        rows=conn.execute('''SELECT q.*,s.topic,s.quiz_title,s.quiz_kind FROM questions q
            JOIN quiz_sessions s ON q.session_id=s.session_id
            WHERE q.is_correct=0 AND q.answered_at>=? AND q.answered_at<? AND s.quiz_kind!='test'
            AND (? IS NULL OR q.answer_user_id=?) ORDER BY q.answered_at,q.id''',
            (_iso(start),_iso(end),user_id,user_id))
        return [dict(r) for r in rows]


def set_setting(key,value):
    with get_conn() as conn:
        conn.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))


def get_setting(key,default=None):
    with get_conn() as conn:
        row=conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else default


def get_notion_link(target,key):
    with get_conn() as conn:
        row=conn.execute('SELECT page_id FROM notion_links WHERE target=? AND local_key=?',(target,key)).fetchone()
        return row['page_id'] if row else None


def set_notion_link(target,key,page_id):
    with get_conn() as conn:
        conn.execute('INSERT INTO notion_links VALUES (?,?,?) ON CONFLICT(target,local_key) DO UPDATE SET page_id=excluded.page_id',(target,key,page_id))
