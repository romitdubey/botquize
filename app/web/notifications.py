"""Optional, isolated Resend notifications. No grading or quiz state is written here."""
import hashlib
import html
import logging
import os
import re
import uuid
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
import httpx
from app.web.daily import release_day

logger=logging.getLogger(__name__)
# Only Vishu receives notifications, independently of the selected login email.
# Never infer recipients from login accounts or STUDY_ALLOWED_EMAILS.
FIXED_RECIPIENTS=('dhankarvishu293@gmail.com',)


def configuration():
    recipients=FIXED_RECIPIENTS
    key=os.getenv('RESEND_API_KEY','').strip();sender=os.getenv('RESEND_FROM_EMAIL','').strip()
    if not key or not sender or len(recipients)!=1:return None
    if any(not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',v) for v in recipients):return None
    return key,sender,recipients


def main_url():
    value=os.getenv('APP_URL','https://botquize.vercel.app').strip()
    try:
        parsed=urlsplit(value)
        if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password:return f'https://{parsed.netloc}/'
    except ValueError:pass
    return 'https://botquize.vercel.app/'


def event_data(kind,row):
    if kind=='custom':
        return {'id':f'custom:{row["id"]}','kind':kind,'subject':row['subject'],'title':row['subject'],'intro':'A little message for you.','detail':'','stats':[],'message':row['body'],'url':main_url()}
    if kind=='result':
        if not row.get('submitted_at'):return None
        total=len(row.get('questions',[]));correct=row.get('correct',0);wrong=row.get('wrong',0)
        seconds=max(0,int(row.get('elapsed_seconds',0)));minutes,seconds=divmod(seconds,60)
        stats=[('Correct',str(correct)),('Wrong',str(wrong)),('Skipped',str(row.get('skipped',0))),
               ('Accuracy',f'{round(correct/(correct+wrong)*100) if correct+wrong else 0}%'),('Time spent',f'{minutes}m {seconds}s'),('Questions',str(total))]
        if row.get('kind')=='pyq':stats.insert(0,('Exam marks',f'{row.get("score",0):g} / 200'))
        title='A little wiser. A little closer.'
        intro='Vishu’s result is ready. Here is a little snapshot of the progress.'
        subject='Vishu’s result is ready 💚'
        detail=row.get('topic','Practice result')
    elif kind=='quiz':
        exam=row.get('kind')=='pyq';name='Full PYQ exam' if exam else 'Topic quiz'
        title='Your next step is ready.';intro='A fresh opportunity to practise, recall and grow.'
        subject=('A new PYQ paper for Vishu 🌿' if exam else 'A new quiz for Vishu 🌿')
        stats=[('Practice',name),('Questions',str(len(row.get('questions',[])))),('Opens on',release_day(row).strftime('%d %b %Y'))]
        if exam:stats.append(('Time limit','3 hours'))
        detail=row.get('topic','New practice')
    elif kind=='notes':
        title='A little help for your next chapter.';intro='Fresh study material has been added for Vishu. Open your study space when you’re ready.'
        subject='New study material for Vishu 🌷';detail=row.get('title','Study material')
        stats=[('Study day',str(row.get('study_date',''))),('Material','PDF' if row.get('mime')=='application/pdf' else 'Photo')]
    else:return None
    # Deliberate allowlist: never include question text, keys, explanations or source files.
    return {'id':f'{kind}:{row["id"]}','kind':kind,'subject':subject,'title':title,'intro':intro,'detail':str(detail)[:500],'stats':stats,'url':main_url()}


def render_email(event):
    esc=lambda value:html.escape(str(value),quote=True)
    cells=[]
    for label,value in event['stats']:
        cells.append(f'<td width="50%" style="padding:16px;border:4px solid #ffffff;background:#f0f5ec;border-radius:12px;vertical-align:top"><div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#677b69">{esc(label)}</div><div style="font-size:24px;font-weight:700;color:#174f3c;margin-top:6px">{esc(value)}</div></td>')
    rows=''.join('<tr>'+''.join(cells[i:i+2])+('</tr>' if len(cells[i:i+2])==2 else '<td></td></tr>') for i in range(0,len(cells),2))
    message=''.join('<p style="font-size:16px;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere;color:#344e3d">'+esc(paragraph).replace('\n','<br>')+'</p>' for paragraph in event.get('message','').split('\n\n') if paragraph)
    body=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(event['subject'])}</title></head>
<body style="margin:0;padding:0;background:#f5f5ed;font-family:Arial,sans-serif;color:#20352b"><div style="display:none;max-height:0;overflow:hidden">{esc(event['intro'])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5ed"><tr><td align="center" style="padding:32px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:20px;overflow:hidden">
<tr><td style="padding:30px;background:#174f3c;color:#f5f5df"><div style="font-size:12px;letter-spacing:3px;font-weight:700">🌿 STUDY GROVE</div><div style="margin-top:10px;color:#bdd4b6;font-size:12px">A little progress, every day.</div></td></tr>
<tr><td style="padding:30px"><div style="color:#176b50;font-size:12px;font-weight:700;letter-spacing:2px">FOR VISHU, WITH LOVE 💚</div><h1 style="font-size:30px;line-height:1.25;margin:14px 0;color:#20352b">{esc(event['title'])}</h1><p style="font-size:15px;line-height:1.7;color:#68776a">{esc(event['intro'])}</p><p style="font-size:16px;font-weight:700;line-height:1.6;overflow-wrap:anywhere">{esc(event['detail'])}</p>
{message}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0">{rows}</table>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0"><tr><td bgcolor="#176b50" style="border-radius:10px"><a href="{esc(event['url'])}" style="display:inline-block;padding:16px 24px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700">Open our study space →</a></td></tr></table>
<p style="font-size:13px;line-height:1.8;color:#7a8879">One topic. One day. One little step closer.<br>We’re cheering for you, Vishu. 🌷</p></td></tr>
<tr><td style="padding:20px 30px;background:#f6f8f2;color:#7a8879;font-size:11px;line-height:1.7">Your private Study Grove update. Full practice and results stay in your study space.</td></tr></table></td></tr></table></body></html>'''
    text='\n\n'.join([event['title'],event['intro'],event['detail'],event.get('message',''),'\n'.join(f'{k}: {v}' for k,v in event['stats']),'Open our study space: '+event['url']])
    return body,text


def schedule(background,store,alias,kind,row):
    if alias!='vishu' or background is None:return
    try:
        if not configuration():return
        event=event_data(kind,row)
        if event:
            if kind=='custom':background.add_task(deliver_manual,store,event,row['reply_chat_id'])
            else:background.add_task(deliver,store,event)
    except Exception:
        logger.warning('Email notification could not be scheduled; study action is unaffected.')


async def deliver(store,event):
    """Send one message to Vishu once, after the study response. Failures never escape."""
    config=configuration()
    if not config:return 'disabled'
    key,sender,recipients=config;token=str(uuid.uuid4());claimed=False
    try:
        body,text=render_email(event)
        batch=[{'from':sender,'to':[address],'subject':event['subject'],'html':body,'text':text} for address in recipients]
        rows=await store.request('POST','study_email_events',body={'id':event['id'],'payload':batch},params={'on_conflict':'id'},headers={'Prefer':'resolution=ignore-duplicates,return=representation'})
        if not rows:rows=await store.request('GET','study_email_events',params={'id':'eq.'+event['id'],'select':'*'})
        if not rows:return 'pending'
        original=rows[0]
        if original['status']=='sent':return 'sent'
        stamp=datetime.now(timezone.utc)
        created=datetime.fromisoformat(original['created_at'].replace('Z','+00:00'))
        # Resend idempotency retention is finite. Do not blindly replay uncertain old sends.
        if stamp-created>timedelta(hours=23):
            logger.warning('Email event needs manual review; automatic retry window elapsed.');return 'review'
        lease=(stamp+timedelta(seconds=60)).isoformat()
        rows=await store.request('PATCH','study_email_events',params={'id':'eq.'+event['id'],'status':'neq.sent','or':f'(lease_until.is.null,lease_until.lt.{stamp.isoformat()})'},body={'status':'sending','lease_token':token,'lease_until':lease})
        if not rows:return 'pending'
        claimed=True
        frozen=rows[0]['payload']
        if len(frozen)!=len(recipients) or any(not isinstance(item.get('to'),list) or len(item['to'])!=1 for item in frozen) or {item['to'][0].lower() for item in frozen}!={address.lower() for address in recipients}:
            raise RuntimeError('resend_recipient_configuration_changed')
        async with httpx.AsyncClient(timeout=8) as client:
            response=await client.post('https://api.resend.com/emails/batch',headers={'Authorization':'Bearer '+key,'Idempotency-Key':'study-'+hashlib.sha256(event['id'].encode()).hexdigest(),'Content-Type':'application/json'},json=frozen)
        if not response.is_success:raise RuntimeError('resend_http_'+str(response.status_code))
        ids=response.json().get('data',[])
        if len(ids)!=len(recipients) or any(not item.get('id') for item in ids):raise RuntimeError('resend_invalid_response')
        await store.request('PATCH','study_email_events',params={'id':'eq.'+event['id'],'lease_token':'eq.'+token},body={'status':'sent','sent_at':datetime.now(timezone.utc).isoformat(),'lease_until':None,'last_error':None})
        return 'sent'
    except Exception as exc:
        logger.warning('Email delivery is pending or failed; study action is unaffected.')
        if claimed:
            try:
                safe=str(exc) if isinstance(exc,RuntimeError) and str(exc).startswith('resend_') else 'delivery_or_storage_error'
                await store.request('PATCH','study_email_events',params={'id':'eq.'+event['id'],'lease_token':'eq.'+token},body={'status':'failed','lease_until':None,'last_error':safe})
            except Exception:pass
        return 'failed'


async def deliver_manual(store,event,chat_id):
    status=await deliver(store,event)
    from app.config import ADMIN_USER_IDS
    if chat_id not in ADMIN_USER_IDS:return
    from app.web.telegram import telegram
    messages={'sent':'Email accepted by Resend for Vishu ✅',
              'failed':'Email could not be confirmed. Check Resend settings/outbox, then tap Send again to retry this same email safely.',
              'disabled':'Email is not configured. Set RESEND_API_KEY and RESEND_FROM_EMAIL in Vercel and redeploy.',
              'review':'This older email needs manual review in Resend before resending.',
              'pending':'This email is already being processed. No duplicate email was created.'}
    try:await telegram('sendMessage',{'chat_id':chat_id,'text':messages[status]})
    except Exception:logger.warning('Email delivery acknowledgement could not be sent to the admin.')
