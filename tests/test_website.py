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
    def __init__(self):self.note_rows={};self.banks={};self.states={};self.admins={};self.lock=asyncio.Lock();self.images={}
    async def quizzes(self,**filters):
        result=list(self.banks.values())
        for key,val in filters.items():
            if key in ('id','kind','study_date'):result=[q for q in result if str(q[key])==val.removeprefix('eq.')]
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
    async def attach_image(self,key,index,path):
        async with self.lock:self.banks[key]['questions'][index].update(image_path=path,image_url='')
    async def notes(self,day):return [copy.deepcopy(n) for n in self.note_rows.values() if n['study_date']==day]
    async def put_note(self,row):self.note_rows.setdefault(row['id'],copy.deepcopy(row))
    async def signed_urls(self,bucket,paths):return {p:'https://images.test/'+p for p in paths}
    async def upload_note(self,path,content,mime):self.images[path]=(content,mime);return path
    async def image_urls(self,paths):return {path:'https://images.test/'+path for path in paths}
    async def upload_image(self,path,content,mime):self.images[path]=(content,mime);return path

@pytest.fixture
def cloud(monkeypatch):
    store=MemoryStore();monkeypatch.setattr(api,'store',store)
    monkeypatch.setattr(api,'today',lambda:date(2026,10,21))
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
    bank['status']='open';bank['kind']='pyq';await cloud.put_quiz(bank)
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
async def test_practice_pause_resume_preserves_answers_and_active_time_across_days(cloud,bank,monkeypatch):
    stamp=datetime(2026,10,20,6,tzinfo=timezone.utc);monkeypatch.setattr(api,'now',lambda:stamp)
    bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json();path='/api/attempts/'+a['id']
        assert a['deadline'] is None
        await c.put(path+'/answer',json={'index':0,'answer':1})
        stamp+=timedelta(seconds=25)
        paused=(await c.post(path+'/clock',json={'action':'pause'})).json()
        assert paused['elapsed_seconds']==25 and not paused['running_since']
        stamp+=timedelta(days=4)
        saved=(await c.get(path)).json()
        assert not saved['submitted_at'] and saved['answers']=={'0':1} and saved['elapsed_seconds']==25
        assert (await c.put(path+'/answer',json={'index':1,'answer':0})).status_code==409
        await c.post(path+'/clock',json={'action':'resume'})
        stamp+=timedelta(seconds=20)
        done=(await c.post(path+'/submit')).json()
        assert done['elapsed_seconds']==45 and done['correct']==1 and 'score' not in done
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).json()['id']==a['id']

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

@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,expected',[
    (404,'PGRST205','Study tables are missing'),
    (401,'','backend database key was rejected'),
    (403,'42501','backend cannot access study tables'),
    (409,'23503','learner account ID'),
    (500,'','temporarily unavailable'),
])
async def test_storage_setup_errors_are_actionable_without_exposing_upstream_secrets(monkeypatch,status,code,expected):
    from app.web.store import Store
    client_type=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'code':code,'message':'upstream-private-secret'}))
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:client_type(transport=transport,**kwargs))
    store=Store();store.url='https://project.test';store.key='sb_secret_private'
    with pytest.raises(HTTPException) as error:
        await store.request('GET','study_learners')
    assert expected in error.value.detail
    assert 'upstream-private-secret' not in error.value.detail and store.key not in error.value.detail

@pytest.mark.asyncio
async def test_only_today_can_be_marked_studied(cloud):
    async with connection() as c:
        for day in ('2026-10-20','2026-10-22'):
            assert (await c.put('/api/days/'+day,json={'studied':True})).status_code==403
        response=await c.put('/api/days/2026-10-21',json={'studied':True})
        assert response.status_code==200 and response.json()['studied']
    assert set(cloud.states['learner-1']['days'])=={'2026-10-21'}

@pytest.mark.asyncio
async def test_study_timer_removed(cloud):
    async with connection() as c:
        assert (await c.post('/api/timer',json={'action':'start'})).status_code==410

@pytest.mark.asyncio
async def test_future_notes_locked_and_past_notes_read_only(cloud,bank):
    cloud.note_rows['note']={'id':'note','study_date':'2026-10-21','title':'My notes','filename':'notes.pdf','mime':'application/pdf','path':'2026-10-21/file.pdf'}
    bank['study_date']='2026-10-21';bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as c:
        assert (await c.get('/api/days/2026-10-22')).status_code==403
        response=(await c.get('/api/days/2026-10-21')).json()
        assert response['editable'] and response['notes'][0]['url'].startswith('https://images.test/')
        assert 'path' not in response['notes'][0]
        assert response['quizzes'][0]['release_date']=='2026-10-22' and not response['quizzes'][0]['available']
        assert not (await c.get('/api/days/2026-10-20')).json()['editable']

@pytest.mark.asyncio
async def test_quiz_releases_day_after_study_and_never_exposes_future_questions(cloud,bank,monkeypatch):
    bank['status']='open';bank['study_date']='2026-10-21';await cloud.put_quiz(bank)
    async with connection() as c:
        assert not (await c.get('/api/dashboard')).json()['quizzes']
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).status_code==403
        monkeypatch.setattr(api,'today',lambda:date(2026,10,22))
        quizzes=(await c.get('/api/dashboard')).json()['quizzes']
        assert len(quizzes)==1 and quizzes[0]['release_date']=='2026-10-22'
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).status_code==200

@pytest.mark.asyncio
async def test_notes_upload_pdf_photo_replay_and_done_do_not_change_quiz(cloud,monkeypatch):
    from app.web import telegram as tg
    monkeypatch.setattr(tg,'telegram',AsyncMock(return_value={}))
    async def send(text=None,**extra):
        await tg.handle_update({'update_id':11,'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},cloud)
    await send('/notes 2026-10-21 | Revision notes')
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'%PDF-1.7 sample'))
    file={'file_id':'one','file_unique_id':'pdf-one','file_name':'notes.pdf'}
    await send(document=file);await send(document=file)
    assert len(cloud.note_rows)==1
    assert next(iter(cloud.note_rows.values()))['mime']=='application/pdf'
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'\x89PNG\r\n\x1a\nsample'))
    await send(photo=[{'file_id':'two','file_unique_id':'image-two'}])
    assert len(cloud.note_rows)==2 and not cloud.banks
    await send('/done')
    assert cloud.admins[123456789]['upload_mode']=='quiz'

@pytest.mark.asyncio
async def test_help_works_even_when_database_setup_is_broken(monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.state=AsyncMock(side_effect=HTTPException(503,'Unavailable'))
    reply=AsyncMock(return_value={});monkeypatch.setattr(tg,'telegram',reply)
    await tg.handle_update({'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},'text':'/start'}},store)
    store.state.assert_not_called()
    assert '/notes' in reply.call_args.args[1]['text']

@pytest.mark.asyncio
async def test_bulk_json_and_fifteen_named_diagrams_attach_without_losing_other_images(cloud,monkeypatch):
    import json
    from app.web import telegram as tg
    monkeypatch.setattr(tg,'telegram',AsyncMock(return_value={}))
    async def send(text=None,**extra):
        await tg.handle_update({'update_id':33,'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},cloud)
    await send('/topic 2026-10-21 | Full paper')
    await send('/bulk')
    payload={'questions':[{'question_number':i,'question':f'Paper question {i}?','options':['A','B','C','D'],'correct_option':i%4,'explanation':f'Explanation {i}'} for i in range(1,101)]}
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=json.dumps(payload).encode()))
    await send(document={'file_id':'paper','file_name':'paper.json'})
    bank=next(iter(cloud.banks.values()));assert len(bank['questions'])==100
    await send('/images')
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'\x89PNG\r\n\x1a\nsample'))
    numbers=[2,7,12,15,19,22,30,38,45,51,60,68,79,88,99]
    await asyncio.gather(*(send(document={'file_id':f'image-{n}','file_unique_id':f'image-{n}','file_name':f'Q{n}.png'}) for n in numbers))
    stored=cloud.banks[bank['id']]['questions']
    assert [i+1 for i,q in enumerate(stored) if q['image_path']]==numbers
    assert all(q['explanation']==f'Explanation {i+1}' for i,q in enumerate(stored))
    assert all(q['correct_option']==(i+1)%4 for i,q in enumerate(stored))
    async with connection() as c:
        # Approved today still stays locked until tomorrow.
        await send('/open')
        assert (await c.post(f'/api/quizzes/{bank["id"]}/start')).status_code==403
        monkeypatch.setattr(api,'today',lambda:date(2026,10,22))
        attempt=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        assert sum(bool(q['image_url']) for q in attempt['questions'])==15
        assert all('correct_option' not in q for q in attempt['questions'])


def test_diagram_labels_use_printed_number_and_explicit_array_position():
    from app.web.attachments import attachment_number,resolve_question
    questions=[{'question':'21. First?','options':['A','B'],'correct_option':0},
               {'question_number':59,'question':'A diagram?','options':['A','B'],'correct_option':0}]
    assert resolve_question(questions,'Q59')==1
    assert resolve_question(questions,'21')==0
    assert resolve_question(questions,'#1')==0
    assert attachment_number(filename='image_q59.png')=='59'
    assert attachment_number(caption='Question 59')=='59'
    with pytest.raises(HTTPException):resolve_question(questions,'1')
    with pytest.raises(HTTPException):resolve_question([{'number':'2'},{'number':'2'}],'Q2')

@pytest.mark.asyncio
async def test_captioned_photo_and_single_question_json_accept_diagrams(cloud,monkeypatch):
    from app.web import telegram as tg
    monkeypatch.setattr(tg,'telegram',AsyncMock(return_value={}))
    async def send(text=None,**extra):
        await tg.handle_update({'update_id':34,'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},cloud)
    await send('/topic 2026-10-21 | Diagram question')
    await send('/question {"question_number":59,"question":"Identify the labelled structure.","options":["A","B"],"correct_option":1,"explanation":"Why B."}')
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'\xff\xd8\xffimage'))
    await send(photo=[{'file_id':'photo','file_unique_id':'q59'}])
    bank=next(iter(cloud.banks.values()))
    assert bank['questions'][0]['image_path'] and bank['questions'][0]['number']=='59'
    await send('/images')
    await send(caption='Q59',photo=[{'file_id':'new-photo','file_unique_id':'q59-new'}])
    assert 'q59-new' in cloud.banks[bank['id']]['questions'][0]['image_path']


def pyq_data():
    return {'sections':{section:[{'question':f'Question {section}{i}', 'options':['A','B','C','D'],'correct_option':0,'explanation':'Because A'} for i in range(count)] for section,count in [('A',20),('B',50),('C',75)]}}


def test_unlimited_practice_count_and_strict_pyq_format():
    item={'question':'Q?','options':['A','B'],'correct_option':0}
    assert len(validate_bank({'questions':[item]*1201},'Topic','2026-10-16')['questions'])==1201
    data=pyq_data();bank=domain.validate_pyq(data,'PYQ','2026-10-17')
    assert bank['kind']=='pyq' and bank['duration_seconds']==10800 and len(bank['questions'])==145
    assert [bank['questions'][i]['section'] for i in (0,20,70)]==['A','B','C']
    data['sections']['A'].pop()
    with pytest.raises(HTTPException):domain.validate_pyq(data,'PYQ','2026-10-17')


def test_official_section_scoring_and_excess_answers_in_paper_order():
    bank=domain.validate_pyq(pyq_data(),'PYQ','2026-10-17')
    a={'kind':'pyq','started_at':'2026-10-17T06:00:00+00:00','questions':bank['questions'],'answers':{str(i):0 for i in reversed(range(145))}}
    a['answers']['0']=1;a['answers']['20']=1;a['answers']['70']=1
    domain.finish(a,datetime(2026,10,17,9,tzinfo=timezone.utc))
    assert a['score']==190 and a['correct']==72 and a['wrong']==3
    assert a['section_results']['A']['score']==27.5 and a['section_results']['C']['score']==95
    assert len(a['excluded_indices'])==70 and a['excluded_indices'][:5]==list(range(15,20))
    assert len(domain.mistakes({'attempts':{'a':a}}))==3

@pytest.mark.asyncio
async def test_practice_stale_browser_capped_and_multiple_quizzes_saved(cloud,bank,monkeypatch):
    stamp=datetime(2026,10,20,6,tzinfo=timezone.utc);monkeypatch.setattr(api,'now',lambda:stamp)
    bank['status']='open';await cloud.put_quiz(bank)
    second={**bank,'id':'second','topic':'Other'};await cloud.put_quiz(second)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        stamp+=timedelta(seconds=20)
        await c.post('/api/quizzes/second/start')
        first=(await c.get('/api/attempts/'+a['id'])).json()
        assert first['elapsed_seconds']==20 and not first['running_since'] and not first['submitted_at']
        await c.post('/api/attempts/'+a['id']+'/clock',json={'action':'resume'})
        stamp+=timedelta(days=2)
        first=(await c.get('/api/attempts/'+a['id'])).json()
        assert first['elapsed_seconds']==80 and not first['running_since'] and not first['submitted_at']

@pytest.mark.asyncio
async def test_pyq_same_day_release_no_pause_and_automatic_deadline(cloud,monkeypatch):
    stamp=datetime(2026,10,17,6,tzinfo=timezone.utc)
    monkeypatch.setattr(api,'now',lambda:stamp);monkeypatch.setattr(api,'today',lambda:date(2026,10,17))
    bank=domain.validate_pyq(pyq_data(),'Full PYQ','2026-10-17');bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json();path='/api/attempts/'+a['id']
        assert (await c.post(path+'/clock',json={'action':'pause'})).status_code==400
        await c.put(path+'/answer',json={'index':0,'answer':0})
        stamp+=timedelta(hours=3,seconds=1)
        done=(await c.get(path)).json()
        assert done['score']==2 and done['skipped']==144 and done['elapsed_seconds']==10800
        assert (await c.put(path+'/answer',json={'index':1,'answer':0})).json()=={'submitted':True}

@pytest.mark.asyncio
async def test_telegram_pyq_upload_and_switch_back_to_daily(cloud,monkeypatch):
    import json
    from app.web import telegram as tg
    calls=[]
    async def send(method,body=None,files=None):calls.append((method,body));return {}
    monkeypatch.setattr(tg,'telegram',send)
    async def update(text=None,**extra):
        await tg.handle_update({'update_id':800,'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},cloud)
    await update('/pyq 2026-10-17 | Full PYQ')
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=json.dumps(pyq_data()).encode()))
    await update(document={'file_id':'pyq','file_name':'paper.json'})
    bank=next(iter(cloud.banks.values()))
    assert bank['kind']=='pyq' and len(bank['questions'])==145 and bank['status']=='draft'
    await update('/open')
    assert cloud.banks[bank['id']]['status']=='open'
    await update('/topic 2026-10-19 | Daily topic')
    assert cloud.admins[123456789]['quiz_kind']=='daily'
    assert all(method=='sendMessage' for method,_ in calls)

@pytest.mark.asyncio
async def test_large_practice_saves_answers_beyond_old_limit(cloud):
    bank=validate_bank({'questions':[{'question':f'Question {i}','options':['A','B'],'correct_option':0} for i in range(1202)]},'Large bank','2026-10-16')
    bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as c:
        a=(await c.post(f'/api/quizzes/{bank["id"]}/start')).json()
        result=await c.put('/api/attempts/'+a['id']+'/answer',json={'index':1201,'answer':0})
        assert result.status_code==200 and result.json()=={'saved':True}
