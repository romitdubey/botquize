"""Notification isolation, single-recipient limits, idempotency and safe content."""
import asyncio
import copy
from datetime import datetime,timezone
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import BackgroundTasks
from app.web import notifications as mail
from tests.test_website import MemoryStore,connection
from app.web import api

@pytest.fixture
def mail_config(monkeypatch):
    monkeypatch.setattr(mail,'FIXED_RECIPIENTS',('first@example.com',))
    monkeypatch.setenv('RESEND_API_KEY','re_test_only')
    monkeypatch.setenv('RESEND_FROM_EMAIL','Study Grove <updates@example.com>')
    monkeypatch.setenv('STUDY_NOTIFICATION_EMAILS','first@example.com,second@example.com')
    monkeypatch.setenv('APP_URL','https://botquize.vercel.app/')


def result():
    return {'id':'attempt-1','submitted_at':'2026-10-18T01:00:00Z','kind':'daily','topic':'Enzymes <script>bad()</script>',
            'questions':[{'question':'PRIVATE QUESTION','correct_option':1,'explanation':'PRIVATE EXPLANATION'}]*3,
            'answers':{'0':1,'1':0},'correct':1,'wrong':1,'skipped':1,'elapsed_seconds':125}

class Outbox:
    def __init__(self):self.rows={}
    async def request(self,method,table,params=None,body=None,headers=None):
        assert table=='study_email_events'
        if method=='POST':
            if body['id'] in self.rows:return []
            self.rows[body['id']]={**copy.deepcopy(body),'status':'pending','created_at':datetime.now(timezone.utc).isoformat(),'lease_until':None}
            return [copy.deepcopy(self.rows[body['id']])]
        ident=params['id'].removeprefix('eq.');row=self.rows.get(ident)
        if not row:return []
        if method=='GET':return [copy.deepcopy(row)]
        if method=='PATCH':
            if params.get('status')=='neq.sent' and (row['status']=='sent' or row.get('lease_until') and row['lease_until']>datetime.now(timezone.utc).isoformat()):return []
            if params.get('lease_token') and params['lease_token']!='eq.'+row.get('lease_token',''):return []
            row.update(copy.deepcopy(body));return [copy.deepcopy(row)]
        raise AssertionError(method)


def mock_resend(monkeypatch,status=200):
    calls=[];original=httpx.AsyncClient
    async def transport(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(status,json={'data':[{'id':'email-1'}]} if status==200 else {'message':'private upstream error'})
    factory=lambda **kwargs:original(transport=httpx.MockTransport(transport),**kwargs)
    monkeypatch.setattr(mail.httpx,'AsyncClient',factory)
    return calls

@pytest.mark.parametrize('emails',['','invalid','one@example.com,ONE@example.com','a@example.com,b@example.com,c@example.com','a@example.com,invalid'])
def test_never_infer_login_addresses_or_send_to_wrong_recipient_count(monkeypatch,emails):
    monkeypatch.setenv('RESEND_API_KEY','test');monkeypatch.setenv('RESEND_FROM_EMAIL','updates@example.com')
    monkeypatch.setenv('STUDY_ALLOWED_EMAILS','login1@example.com,login2@example.com')
    monkeypatch.setattr(mail,'FIXED_RECIPIENTS',tuple(v for v in emails.split(',') if v))
    assert mail.configuration() is None


def test_result_template_is_stats_only_escaped_and_links_to_main_page():
    event=mail.event_data('result',result());body,text=mail.render_email(event)
    assert '50%' in body and '2m 5s' in body
    assert 'PRIVATE QUESTION' not in body+text and 'PRIVATE EXPLANATION' not in body+text
    assert 'correct_option' not in str(event) and '<script>' not in body
    assert 'href="https://botquize.vercel.app/"' in body
    assert len(event['stats'])==6


def test_exam_email_includes_marks_without_answers():
    data=result();data.update(kind='pyq',score=142.5)
    body,_=mail.render_email(mail.event_data('result',data))
    assert '142.5 / 200' in body and 'PRIVATE QUESTION' not in body

@pytest.mark.asyncio
async def test_only_vishu_schedules_and_unfinished_results_never_send(mail_config):
    tasks=BackgroundTasks();store=Outbox()
    for alias in ('me',None,'other'):mail.schedule(tasks,store,alias,'result',result())
    unfinished=result();unfinished['submitted_at']=None
    mail.schedule(tasks,store,'vishu','result',unfinished)
    assert tasks.tasks==[]
    mail.schedule(tasks,store,'vishu','result',result());assert len(tasks.tasks)==1

@pytest.mark.asyncio
async def test_one_message_and_no_duplicates_on_refresh_or_concurrency(mail_config,monkeypatch):
    calls=mock_resend(monkeypatch);store=Outbox();event=mail.event_data('result',result())
    await asyncio.gather(mail.deliver(store,event),mail.deliver(store,event))
    await mail.deliver(store,event)
    assert len(calls)==1
    import json
    batch=json.loads(calls[0].content)
    assert [v['to'] for v in batch]==[['first@example.com']]
    assert calls[0].headers['idempotency-key'].startswith('study-')
    assert store.rows[event['id']]['status']=='sent'

@pytest.mark.asyncio
async def test_delivery_failure_is_recorded_safely_and_does_not_raise(mail_config,monkeypatch):
    calls=mock_resend(monkeypatch,status=503);store=Outbox();event=mail.event_data('result',result())
    await mail.deliver(store,event)
    assert store.rows[event['id']]['status']=='failed'
    assert store.rows[event['id']]['last_error']=='resend_http_503'
    assert 'private upstream error' not in str(store.rows)
    await mail.deliver(store,event)
    assert len(calls)==2 and calls[0].headers['idempotency-key']==calls[1].headers['idempotency-key']

@pytest.mark.asyncio
async def test_missing_outbox_does_not_break_study_action(mail_config):
    store=MemoryStore();store.request=AsyncMock(side_effect=RuntimeError('Missing migration'))
    await mail.deliver(store,mail.event_data('result',result()))

@pytest.mark.asyncio
async def test_telegram_open_and_notes_only_notify_vishu(monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.admins[123456789]={'target_alias':'vishu','target_user_id':'vishu','quiz_id':'paper'}
    store.banks['paper']={'id':'paper','owner_id':'vishu','kind':'daily','study_date':'2026-10-16','topic':'Topic','questions':[],'status':'draft'}
    monkeypatch.setattr(tg,'telegram',AsyncMock());notify=AsyncMock()
    # Notification scheduler is synchronous; capture without a coroutine.
    events=[]
    async def update(text=None,**extra):
        await tg.handle_update({'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},store,notify=lambda *args:events.append(args))
    await update('/open');assert events[0][:2]==('vishu','quiz')
    await update('/close');assert len(events)==1
    await update('/notes 2026-10-16 | Notes')
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'%PDF-1.7'))
    await update(document={'file_id':'pdf','file_name':'notes.pdf'})
    assert events[-1][:2]==('vishu','notes')
    # Actual delivery gate suppresses every me event, independent of Telegram.
    tasks=BackgroundTasks();mail.schedule(tasks,store,'me','notes',events[-1][2]);assert not tasks.tasks

# Reuse the existing authenticated API fixture; notification scheduling is captured only.
from tests.test_website import cloud,bank

@pytest.mark.asyncio
async def test_result_hooks_are_additive_and_answer_saves_do_not_notify(cloud,bank,monkeypatch):
    events=[]
    monkeypatch.setattr(api,'schedule_email',lambda background,store,alias,kind,row:events.append((alias,kind,copy.deepcopy(row))))
    async def identity():return {'id':'learner-1','email':'login@example.com','account_alias':'vishu'}
    api.app.dependency_overrides[api.learner]=identity
    bank['status']='open';await cloud.put_quiz(bank)
    async with connection() as client:
        attempt=(await client.post('/api/quizzes/'+bank['id']+'/start')).json()
        await client.put('/api/attempts/'+attempt['id']+'/answer',json={'index':0,'answer':1})
        assert events==[]
        submitted=(await client.post('/api/attempts/'+attempt['id']+'/submit')).json()
        assert submitted['correct']==1 and len(events)==1 and events[0][:2]==('vishu','result')
        again=(await client.get('/api/attempts/'+attempt['id'])).json()
        assert again==submitted and len(events)==2  # Delivery outbox deduplicates this stable event ID.
        assert mail.event_data('result',events[0][2])['id']==mail.event_data('result',events[1][2])['id']


def test_quiz_mail_explains_release_date_and_pyq_duration():
    event=mail.event_data('quiz',{'id':'q','study_date':'2026-10-18','kind':'daily','topic':'Topic','questions':[{}]*20})
    assert ('Opens on','19 Oct 2026') in event['stats']
    event=mail.event_data('quiz',{'id':'p','study_date':'2026-10-18','kind':'pyq','topic':'Full PYQ','questions':[{}]*145})
    assert ('Opens on','18 Oct 2026') in event['stats'] and ('Time limit','3 hours') in event['stats']


def test_fixed_provided_recipients_cannot_be_overridden_by_login_or_env(monkeypatch):
    monkeypatch.setenv('RESEND_API_KEY','test');monkeypatch.setenv('RESEND_FROM_EMAIL','updates@example.com')
    monkeypatch.setenv('STUDY_NOTIFICATION_EMAILS','wrong@example.com,other@example.com')
    assert mail.configuration()[2]==('dhankarvishu293@gmail.com',)

@pytest.mark.asyncio
async def test_custom_email_preview_send_and_cancel_are_admin_only(mail_config,monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.admins[123456789]={'target_alias':'vishu','target_user_id':'vishu'}
    calls=[];events=[]
    async def send(method,body=None,files=None):calls.append((method,body));return {}
    monkeypatch.setattr(tg,'telegram',send)
    async def update(text=None,callback=None,user=123456789):
        envelope={'from':{'id':user},'chat':{'id':user,'type':'private'}}
        payload={'message':{**envelope,'text':text}} if callback is None else {'callback_query':{'id':'click','from':{'id':user},'message':{**envelope,'from':{'id':777}},'data':callback}}
        await tg.handle_update(payload,store,notify=lambda *args:events.append(args))
    await update('/email A little reminder | Take a break, Vishu.\nYou’ve got this 💚')
    draft=store.admins[123456789]['email_draft'];assert not events
    assert calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']=='mail:send:'+draft['id']
    assert calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['text']=='Send to Vishu 💚'
    assert 'romitbharadwaj1@gmail.com' not in calls[-1][1]['text']
    await update(callback='mail:send:'+draft['id'],user=999)
    assert events==[]
    await update(callback='mail:send:'+draft['id'])
    assert events[-1][0:2]==('vishu','custom') and events[-1][2]['subject']=='A little reminder'
    assert 'Take a break' in events[-1][2]['body']
    await update(callback='mail:send:'+draft['id'])
    assert events[-1][2]['id']==events[-2][2]['id']  # same outbox key on double tap
    await update(callback='mail:cancel:'+draft['id'])
    assert 'already queued' in calls[-1][1]['text']
    await update('/email Another subject\nA multiline body\nSecond line')
    new=store.admins[123456789]['email_draft'];assert new['id']!=draft['id']
    await update(callback='mail:cancel:'+new['id'])
    assert store.admins[123456789]['email_draft'] is None
    assert 'Nothing was sent' in calls[-1][1]['text']

@pytest.mark.asyncio
async def test_custom_email_requires_vishu_and_configuration_before_send(monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.admins[123456789]={'target_alias':'me'};send=AsyncMock()
    monkeypatch.setattr(tg,'telegram',send);events=[]
    async def update(text=None,callback=None):
        payload={'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},'text':text}} if not callback else {'callback_query':{'id':'click','from':{'id':123456789},'message':{'chat':{'id':123456789,'type':'private'}},'data':callback}}
        await tg.handle_update(payload,store,notify=lambda *args:events.append(args))
    await update('/email Test | Body');assert 'account vishu' in send.call_args.args[1]['text']
    store.admins[123456789]['target_alias']='vishu'
    await update('/email Test | Body');draft=store.admins[123456789]['email_draft']
    await update(callback='mail:send:'+draft['id'])
    assert 'RESEND_API_KEY' in send.call_args.args[1]['text'] and not events
    assert not store.admins[123456789]['email_draft'].get('send_requested')


def test_custom_template_preserves_message_without_running_html():
    event=mail.event_data('custom',{'id':'manual','subject':'Hello Vishu','body':'First paragraph\n\n<script>literal text</script>\nSecond line'})
    body,text=mail.render_email(event)
    assert '<script>' not in body and '&lt;script&gt;' in body
    assert 'First paragraph' in body and 'Second line' in body and '<script>literal text</script>' in text
    assert event['id']=='custom:manual' and event['subject']=='Hello Vishu'

@pytest.mark.asyncio
async def test_manual_delivery_sends_one_once_and_acknowledges_only_admin(mail_config,monkeypatch):
    from app.web import telegram as tg
    calls=mock_resend(monkeypatch);ack=AsyncMock();monkeypatch.setattr(tg,'telegram',ack)
    store=Outbox();event=mail.event_data('custom',{'id':'draft-123','subject':'A small reminder','body':'Take a break.\n\nYou’ve got this 💚'})
    await mail.deliver_manual(store,event,123456789)
    await mail.deliver_manual(store,event,123456789)
    assert len(calls)==1
    import json
    batch=json.loads(calls[0].content)
    assert len(batch)==1 and all(v['subject']=='A small reminder' and 'Take a break' in v['text'] for v in batch)
    assert ack.call_args.args[1]['chat_id']==123456789 and 'accepted by Resend' in ack.call_args.args[1]['text']


@pytest.mark.asyncio
async def test_old_two_recipient_outbox_never_replays_removed_address(mail_config,monkeypatch):
    calls=mock_resend(monkeypatch);store=Outbox();event=mail.event_data('result',result())
    store.rows[event['id']]={'id':event['id'],'status':'failed','created_at':datetime.now(timezone.utc).isoformat(),
        'payload':[{'to':['first@example.com']},{'to':['removed@example.com']}],'lease_until':None}
    assert await mail.deliver(store,event)=='failed'
    assert not calls
    assert store.rows[event['id']]['last_error']=='resend_recipient_configuration_changed'


def test_html_email_keeps_design_but_removes_active_content():
    from app.web.email_html import clean_email_html
    body,text=clean_email_html('<html><head><script>secret()</script></head><body><p style="color:#244c3e;padding:20px;background:url(https://bad.test)">Hello Vishu ❤️</p><script>bad()</script><img src="https://bad.test/pixel"><a href="javascript:bad()" onclick="bad()">Hi</a></body></html>')
    assert 'color:#244c3e' in body and 'padding:20px' in body
    assert 'Hello Vishu ❤️' in text
    assert all(v not in body+text for v in ('bad()', 'secret()', 'bad.test', 'onclick', 'javascript:'))
    event=mail.event_data('custom',{'id':'html','subject':'For Vishu','html_body':body})
    rendered,plain=mail.render_email(event)
    assert 'Hello Vishu ❤️' in rendered+plain
    assert 'color:#244c3e' in rendered


@pytest.mark.asyncio
async def test_html_upload_previews_and_requires_explicit_send(mail_config,monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.admins[123456789]={'target_alias':'vishu','target_user_id':'vishu'}
    send=AsyncMock();events=[]
    monkeypatch.setattr(tg,'telegram',send)
    monkeypatch.setattr(tg,'download',AsyncMock(return_value=b'<html><body><p style="color:#244c3e">Hello Vishu</p></body></html>'))
    async def update(**message):
        await tg.handle_update({'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**message}},store,notify=lambda *args:events.append(args))
    await update(text='/emailhtml A letter for you')
    await update(document={'file_id':'html','file_name':'letter.html','file_size':120})
    draft=store.admins[123456789]['email_draft']
    assert not events and draft['subject']=='A letter for you' and 'color:#244c3e' in draft['html_body']
    assert store.admins[123456789]['upload_mode']=='quiz'
    assert 'Hello Vishu' in send.call_args.args[1]['text']
    await tg.handle_update({'callback_query':{'id':'click','from':{'id':123456789},'message':{'chat':{'id':123456789,'type':'private'}},'data':'mail:send:'+draft['id']}},store,notify=lambda *args:events.append(args))
    assert len(events)==1 and events[0][2]['html_body']==draft['html_body']


def test_romantic_email_artifact_remains_styled_after_cleaning():
    from pathlib import Path
    from app.web.email_html import clean_email_html
    body,text=clean_email_html(Path('output/emails/for-vishu.html').read_text())
    assert 'background-color:#244c3e' in body
    assert 'Hi meri Vishu 🌷' in text
    assert 'Abhi jo bhi hua, uske liye sorry.' in text
    assert 'khane aur apni health' in text
    assert 'Ab ek chhoti si smile, phir test? Main yahin hoon, tumhare saath. 💚' in text
    assert 'Tumhara bandar 🐒' in text and 'https://botquize.vercel.app/' in body
