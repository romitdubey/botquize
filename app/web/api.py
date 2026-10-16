"""Same-origin API for the mobile study site. No Telegram lifecycle on cold starts."""
import copy
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from app.config import BOT_TOKEN, WEBHOOK_SECRET
from app.services.planner import plan_rows
from app.web.store import Store
from app.web.accounts import content_visible
from app.web.daily import scheduled_day, today_topic, require_today, release_day, is_released
from app.web.domain import (now, iso, parsed, today, visible_quiz, question_public, finish,
                           mistakes, monday_window, TZ, practice_clock, reconcile_attempt)

app=FastAPI(title='Life Science Study', docs_url=None, redoc_url=None)
store=Store()
logging.getLogger('httpx').setLevel(logging.WARNING)

@app.exception_handler(httpx.HTTPError)
async def connection_error(request, exc):
    return JSONResponse({'detail':'Connection interrupted. Please try again.'},status_code=503)

@app.middleware('http')
async def private_responses(request, call_next):
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    return response

async def learner(request: Request):
    auth=request.headers.get('Authorization','')
    if not auth.startswith('Bearer '): raise HTTPException(401,'Please sign in.')
    url=os.getenv('SUPABASE_URL','').rstrip('/')
    key=os.getenv('SUPABASE_ANON_KEY','') or os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
    if not url or not key: raise HTTPException(503,'Sign-in is not configured yet.')
    async with httpx.AsyncClient(timeout=15) as client:
        response=await client.get(url+'/auth/v1/user',headers={'Authorization':auth,'apikey':key})
    if response.status_code!=200: raise HTTPException(401,'Your session expired. Please sign in again.')
    user=response.json()
    allowed={s.strip().lower() for s in os.getenv('STUDY_ALLOWED_EMAILS','').split(',') if s.strip()}
    if not allowed or user.get('email','').lower() not in allowed:
        raise HTTPException(403,'This private study space is only for its invited learners.')
    profile=(await store.state(user['id']))['data']
    user['account_alias']=profile.get('account_alias')
    mentor=os.getenv('STUDY_MENTOR_EMAIL','').strip().lower()
    learner_id=os.getenv('STUDY_LEARNER_ID','').strip()
    if mentor and user.get('email','').lower()==mentor and user.get('account_alias')!='me':
        if not learner_id: raise HTTPException(503,'Mentor access needs the learner account ID.')
        user={**user,'viewer_id':user['id'],'id':learner_id,'read_only':True}
    return user

async def participant(user=Depends(learner)):
    if user.get('read_only'): raise HTTPException(403,'Mentor access is read-only.')
    return user

async def weekly(user_id, data):
    start,end,monday=monday_window(today())
    # One immutable weekly snapshot per learner. No cron required.
    quiz_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'study-weekly:{user_id}:{monday}'))
    existing=await store.quizzes(id='eq.'+quiz_id)
    if existing: return
    wrong=mistakes(data,start,end)
    if not wrong: return
    await store.put_quiz({'id':quiz_id,'study_date':monday.isoformat(),
        'topic':'Monday mistake retry','description':f'Mistakes from {start:%d %b}–{(end-timedelta(days=1)):%d %b}',
        'status':'open','kind':'weekly','owner_id':user_id,
        'duration_seconds':min(21600,max(600,len(wrong)*90)),
        'questions':[{k:v for k,v in q.items() if k not in ('your_answer','times_wrong','last_wrong')} for q in wrong]})

async def reconcile(user_id):
    stamp=now()
    def action(data):
        for attempt in data.get('attempts',{}).values():
            reconcile_attempt(attempt,stamp)
        return copy.deepcopy(data)
    return await store.mutate(user_id,action)

@app.get('/api/config')
async def config():
    return {'supabase_url':os.getenv('SUPABASE_URL',''),
        'supabase_anon_key':os.getenv('SUPABASE_ANON_KEY',''),
        'configured':bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_ANON_KEY') and os.getenv('SUPABASE_SERVICE_ROLE_KEY') and os.getenv('STUDY_ALLOWED_EMAILS'))}

@app.get('/api/dashboard')
async def dashboard(user=Depends(learner)):
    data=await reconcile(user['id'])
    await weekly(user['id'],data)
    quizzes=await store.quizzes()
    quizzes=[q for q in quizzes if content_visible(q,user) and is_released(q,today())]
    attempts=[{k:v for k,v in a.items() if k not in ('questions','answers','flags')} | {'count':len(a['questions'])}
              for a in data.get('attempts',{}).values()]
    schedule=[{k:v for k,v in r.items() if k not in ('pages','page_start','page_end','key','week')} for r in plan_rows()]
    return {'user':{'email':user.get('email'),'id':user['id'],'name':'Romit' if user.get('account_alias')=='me' else 'Vishu','account_alias':user.get('account_alias'),'read_only':user.get('read_only',False)}, 'today':today().isoformat(),
        'schedule':schedule,'days':data.get('days',{}),
        'quizzes':[visible_quiz(q) | {'release_date':release_day(q).isoformat()} for q in quizzes], 'attempts':attempts,
        'mistake_count':len(mistakes(data))}

@app.get('/api/days/{day}')
async def day_detail(day:str,user=Depends(learner)):
    row=scheduled_day(day)
    if day>today().isoformat():raise HTTPException(403,'This study day opens on its scheduled date.')
    notes=[n for n in await store.notes(day) if content_visible(n,user)]
    urls=await store.signed_urls('study-notes',[n['path'] for n in notes])
    notes=[{k:v for k,v in n.items() if k!='path'} | {'url':urls.get(n['path'],'')} for n in notes]
    banks=await store.quizzes(study_date='eq.'+day)
    quizzes=[visible_quiz(q) | {'release_date':release_day(q).isoformat(),'available':is_released(q,today())}
             for q in banks if q['status']=='open' and content_visible(q,user)]
    return {'day':row,'notes':notes,'quizzes':quizzes,'editable':day==today().isoformat() and not user.get('read_only')}

class DayUpdate(BaseModel):
    studied: bool

@app.put('/api/days/{day}')
async def update_day(day:str, payload:DayUpdate,user=Depends(participant)):
    require_today(day,today())
    def action(data):
        record=data.setdefault('days',{}).setdefault(day,{})
        record['studied']=payload.studied
        return record
    return await store.mutate(user['id'],action)

class TimerUpdate(BaseModel):
    action: str
    topic: str=Field(default='',max_length=500)

@app.post('/api/timer')
async def timer(payload:TimerUpdate,user=Depends(participant)):
    raise HTTPException(410,'Study timers have been removed. Practice time is saved inside each quiz.')

async def accessible_quiz(quiz_id,user):
    quiz=await store.quiz(quiz_id)
    if not is_released(quiz,today()) or not content_visible(quiz,user):
        raise HTTPException(403,'This test has not been opened yet.')
    return quiz

async def present_attempt(attempt):
    result=copy.deepcopy(attempt)
    if not result.get('submitted_at'): result['questions']=[question_public(q) for q in result['questions']]
    urls=await store.image_urls([q['image_path'] for q in result['questions'] if q.get('image_path')])
    for q in result['questions']:
        if q.get('image_path'): q['image_url']=urls.get(q['image_path'],'')
    return result

@app.post('/api/quizzes/{quiz_id}/start')
async def start_attempt(quiz_id:str,user=Depends(participant)):
    quiz=await accessible_quiz(quiz_id,user)
    stamp=now(); attempt_id=str(uuid.uuid4())
    def action(data):
        attempts=data.setdefault('attempts',{})
        for old in attempts.values():reconcile_attempt(old,stamp)
        matching=[a for a in attempts.values() if a['quiz_id']==quiz_id]
        if matching:
            return copy.deepcopy(next((a for a in matching if not a.get('submitted_at')),matching[-1]))
        for old in attempts.values():
            if not old.get('submitted_at'):
                if old.get('kind')=='pyq':raise HTTPException(409,'Your full exam is running. Finish it before opening another quiz.')
                practice_clock(old,stamp,pause=True)
        record={'id':attempt_id,'quiz_id':quiz_id,'topic':quiz['topic'],'kind':quiz['kind'],
            'study_date':quiz['study_date'],'started_at':iso(stamp),
            'deadline':iso(stamp+timedelta(seconds=10800)) if quiz['kind']=='pyq' else None,
            'elapsed_seconds':0,'running_since':iso(stamp) if quiz['kind']!='pyq' else None,'heartbeat_at':iso(stamp),
            'questions':copy.deepcopy(quiz['questions']),'answers':{},'flags':[],'submitted_at':None}
        attempts[attempt_id]=record
        return copy.deepcopy(record)
    return await present_attempt(await store.mutate(user['id'],action))

@app.get('/api/attempts/{attempt_id}')
async def get_attempt(attempt_id:str,user=Depends(learner)):
    data=await reconcile(user['id'])
    attempt=data.get('attempts',{}).get(attempt_id)
    if not attempt: raise HTTPException(404,'Attempt not found.')
    return await present_attempt(attempt)

class AnswerUpdate(BaseModel):
    index: int=Field(ge=0)
    answer: int | None=None
    flagged: bool=False

@app.put('/api/attempts/{attempt_id}/answer')
async def save_answer(attempt_id:str,payload:AnswerUpdate,user=Depends(participant)):
    stamp=now()
    def action(data):
        a=data.get('attempts',{}).get(attempt_id)
        if not a: raise HTTPException(404,'Attempt not found.')
        reconcile_attempt(a,stamp)
        if a.get('submitted_at'): return {'submitted':True}
        if a.get('kind')=='pyq' and stamp>=parsed(a['deadline']):
            finish(a,parsed(a['deadline']));return {'submitted':True}
        if a.get('kind')!='pyq' and not a.get('running_since'):raise HTTPException(409,'Resume your quiz before answering.')
        if payload.index>=len(a['questions']): raise HTTPException(400,'Invalid question number.')
        if payload.answer is not None and not 0<=payload.answer<len(a['questions'][payload.index]['options']):
            raise HTTPException(400,'Invalid answer.')
        key=str(payload.index)
        if payload.answer is None: a['answers'].pop(key,None)
        else: a['answers'][key]=payload.answer
        flags=set(a['flags'])
        if payload.flagged: flags.add(payload.index)
        else: flags.discard(payload.index)
        a['flags']=sorted(flags)
        return {'saved':True}
    return await store.mutate(user['id'],action)

@app.post('/api/attempts/{attempt_id}/submit')
async def submit_attempt(attempt_id:str,user=Depends(participant)):
    stamp=now()
    def action(data):
        a=data.get('attempts',{}).get(attempt_id)
        if not a: raise HTTPException(404,'Attempt not found.')
        finish(a,min(stamp,parsed(a['deadline'])) if a.get('kind')=='pyq' else stamp)
        return copy.deepcopy(a)
    return await present_attempt(await store.mutate(user['id'],action))

class ClockUpdate(BaseModel):
    action:str

@app.post('/api/attempts/{attempt_id}/clock')
async def attempt_clock(attempt_id:str,payload:ClockUpdate,user=Depends(participant)):
    if payload.action not in ('pause','resume','heartbeat'):raise HTTPException(400,'Invalid clock action.')
    stamp=now()
    def action(data):
        attempts=data.get('attempts',{});a=attempts.get(attempt_id)
        if not a:raise HTTPException(404,'Attempt not found.')
        if a.get('kind')=='pyq':raise HTTPException(400,'Full exams cannot be paused. The three-hour clock continues.')
        reconcile_attempt(a,stamp)
        if a.get('submitted_at'):return copy.deepcopy(a)
        if payload.action=='resume':
            for other in attempts.values():
                if other is a or other.get('submitted_at'):continue
                reconcile_attempt(other,stamp)
                if other.get('kind')=='pyq' and not other.get('submitted_at'):raise HTTPException(409,'Finish your running full exam first.')
                practice_clock(other,stamp,pause=True)
            if not a.get('running_since'):a.update(running_since=iso(stamp),heartbeat_at=iso(stamp))
        else:practice_clock(a,stamp,pause=payload.action=='pause')
        return copy.deepcopy(a)
    return await present_attempt(await store.mutate(user['id'],action))

@app.get('/api/mistakes')
async def wrong_answers(user=Depends(learner)):
    data=await reconcile(user['id'])
    questions=mistakes(data)
    urls=await store.image_urls([q['image_path'] for q in questions if q.get('image_path')])
    for q in questions:
        if q.get('image_path'): q['image_url']=urls.get(q['image_path'],'')
    return {'questions':questions}

@app.post('/api/mistakes/retry')
async def retry_mistakes(user=Depends(participant)):
    data=await reconcile(user['id']); questions=mistakes(data)
    if not questions: raise HTTPException(400,'No mistakes to retry yet.')
    # A fresh immutable bank, shared only with its learner.
    quiz={'id':str(uuid.uuid4()),'study_date':today().isoformat(),'topic':'My mistake practice',
        'description':'A fresh attempt at your saved mistakes.','kind':'weekly','status':'open',
        'owner_id':user['id'],'duration_seconds':min(21600,max(600,len(questions)*90)),
        'questions':[{k:v for k,v in q.items() if k not in ('your_answer','times_wrong','last_wrong')} for q in questions]}
    await store.put_quiz(quiz)
    return {'id':quiz['id']}

@app.post('/api/telegram/webhook')
@app.post('/webhook')
async def telegram_webhook(request:Request):
    if not BOT_TOKEN or not secrets.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token',''),WEBHOOK_SECRET):
        raise HTTPException(403,'Forbidden')
    from app.web.telegram import handle_update
    await handle_update(await request.json(),store)
    return {'ok':True}

@app.get('/api/health')
async def health(): return {'status':'ok'}

# Local single-process preview; Vercel serves the same built files as static assets.
WEB_ROOT=Path(__file__).resolve().parents[2]/'web'
@app.get('/')
async def index(): return FileResponse(WEB_ROOT/'index.html')
@app.get('/{asset}')
async def asset(asset:str):
    if asset not in ('app.js','style.css','demo.js','schedule.js','favicon.svg','sample-notes.svg','sample-diagram.svg'): raise HTTPException(404)
    return FileResponse(WEB_ROOT/asset)
