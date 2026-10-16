"""Private Telegram administration only: never sends quiz polls or channel posts."""
import json
import os
import uuid
from pathlib import Path
from datetime import date
import httpx
from fastapi import HTTPException
from app.config import BOT_TOKEN, ADMIN_USER_IDS
from app.web.domain import validate_bank, validate_pyq, today
from app.web.daily import scheduled_day, release_day
from app.web.attachments import attachment_number, resolve_question, question_number
from app.services.planner import plan_rows

HELP='''🌿 Study desk — admin controls

/topic 2026-10-16 | Enzymes
Set the study day + topic for your next JSON upload. Then send your usual JSON file. It is saved as a draft; all explanations are preserved.

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

async def handle_update(update,store):
    message=update.get('message')
    if not message: return # Old inline buttons/poll answers never publish anything.
    user=message.get('from',{}).get('id');chat=message.get('chat',{})
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
        if command in ('/topic','/pyq'):
            if '|' not in arg: await reply(f'Use {command} YYYY-MM-DD | Topic or paper title');return
            day,topic=map(str.strip,arg.split('|',1))
            try: date.fromisoformat(day)
            except ValueError: await reply('Use a date like 2026-10-16.');return
            if not topic or len(topic)>500: await reply('Please provide a topic under 500 characters.');return
            await change(study_date=day,topic=topic,upload_mode='quiz',quiz_kind='pyq' if command=='/pyq' else 'daily',pending_image=None)
            await reply(f'Next upload: {topic}\nStudy day: {day}\n'+('Send full PYQ JSON with sections A (20 questions), B (50), C (75). Four options per question; correct_option is zero based. Use unique question_number values 1–145.' if command=='/pyq' else 'Send daily JSON with a questions array. Any question count; 10 MB file limit. Practice has no deadline.')+'\nThen /images for diagrams, /open when ready.');return
        if command=='/bulk':
            await change(upload_mode='quiz',pending_image=None)
            await reply(('PYQ mode: send JSON sections A (20), B (50), C (75).' if state.get('quiz_kind')=='pyq' else 'Daily mode: send JSON with a questions array; any question count (10 MB file limit).')+' Include question_number, question, options, correct_option and explanation. /topic DATE | Topic selects daily mode; /pyq DATE | Title selects full exam. Then /images to attach named diagrams.');return
        if command=='/images':
            if not state.get('quiz_id'):await reply('Upload a JSON paper or /select a test first.');return
            quiz=await store.quiz(state['quiz_id'])
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
            quiz=await store.quiz(arg)
            if quiz.get('owner_id'): await reply('Select a daily test, not a personal retry.');return
            await change(quiz_id=quiz['id'],study_date=quiz['study_date'],topic=quiz['topic'],quiz_kind=quiz['kind'],pending_image=None,upload_mode='quiz')
            await reply(f'Selected {quiz["topic"]}.');return
        if command in ('/open','/close'):
            if not state.get('quiz_id'): await reply('Upload a JSON file or /select a test first.');return
            await store.update_quiz(state['quiz_id'],{'status':'open' if command=='/open' else 'closed'})
            link=os.getenv('APP_URL','').rstrip('/')
            await reply((f'Test approved. Opens on {release_day(await store.quiz(state["quiz_id"])):%d %b %Y}. ' if command=='/open' else 'Test closed for new attempts. ')+link);return
        if command=='/tests':
            rows=await store.quizzes(kind='in.(daily,pyq)',order='created_at.desc',limit='12')
            await reply('\n\n'.join(f'{q["study_date"]} · {q["topic"]}\n{q["status"]} · {len(q["questions"])} questions\n{q["id"]}' for q in rows) or 'No uploads yet.');return
        if command=='/status':
            quiz=await store.quiz(state['quiz_id']) if state.get('quiz_id') else None
            await reply(f'Upload label: {state.get("study_date","not set")} · {state.get("topic","not set")}\n'+
                (f'Selected: {quiz["topic"]}\n{quiz["status"]} · {len(quiz["questions"])} questions\nID: {quiz["id"]}' if quiz else 'No test selected.'));return
        if command=='/plan':
            row=next((r for r in plan_rows() if r['date']==today().isoformat()),None)
            await reply(f'{today()}: '+(row['topic'] if row else 'No scheduled topic today.'));return
        if command=='/image':
            if not state.get('quiz_id'): await reply('Upload or select a test first.');return
            quiz=await store.quiz(state['quiz_id'])
            index=resolve_question(quiz['questions'],arg)
            label=question_number(quiz['questions'][index],index)
            await change(upload_mode='quiz',pending_image={'quiz_id':quiz['id'],'index':index})
            await reply(f'Send a photo or PNG/JPEG/WebP file for question {label} (array item {index+1}):\n{quiz["questions"][index]["question"][:500]}');return
        document=message.get('document',{})
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
            note_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'study-note:{day}:{source}'))
            path=f'{day}/{note_id}.{extension}'
            filename=Path(file.get('file_name') or f'Notes.{extension}').name[:240]
            await store.upload_note(path,content,mime)
            await store.put_note({'id':note_id,'study_date':day,'title':state.get('notes_title') or filename,
                'filename':filename,'mime':mime,'path':path})
            await reply(f'Notes saved for {day}: {filename}\nYou can send another PDF/photo, or /done.');return
        if is_photo:
            pending=state.get('pending_image')
            if not pending:
                label=attachment_number(message.get('caption',''),document.get('file_name',''))
                if not state.get('quiz_id') or not label:
                    await reply('Use /image Q12 first, or send a file named Q12.png / a photo captioned Q12 after selecting your JSON paper.');return
                bank=await store.quiz(state['quiz_id'])
                pending={'quiz_id':bank['id'],'index':resolve_question(bank['questions'],label)}
            file=message['photo'][-1] if message.get('photo') else document
            content=await download(file['file_id'],10*1024*1024)
            if content.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','jpg'
            elif content.startswith(b'\x89PNG\r\n\x1a\n'):mime,extension='image/png','png'
            elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime,extension='image/webp','webp'
            else: await reply('Please send a PNG, JPEG or WebP image.');return
            quiz=await store.quiz(pending['quiz_id']);index=pending['index']
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
                if not document.get('file_name','').lower().endswith('.json'):await reply('Upload a .json file, or use /image for a diagram.');return
                if document.get('file_size',0)>10*1024*1024:await reply('JSON limit is 10 MB.');return
                raw=await download(document['file_id'],10*1024*1024)
                try:data=json.loads(raw.decode('utf-8-sig'))
                except (ValueError,UnicodeError):await reply('This file is not valid UTF-8 JSON.');return
            bank=(validate_pyq if state.get('quiz_kind')=='pyq' and command!='/question' else validate_bank)(data,state['topic'],state['study_date'])
            await store.put_quiz(bank)
            fields={'upload_mode':'quiz','quiz_id':bank['id'],'pending_image':{'quiz_id':bank['id'],'index':0} if command=='/question' else None}
            await change(**fields)
            await reply(f'Saved {len(bank["questions"])} questions with explanations.\n{bank["topic"]} · {bank["study_date"]}\nID: {bank["id"]}\n'+
                ('Send its diagram now, then /open.' if command=='/question' else 'Use /images to send named diagrams, or /image Q12 for one. Use /open when ready. Daily practice opens the next day; PYQs open on their paper date.'));return
        await reply('Use /help for website admin commands. Questions are answered on the website.')
    except HTTPException as exc:
        await reply(str(exc.detail))
        if exc.status_code>=500: raise
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        await reply('Could not complete that action. Please check the upload format and database configuration, then try again.')
        raise HTTPException(503,'Admin action failed.')
