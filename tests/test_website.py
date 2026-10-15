"""Website contracts with a deterministic private store; no cloud writes or Telegram sends."""
import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import HTTPException
from app.web import api, domain
from app.web.domain import validate_bank

class MemoryStore:
    def __init__(self):self.banks={};self.states={};self.admins={};self.lock=asyncio.Lock();self.images={}
    async def quizzes(self,**filters):
        result=list(self.banks.values())
        for key,val in filters.items():
            if key in ('id','kind'):result=[q for q in result if str(q[key])==val.removeprefix('eq.')]
        return copy.deepcopy(result)
    async def quiz(self,key):
        if key not in self.banks:raise HTTPException(404,'Test not found.')
        return copy.deepcopy(self.banks[key])
    async def put_quiz(self,row):self.banks.setdefault(row['id'],copy.deepcopy(row))
    async def update_quiz(self,key,fields):self.banks[key].update(copy.deepcopy(fields))
    async def state(self,key,admin=False):return {'data':copy.deepcopy((self.admins if admin else self.states).get(key,{})),'version':0}
    async def mutate(self,key,action,admin=False):
        async with self.lock:
            states=self.admins if admin else self.states
            data=copy.deepcopy(states.get(key,{}));result=action(data);states[key]=data
            return copy.deepcopy(result)
    async def image_urls(self,paths):return {path:'https://images.test/'+path for path in paths}
    async def upload_image(self,path,content,mime):self.images[path]=(content,mime);return path

@pytest.fixture
def cloud(monkeypatch):
    store=MemoryStore();monkeypatch.setattr(api,'store',store)
    async def identity(): return {'id':'learner-1','email':'friend@example.com'}
    api.app.dependency_overrides[api.learner]=identity
    yield store
    api.app.dependency_overrides.clear()

@pytest.fixture
def bank():
    return validate_bank({'questions':[{'question':'Long question?','options':['Alpha','Beta','Gamma'],'correct_option':1,'explanation':'A full explanation.'},{'question':'Second?','options':['Yes','No'],'correct_option':0}]},'Enzymes','2026-10-16')

def connection():return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test')

def test_web_bank_preserves_full_text_and_stable_image_identity():
    data={'questions':[{'question':'Q'*2000,'options':['A'*300,'B'],'correct_option':0,'explanation':'E'*1000}]}
    one=validate_bank(data,'Topic','2026-10-16');two=validate_bank(data,'Topic','2026-10-16')
    assert one['id']==two['id'];assert len(one['questions'][0]['explanation'])==1000
    assert len(one['questions'][0]['question'])==2000 and len(one['questions'][0]['options'][0])==300
    data['questions'][0]['image_url']='https://images.test/diagram.png'
    three=validate_bank(data,'Topic','2026-10-16')
    assert three['questions'][0]['id']==one['questions'][0]['id'] and three['id']!=one['id']

@pytest.mark.parametrize('value',[True,-1,2,'0',None])
def test_bank_rejects_invalid_answer_keys(value):
    with pytest.raises(HTTPException):validate_bank({'questions':[{'question':'Q','options':['A','B'],'correct_option':value}]},'T','2026-10-16')

@pytest.mark.asyncio
async def test_draft_private_keys_hidden_and_server_grades_idempotently(cloud,bank):
    await cloud.put_quiz(bank)
    async with connection() as c:
        assert (await c.get('/api/dashboard')).json()['quizzes']==[]
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).status_code==403
        await cloud.update_quiz(bank['id'],{'status':'open'})
        dash=(await c.get('/api/dashboard')).json();assert dash['quizzes'][0]['count']==2
        assert 'questions' not in dash['quizzes'][0]
        assert not any('page_start' in r or 'pages' in r for r in dash['schedule'])
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        assert all('correct_option' not in q and 'explanation' not in q for q in a['questions'])
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).json()['id']==a['id']
        await c.put(f'/api/attempts/{a["id"]}/answer',json={'index':0,'answer':0,'flagged':True})
        await c.put(f'/api/attempts/{a["id"]}/answer',json={'index':1,'answer':0})
        done=(await c.post(f'/api/attempts/{a["id"]}/submit')).json()
        assert (done['correct'],done['wrong'],done['skipped'])==(1,1,0)
        assert done['questions'][0]['correct_option']==1
        again=(await c.post(f'/api/attempts/{a["id"]}/submit')).json();assert done==again
        await c.put(f'/api/attempts/{a["id"]}/answer',json={'index':0,'answer':1})
        assert cloud.states['learner-1']['attempts'][a['id']]['answers']['0']==0
        wrong=(await c.get('/api/mistakes')).json()['questions'];assert len(wrong)==1 and wrong[0]['explanation']
        retry=(await c.post('/api/mistakes/retry')).json()
        assert retry['id']!=bank['id'] and len(cloud.banks[retry['id']]['questions'])==1
        assert cloud.states['learner-1']['attempts'][a['id']]['wrong']==1

@pytest.mark.asyncio
async def test_server_deadline_rejects_late_answers_and_reconciles(cloud,bank,monkeypatch):
    stamp=datetime(2026,10,20,6,tzinfo=timezone.utc);monkeypatch.setattr(api,'now',lambda:stamp)
    bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        stamp+=timedelta(seconds=bank['duration_seconds']+1)
        result=await c.put(f'/api/attempts/{a["id"]}/answer',json={'index':0,'answer':1})
        assert result.json()=={'submitted':True}
        a=(await c.get('/api/attempts/'+a['id'])).json();assert a['correct']==0 and a['skipped']==2

@pytest.mark.asyncio
async def test_second_learner_cannot_read_attempt_or_private_retry(cloud,bank):
    bank.update(status='open',owner_id='someone-else');await cloud.put_quiz(bank)
    async with connection() as c:
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).status_code==403
        assert (await c.get('/api/attempts/someone-else')).status_code==404
        assert (await c.get('/api/dashboard')).json()['quizzes']==[]

@pytest.mark.asyncio
async def test_timer_saved_across_devices_caps_disconnect_and_splits_midnight(cloud,monkeypatch):
    stamp=datetime(2026,10,20,18,29,30,tzinfo=timezone.utc);monkeypatch.setattr(api,'now',lambda:stamp)
    async with connection() as c:
        await c.post('/api/timer',json={'action':'start','topic':'Enzymes'})
        stamp+=timedelta(seconds=60)
        res=(await c.post('/api/timer',json={'action':'heartbeat'})).json()
        assert res['days']['2026-10-20']['seconds']==30
        assert res['days']['2026-10-21']['seconds']==30
        stamp+=timedelta(seconds=3600)
        dash=(await c.get('/api/dashboard')).json()
        assert dash['days']['2026-10-21']['seconds']==120 and not dash['timer']['running_since']
        # A fresh request/device sees the same saved total; pause does not double count.
        res=(await c.post('/api/timer',json={'action':'pause'})).json()
        assert res['days']==dash['days']

@pytest.mark.asyncio
async def test_monday_retry_excludes_weekend_and_keeps_snapshot(cloud,bank,monkeypatch):
    monkeypatch.setattr(api,'today',lambda:date(2026,10,26))
    def attempt(id,day,questions):return {'id':id,'submitted_at':f'2026-10-{day}T12:00:00+05:30','questions':questions,'answers':{'0':0},'correct':0,'wrong':1,'skipped':0}
    q=bank['questions'][0];other=bank['questions'][1];other['correct_option']=1
    cloud.states['learner-1']={'attempts':{'a':attempt('a','19',[q]),'b':attempt('b','20',[q]),'c':attempt('c','24',[other])}}
    async with connection() as c:
        await c.get('/api/dashboard');await c.get('/api/dashboard')
    weekly=[q for q in cloud.banks.values() if q['kind']=='weekly']
    assert len(weekly)==1 and len(weekly[0]['questions'])==1 and weekly[0]['questions'][0]['id']==q['id']
    assert len(cloud.states['learner-1']['attempts'])==3

@pytest.mark.asyncio
async def test_telegram_private_admin_upload_open_image_and_no_polls(cloud,monkeypatch):
    from app.web import telegram as tg
    calls=[]
    async def send(method,body=None,files=None):calls.append((method,body));return {}
    monkeypatch.setattr(tg,'telegram',send)
    async def update(text=None,**extra):
        await tg.handle_update({'update_id':4,'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},cloud)
    await update('/topic 2026-10-16 | Enzymes')
    raw=b'{"questions":[{"question":"Diagram?","options":["A","B"],"correct_option":0,"explanation":"Full explanation"}]}'
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=raw))
    await update(document={'file_id':'file','file_name':'questions.json','file_size':len(raw)})
    assert len(cloud.banks)==1;bank=next(iter(cloud.banks.values()));assert bank['status']=='draft'
    await update(document={'file_id':'file','file_name':'questions.json','file_size':len(raw)})
    assert len(cloud.banks)==1
    await update('/image 1')
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'\x89PNG\r\n\x1a\ncontent'))
    await update(photo=[{'file_id':'photo','file_unique_id':'photo-unique'}])
    assert bank['id']+'/1-photo-unique.png' in cloud.images
    await update('/open');assert cloud.banks[bank['id']]['status']=='open'
    assert cloud.banks[bank['id']]['questions'][0]['image_path']
    assert all(method=='sendMessage' for method,_ in calls)
    assert all(body['chat_id']==123456789 for _,body in calls)
    calls.clear()
    await tg.handle_update({'message':{'from':{'id':999},'chat':{'id':999,'type':'private'},'text':'/open'}},cloud)
    assert not calls

@pytest.mark.asyncio
async def test_webhook_rejects_unverified_delivery():
    async with connection() as c:
        assert (await c.post('/api/telegram/webhook',json={'update_id':1})).status_code==403

@pytest.mark.asyncio
async def test_unauthenticated_cannot_read_dashboard():
    api.app.dependency_overrides.clear()
    async with connection() as c:
        r=await c.get('/api/dashboard');assert r.status_code==401
        assert r.headers['cache-control']=='no-store'

@pytest.mark.asyncio
async def test_config_never_exposes_service_key(monkeypatch):
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY','never-in-browser')
    monkeypatch.setenv('SUPABASE_ANON_KEY','public-key')
    async with connection() as c:
        r=await c.get('/api/config');assert 'never-in-browser' not in r.text;assert r.json()['supabase_anon_key']=='public-key'

@pytest.mark.asyncio
async def test_mentor_can_read_but_cannot_change_learner_progress(cloud):
    async def mentor():return {'id':'learner-1','email':'mentor@example.com','read_only':True}
    api.app.dependency_overrides[api.learner]=mentor
    async with connection() as c:
        assert (await c.get('/api/dashboard')).json()['user']['read_only']
        assert (await c.put('/api/days/2026-10-16',json={'studied':True})).status_code==403
        assert (await c.post('/api/timer',json={'action':'start'})).status_code==403
        assert (await c.post('/api/mistakes/retry')).status_code==403

@pytest.mark.asyncio
async def test_auth_checks_real_user_allowlist_and_maps_mentor(monkeypatch):
    from starlette.requests import Request
    monkeypatch.setenv('SUPABASE_URL','https://project.test');monkeypatch.setenv('SUPABASE_ANON_KEY','public')
    monkeypatch.setenv('STUDY_ALLOWED_EMAILS','friend@example.com,mentor@example.com')
    monkeypatch.setenv('STUDY_MENTOR_EMAIL','mentor@example.com');monkeypatch.setenv('STUDY_LEARNER_ID','friend-uuid')
    request=Request({'type':'http','headers':[(b'authorization',b'Bearer user-jwt')]})
    email='stranger@example.com'
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,url,headers):
            assert url=='https://project.test/auth/v1/user'
            assert headers['Authorization']=='Bearer user-jwt'
            return httpx.Response(200,json={'id':'mentor-uuid','email':email})
    monkeypatch.setattr(api.httpx,'AsyncClient',Client)
    with pytest.raises(HTTPException) as error:await api.learner(request)
    assert error.value.status_code==403
    email='mentor@example.com';user=await api.learner(request)
    assert user['id']=='friend-uuid' and user['viewer_id']=='mentor-uuid' and user['read_only']

@pytest.mark.asyncio
async def test_store_compare_and_swap_retries_conflict_without_losing_data(monkeypatch):
    from app.web.store import Store
    store=Store();current={'data':{'count':1},'version':1};calls=0
    async def state(user_id,admin=False):return copy.deepcopy(current)
    async def request(method,resource,params=None,body=None,headers=None):
        nonlocal calls
        calls+=1
        if calls==1:
            current.update(data={'count':2},version=2)
            return []
        assert params['version']=='eq.2'
        current.update(copy.deepcopy(body));return [copy.deepcopy(current)]
    monkeypatch.setattr(store,'state',state);monkeypatch.setattr(store,'request',request)
    def increase(data):data['count']+=1;return data['count']
    assert await store.mutate('learner',increase)==3
    assert current['data']['count']==3 and current['version']==3

@pytest.mark.asyncio
async def test_concurrent_submissions_grade_once_and_closed_test_remains_reviewable(cloud,bank):
    bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        await cloud.update_quiz(bank['id'],{'status':'closed'})
        assert (await c.get('/api/attempts/'+a['id'])).status_code==200
        one,two=await asyncio.gather(c.post(f'/api/attempts/{a["id"]}/submit'),c.post(f'/api/attempts/{a["id"]}/submit'))
        assert one.json()==two.json() and one.json()['skipped']==2
        assert len(cloud.states['learner-1']['attempts'])==1

@pytest.mark.asyncio
async def test_diagrams_signed_in_bulk_and_never_lost_from_attempt(cloud,bank):
    bank['status']='open';bank['questions'][0]['image_path']='quiz/1.png';await cloud.put_quiz(bank)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        assert a['questions'][0]['image_url']=='https://images.test/quiz/1.png'
        assert 'correct_option' not in a['questions'][0]

@pytest.mark.asyncio
async def test_default_legacy_entrypoint_is_website_without_starting_telegram(monkeypatch):
    # Reload only the compatibility alias; no startup/lifespan/network is run.
    import importlib
    from app import bot
    monkeypatch.delenv('LEGACY_TELEGRAM_POLLS',raising=False)
    importlib.reload(bot)
    assert bot.fastapi_app is api.app
    monkeypatch.setenv('LEGACY_TELEGRAM_POLLS','true')
    importlib.reload(bot)


def test_preview_schedule_matches_canonical_plan():
    import json
    from pathlib import Path
    from app.services.planner import plan_rows
    text=Path('web/schedule.js').read_text().split('export default ',1)[1].strip().rstrip(';')
    preview=json.loads(text)
    canonical=[{k:v for k,v in row.items() if k in ('date','topic','part','kind')} for row in plan_rows()]
    assert preview==canonical
