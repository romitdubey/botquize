"""Private Telegram administration only: never sends quiz polls or channel posts."""
import json
import os
import uuid
from pathlib import Path
from datetime import date
import httpx
from fastapi import HTTPException
from app.config import BOT_TOKEN, ADMIN_USER_IDS
from app.web.email_html import clean_email_html
from app.web.accounts import scoped_quiz, copy_content
from app.web.importer import export_part, merge_exports
from app.web.notifications import configuration as email_configuration, notification_recipients
from app.web.domain import validate_bank, validate_pyq, today
from app.web.daily import scheduled_day, release_day
from app.web.attachments import attachment_number, resolve_question, question_number
from app.services.planner import plan_rows

HELP='''🌿 Study desk — admin controls

/account me your@email.com — bind/select your test login
/account vishu her@email.com — bind/select Vishu’s login
/account me or /account vishu — switch upload destination
/copyto vishu — copy selected quiz + that day’s notes as drafts, without results
Select the destination BEFORE uploading. Switching clears the current selection.

/topic 2026-10-16 | Enzymes
Set the study day + topic for your next JSON upload. Bilingual question + answer exports can be sent as two files, in either order (.json / .json4); they merge automatically by question ID. Then send your usual JSON file. It is saved as a draft; all explanations are preserved.

/notes 2026-10-16 | Topic notes — send PDFs/photos for that study day
/done — finish notes uploads and return to JSON mode
/open — approve a test; it becomes visible the day after its study date
/close — hide it from new attempts
/tests — list recent tests with IDs
/select TEST-ID — select an older test
/bulk — upload any number of daily questions (10 MB per JSON file)
/pyq YYYY-MM-DD | Paper title — upload a full A/B/C exam JSON (20/50/75 questions)
/images — send diagram files named Q12.png or photos captioned Q12
/image Q12 — attach the next photo to printed question 12
/image #12 — attach to the 12th item in the JSON array
/question {JSON} — add one question as a new draft, then send its diagram
/email Subject | Body — preview an email to RESEND_TO_EMAIL (Vishu account only)
/emailhtml Subject — upload an HTML email file, preview, then confirm
/status — selected test and upload label
/plan — today's study topic

Questions, timers, results and Monday retries live on the website. No quizzes are posted to Telegram. /start or /help shows this guide.'''

async def telegram(method,body=None,files=None):
    async with httpx.AsyncClient(timeout=25) as client:
        if files: response=await client.post(f'https://api.telegram.org/bot{BOT_TOKEN}/{method}',data=body,files=files)
        else: response=await client.post(f'https://api.telegram.org/bot{BOT_TOKEN}/{method}',json=body)
    if response.status_code>=400: raise HTTPException(503,'Telegram is temporarily unavailable.')
    payload=response.json()
    if not payload.get('ok'): raise HTTPException(503,'Telegram request failed.')
    return payload.get('result')

async def download(file_id,max_size):
    info=await telegram('getFile',{'file_id':file_id})
    if info.get('file_size',0)>max_size: raise HTTPException(400,'File is too large (maximum 10 MB).')
    path=info.get('file_path','')
    if not path: raise HTTPException(400,'Telegram could not provide this file.')
    async with httpx.AsyncClient(timeout=25) as client:
        async with client.stream('GET',f'https://api.telegram.org/file/bot{BOT_TOKEN}/{path}') as response:
            if response.status_code!=200: raise HTTPException(503,'Could not download the file.')
            chunks=[];size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>max_size: raise HTTPException(400,'File is too large (maximum 10 MB).')
                chunks.append(chunk)
    return b''.join(chunks)

async def handle_update(update,store,notify=None):
    callback=update.get('callback_query')
    message=callback.get('message') if callback else update.get('message')
    if not message: return # Old inline buttons/poll answers never publish anything.
    user=(callback.get('from',{}) if callback else message.get('from',{})).get('id');chat=message.get('chat',{})
    if user not in ADMIN_USER_IDS or chat.get('type')!='private': return
    chat_id=chat['id']
    async def reply(text): await telegram('sendMessage',{'chat_id':chat_id,'text':text[:4000]})
    text=message.get('text','').strip()
    parts=text.split(maxsplit=1);command=parts[0].split('@')[0].lower() if parts else ''; arg=parts[1].strip() if len(parts)>1 else ''
    if command in ('/start','/help'):
        await reply(HELP);return
    try:
        state=(await store.state(user,admin=True))['data']
        async def change(**fields):
            def action(data): data.update(fields)
            await store.mutate(user,action,admin=True)
            state.update(fields)
        async def selected_quiz(quiz_id=None):
            if not (quiz_id or state.get('quiz_id')):raise HTTPException(400,'Upload a JSON file or /select a test first.')
            quiz=await store.quiz(quiz_id or state['quiz_id'])
            if quiz.get('kind') not in ('daily','pyq'):raise HTTPException(400,'Personal mistake retries cannot be edited or copied.')
            target=state.get('target_user_id')
            if target and quiz.get('owner_id')!=target and not (not quiz.get('owner_id') and state.get('target_alias')=='vishu'):raise HTTPException(403,'This quiz belongs to another account. Switch /account first.')
            if not target and quiz.get('owner_id'):raise HTTPException(403,'Select its /account first.')
            return quiz
        if callback:
            data=callback.get('data','')
            if not data.startswith(('mail:send:','mail:cancel:')):return
            await telegram('answerCallbackQuery',{'callback_query_id':callback['id']})
            if data.count(':')!=2:return
            operation,mail_id=data.split(':')[1:]
            if state.get('target_alias')!='vishu':await reply('Select /account vishu before sending email.');return
            draft=state.get('email_draft')
            if not draft or draft.get('id')!=mail_id:await reply('This email preview is no longer current. Create a new draft with /email.');return
            if operation=='cancel':
                if draft.get('send_requested'):await reply('This email was already queued. Check the delivery acknowledgement; cancellation cannot recall a sent email.');return
                def cancel(current):
                    if (current.get('email_draft') or {}).get('id')==mail_id and not current['email_draft'].get('send_requested'):current['email_draft']=None
                    elif (current.get('email_draft') or {}).get('send_requested'):raise HTTPException(400,'This email was already queued; cancellation cannot recall it.')
                await store.mutate(user,cancel,admin=True)
                await reply('Email draft cancelled. Nothing was sent.');return
            if not email_configuration():await reply('Set RESEND_API_KEY, RESEND_FROM_EMAIL and a valid RESEND_TO_EMAIL in Vercel, then redeploy. This draft is kept.');return
            if tuple(draft.get('recipients',[]))!=notification_recipients():await reply('The email recipient changed. Create a new /email or /emailhtml preview to confirm the new address. Nothing was sent.');return
            def confirm(current):
                pending=current.get('email_draft') or {}
                if pending.get('id')!=mail_id or current.get('target_alias')!='vishu':raise HTTPException(400,'This email preview expired. Create a new /email draft.')
                pending['send_requested']=True
            await store.mutate(user,confirm,admin=True)
            # Same draft UUID on every tap; the persistent outbox prevents duplicate sends.
            if notify:notify('vishu','custom',{**draft,'reply_chat_id':chat_id})
            await reply('Email queued for '+', '.join(notification_recipients())+'. I’ll confirm when Resend accepts it.');return
        async def email_preview(draft):
            recipients=notification_recipients()
            if not recipients:await reply('Set RESEND_TO_EMAIL to one valid email address in Vercel, then redeploy. Nothing was sent.');return
            draft={**draft,'recipients':list(recipients)}
            await change(email_draft=draft)
            await telegram('sendMessage',{'chat_id':chat_id,'text':('HTML email preview — open your HTML file to see the design.\n' if draft.get('html_body') else 'Email preview — not sent yet\n')+'To: '+', '.join(recipients)+'\n\nSubject: '+draft['subject']+'\n\n'+draft['body'][:3000],
                'reply_markup':{'inline_keyboard':[[{'text':'Send email 💚','callback_data':'mail:send:'+draft['id']},{'text':'Cancel','callback_data':'mail:cancel:'+draft['id']}]]}})
        if command=='/emailhtml':
            if state.get('target_alias')!='vishu':await reply('Use /account vishu first. HTML emails use the configured RESEND_TO_EMAIL.');return
            if not arg or len(arg)>180 or any(c in arg for c in ('\r','\n')):await reply('Use /emailhtml Your subject (1–180 characters), then attach an .html file.');return
            await change(upload_mode='emailhtml',email_subject=arg,email_draft=None)
            await reply('Send your .html file (up to 100 KB). I’ll prepare a preview and wait for Send to Vishu. /done cancels upload mode.');return
        if command=='/email':
            if state.get('target_alias')!='vishu':await reply('Use /account vishu first. Custom emails use the configured RESEND_TO_EMAIL.');return
            if not arg or ('|' not in arg and '\n' not in arg):
                await reply('Use /email Subject | Your message\nOr put the subject on the first line and the message on the following lines.\nYou’ll get a preview before sending.');return
            subject,body=(arg.split('\n',1) if '\n' in arg and ('|' not in arg.split('\n',1)[0]) else arg.split('|',1))
            subject=subject.strip();body=body.strip()
            if not subject or len(subject)>180 or any(c in subject for c in ('\r','\n')) or not body or len(body)>3000:
                await reply('Use a subject of 1–180 characters and a message of 1–3,000 characters.');return
            draft={'id':str(uuid.uuid4()),'subject':subject,'body':body}
            await change(upload_mode='quiz')
            await email_preview(draft);return
        if command=='/account':
            args=arg.split();alias=args[0].lower() if args else ''
            if not args:
                await reply('Selected account: '+state.get('target_alias','not selected')+'\nUse /account me EMAIL or /account vishu EMAIL once; then /account me or /account vishu to switch.');return
            if alias not in ('me','vishu') or len(args)>2:raise HTTPException(400,'Use /account me EMAIL or /account vishu EMAIL. After setup, omit the email to switch.')
            accounts=dict(state.get('accounts',{}))
            if len(args)==2:
                resolved=await store.find_auth_user(args[1].lower())
                if accounts.get(alias) and accounts[alias]['id']!=resolved['id']:raise HTTPException(400,'This alias is already bound to another login. Keep existing bindings to protect saved progress.')
                if any(v['id']==resolved['id'] for k,v in accounts.items() if k!=alias):raise HTTPException(400,'Use different logins for me and vishu.')
                def profile(data):
                    if data.get('account_alias') not in (None,alias):raise HTTPException(400,'This login is already assigned to another account role.')
                    data['account_alias']=alias
                await store.mutate(resolved['id'],profile)
                accounts[alias]=resolved
            if alias not in accounts:raise HTTPException(400,f'First bind /account {alias} EMAIL using that Supabase login email.')
            target=accounts[alias]
            await change(accounts=accounts,target_alias=alias,target_user_id=target['id'],quiz_id=None,pending_image=None,upload_mode='quiz',study_date=None,topic=None,notes_date=None,notes_title=None,quiz_kind='daily',import_parts={},email_draft=None)
            await reply(f'Account selected: {alias} · {target["email"]}\nNew quizzes, notes and diagrams stay in this account. Use /topic or /notes next. Existing answers/results are unchanged.');return
        if command=='/copyto':
            alias=arg.lower();accounts=state.get('accounts',{})
            if alias not in accounts:raise HTTPException(400,'Bind the destination first with /account vishu EMAIL (or /account me EMAIL), then select the source account and quiz.')
            quiz=await selected_quiz();target=accounts[alias]
            if target['id']==quiz.get('owner_id'):raise HTTPException(400,'Choose a different destination account.')
            copied,count=await copy_content(store,quiz,target['id'])
            await reply(f'Copied to {alias}: {copied["topic"]} + {count} notes.\nCopy ID: {copied["id"]}\nQuiz status: {copied["status"]}. Results, time and studied marks were not copied.\nTo release: /account {alias} then /select {copied["id"]} then /open.');return
        if not state.get('target_user_id') and (command in ('/topic','/pyq','/notes','/bulk','/question','/images','/image','/open','/close') or message.get('document') or message.get('photo')):
            raise HTTPException(400,'Select an account first: /account me EMAIL or /account vishu EMAIL. This keeps test uploads away from Vishu.')
        if command in ('/topic','/pyq'):
            if '|' not in arg: await reply(f'Use {command} YYYY-MM-DD | Topic or paper title');return
            day,topic=map(str.strip,arg.split('|',1))
            try: date.fromisoformat(day)
            except ValueError: await reply('Use a date like 2026-10-16.');return
            if not topic or len(topic)>500: await reply('Please provide a topic under 500 characters.');return
            await change(study_date=day,topic=topic,upload_mode='quiz',quiz_kind='pyq' if command=='/pyq' else 'daily',quiz_id=None,pending_image=None,import_parts={})
            await reply(f'Next upload: {topic}\nStudy day: {day}\n'+('Send full PYQ JSON with sections A (20 questions), B (50), C (75). Four options per question; correct_option is zero based. Use unique question_number values 1–145.' if command=='/pyq' else 'Send daily JSON with a questions array. Any question count; 10 MB file limit. Practice has no deadline.')+'\nThen /images for diagrams, /open when ready.');return
        if command=='/bulk':
            await change(upload_mode='quiz',pending_image=None)
            await reply(('PYQ mode: send JSON sections A (20), B (50), C (75).' if state.get('quiz_kind')=='pyq' else 'Daily mode: send JSON with a questions array; any question count (10 MB file limit).')+' Include question_number, question, options, correct_option and explanation. /topic DATE | Topic selects daily mode; /pyq DATE | Title selects full exam. Then /images to attach named diagrams.');return
        if command=='/images':
            if not state.get('quiz_id'):await reply('Upload a JSON paper or /select a test first.');return
            quiz=await selected_quiz()
            await change(upload_mode='images',pending_image=None)
            await reply(f'Diagram mode: {quiz["topic"]}\nSend files named Q12.png / Q27.jpg, or photos captioned Q12 / Q27. You can send an album with individually named files. Only those questions get images. Send /done when finished.');return
        if command=='/notes':
            values=arg.split('|',1)
            day=values[0].strip() or state.get('study_date') or today().isoformat()
            row=scheduled_day(day)
            title=values[1].strip()[:500] if len(values)>1 else row['topic']
            await change(upload_mode='notes',notes_date=day,notes_title=title or row['topic'],pending_image=None)
            await reply(f'Notes for {day}: {title or row["topic"]}\nSend PDF files or photos (up to 10 MB each). Send /done when finished.');return
        if command=='/done':
            await change(upload_mode='quiz',pending_image=None)
            await reply('Uploads finished. Use /bulk for a JSON paper, /images for diagrams, or /notes for study material.');return
        if command=='/select':
            quiz=await selected_quiz(arg)
            await change(quiz_id=quiz['id'],study_date=quiz['study_date'],topic=quiz['topic'],quiz_kind=quiz['kind'],pending_image=None,upload_mode='quiz')
            await reply(f'Selected {quiz["topic"]}.');return
        if command in ('/open','/close'):
            if not state.get('quiz_id'): await reply('Upload a JSON file or /select a test first.');return
            quiz=await selected_quiz()
            await store.update_quiz(state['quiz_id'],{'status':'open' if command=='/open' else 'closed'})
            if command=='/open' and notify:notify(state.get('target_alias'),'quiz',quiz)
            link=os.getenv('APP_URL','').rstrip('/')
            await reply((f'Test approved. Opens on {release_day(await store.quiz(state["quiz_id"])):%d %b %Y}. ' if command=='/open' else 'Test closed for new attempts. ')+link);return
        if command=='/tests':
            rows=await store.quizzes(kind='in.(daily,pyq)',owner_id='eq.'+state['target_user_id'] if state.get('target_user_id') else 'is.null',order='created_at.desc',limit='12')
            rows=[q for q in rows if q.get('owner_id')==state.get('target_user_id')]
            await reply('\n\n'.join(f'{q["study_date"]} · {q["topic"]}\n{q["status"]} · {len(q["questions"])} questions\n{q["id"]}' for q in rows) or 'No uploads yet.');return
        if command=='/status':
            quiz=await selected_quiz() if state.get('quiz_id') else None
            await reply(f'Account: {state.get("target_alias","legacy shared")}\nUpload label: {state.get("study_date","not set")} · {state.get("topic","not set")}\n'+
                (f'Selected: {quiz["topic"]}\n{quiz["status"]} · {len(quiz["questions"])} questions\nID: {quiz["id"]}' if quiz else 'No test selected.'));return
        if command=='/plan':
            row=next((r for r in plan_rows() if r['date']==today().isoformat()),None)
            aptitude=row.get('aptitude') if row else None
            extra=('\nAptitude: '+aptitude['topic']+f" · Part {aptitude['part']}/{aptitude['parts']}") if aptitude else ''
            await reply(f'{today()}: '+(row['topic'] if row else 'No scheduled topic today.')+extra);return
        if command=='/image':
            if not state.get('quiz_id'): await reply('Upload or select a test first.');return
            quiz=await selected_quiz()
            index=resolve_question(quiz['questions'],arg)
            label=question_number(quiz['questions'][index],index)
            await change(upload_mode='quiz',pending_image={'quiz_id':quiz['id'],'index':index})
            await reply(f'Send a photo or PNG/JPEG/WebP file for question {label} (array item {index+1}):\n{quiz["questions"][index]["question"][:500]}');return
        document=message.get('document',{})
        if state.get('upload_mode')=='emailhtml' and document:
            if state.get('target_alias')!='vishu':await reply('Use /account vishu first.');return
            if Path(document.get('file_name','')).suffix.lower() not in ('.html','.htm'):await reply('Please attach an .html file, or /done to cancel.');return
            if document.get('file_size',0)>100_000:await reply('HTML email limit is 100 KB.');return
            try:
                raw=(await download(document['file_id'],100_000)).decode('utf-8-sig')
                body,plain=clean_email_html(raw)
            except (ValueError,UnicodeError) as exc:await reply(str(exc));return
            draft={'id':str(uuid.uuid4()),'subject':state['email_subject'],'body':plain,'html_body':body}
            await change(upload_mode='quiz',email_subject=None)
            await email_preview(draft);return
        is_photo=bool(message.get('photo')) or document.get('mime_type','').startswith('image/') or Path(document.get('file_name','')).suffix.lower() in ('.png','.jpg','.jpeg','.webp')
        if state.get('upload_mode')=='notes' and (document or message.get('photo')):
            file=message['photo'][-1] if message.get('photo') else document
            if file.get('file_size',0)>10*1024*1024:await reply('Notes limit is 10 MB per file.');return
            content=await download(file['file_id'],10*1024*1024)
            if content.startswith(b'%PDF-'):mime,extension='application/pdf','pdf'
            elif content.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','jpg'
            elif content.startswith(b'\x89PNG\r\n\x1a\n'):mime,extension='image/png','png'
            elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime,extension='image/webp','webp'
            else:await reply('Notes accept PDF, PNG, JPEG and WebP files. Use /done before uploading quiz JSON.');return
            day=state['notes_date'];scheduled_day(day)
            source=file.get('file_unique_id') or file.get('file_id')
            note_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'study-note:{state.get("target_user_id","shared")}:{day}:{source}'))
            path=f'{day}/{note_id}.{extension}'
            filename=Path(file.get('file_name') or f'Notes.{extension}').name[:240]
            await store.upload_note(path,content,mime)
            await store.put_note({'id':note_id,'study_date':day,'title':state.get('notes_title') or filename,
                'filename':filename,'mime':mime,'path':path,'owner_id':state.get('target_user_id')})
            if notify:notify(state.get('target_alias'),'notes',{'id':note_id,'study_date':day,'title':state.get('notes_title') or filename,'mime':mime})
            await reply(f'Notes saved for {day}: {filename}\nYou can send another PDF/photo, or /done.');return
        if is_photo:
            pending=state.get('pending_image')
            if not pending:
                label=attachment_number(message.get('caption',''),document.get('file_name',''))
                if not state.get('quiz_id') or not label:
                    await reply('Use /image Q12 first, or send a file named Q12.png / a photo captioned Q12 after selecting your JSON paper.');return
                bank=await selected_quiz()
                pending={'quiz_id':bank['id'],'index':resolve_question(bank['questions'],label)}
            file=message['photo'][-1] if message.get('photo') else document
            content=await download(file['file_id'],10*1024*1024)
            if content.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','jpg'
            elif content.startswith(b'\x89PNG\r\n\x1a\n'):mime,extension='image/png','png'
            elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime,extension='image/webp','webp'
            else: await reply('Please send a PNG, JPEG or WebP image.');return
            quiz=await selected_quiz(pending['quiz_id']);index=pending['index']
            path=f'{quiz["id"]}/{index+1}-{file.get("file_unique_id",str(update.get("update_id",0)))}.{extension}'
            await store.upload_image(path,content,mime)
            await store.attach_image(quiz['id'],index,path)
            await change(pending_image=None)
            await reply(f'Diagram attached to question {question_number(quiz["questions"][index],index)} (array item {index+1}). Send more named diagrams or use /open when ready. New attempts will include it.');return
        if document or command=='/question':
            if not state.get('study_date') or not state.get('topic'):
                await reply('First set /topic YYYY-MM-DD | Topic name, then upload your questions.');return
            if command=='/question':
                try: data={'questions':[json.loads(arg)]}
                except (ValueError,TypeError): await reply('Send /question followed by one JSON object with question, options, correct_option and explanation.');return
            else:
                if document.get('file_size',0)>10*1024*1024:await reply('JSON limit is 10 MB.');return
                raw=await download(document['file_id'],10*1024*1024)
                try:data=json.loads(raw.decode('utf-8-sig'))
                except (ValueError,UnicodeError):
                    name=Path(document.get('file_name') or 'this attachment').name[:150]
                    await reply(f'Could not read {name}: its contents are not valid UTF-8 JSON. Send the question JSON file; the filename extension does not matter. Use /notes for PDFs or /image for diagrams.');return
            part=export_part(data)
            if part:
                context={k:state.get(k) for k in ('target_user_id','study_date','topic','quiz_kind')}
                def stage(current):
                    if any(current.get(k)!=v for k,v in context.items()):raise HTTPException(409,'Account/topic changed during upload. Select the intended topic and resend.')
                    current.update(quiz_id=None,pending_image=None,upload_mode='quiz')
                    staged=current.setdefault('import_parts',{})
                    staged[part[0]]=part[1]
                    return dict(staged)
                staged=await store.mutate(user,stage,admin=True)
                if 'questions' not in staged or 'answers' not in staged:
                    missing='answer export (.json or .json4)' if part[0]=='questions' else 'question export (.json)'
                    await reply(f'{part[0].capitalize()} file received for {state.get("target_alias","selected account")}. Send the matching {missing} next. Nothing is published yet.');return
                data=merge_exports(staged['questions'],staged['answers'],pyq=state.get('quiz_kind')=='pyq')
            bank=(validate_pyq if state.get('quiz_kind')=='pyq' and command!='/question' else validate_bank)(data,state['topic'],state['study_date'])
            upload_context={k:state.get(k) for k in ('target_user_id','study_date','topic','quiz_kind')}
            if state.get('target_user_id'):bank=scoped_quiz(bank,state['target_user_id'])
            await store.put_quiz(bank)
            fields={'upload_mode':'quiz','quiz_id':bank['id'],'import_parts':{},'pending_image':{'quiz_id':bank['id'],'index':0} if command=='/question' else None}
            def select_import(current):
                if any(current.get(k)!=v for k,v in upload_context.items()):raise HTTPException(409,'Account/topic changed. The completed draft stays in the original account; switch back and use /tests to select it.')
                current.update(fields)
            await store.mutate(user,select_import,admin=True)
            await reply(f'Saved {len(bank["questions"])} questions with explanations.\n{bank["topic"]} · {bank["study_date"]}\nID: {bank["id"]}\n'+
                ('Send its diagram now, then /open.' if command=='/question' else 'Use /images to send named diagrams, or /image Q12 for one. Use /open when ready. Daily practice opens the next day; PYQs open on their paper date.'));return
        await reply('Use /help for website admin commands. Questions are answered on the website.')
    except HTTPException as exc:
        await reply(str(exc.detail))
        if exc.status_code>=500: raise
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        await reply('Could not complete that action. Please check the upload format and database configuration, then try again.')
        raise HTTPException(503,'Admin action failed.')
