"""Private Telegram administration only: never sends quiz polls or channel posts."""
import io
import json
import os
from datetime import date, timedelta
import httpx
from fastapi import HTTPException
from app.config import BOT_TOKEN, ADMIN_USER_IDS
from app.web.domain import validate_bank, today
from app.services.planner import plan_rows

HELP='''🌿 Study desk — admin controls

/topic 2026-10-16 | Enzymes
Set the study day + topic for your next JSON upload. Then send your usual JSON file. It is saved as a draft; all explanations are preserved.

/open — open the selected test on the website
/close — hide it from new attempts
/tests — list recent tests with IDs
/select TEST-ID — select an older test
/image 12 — next photo attaches to question 12 of the selected test
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
    try:
        state=(await store.state(user,admin=True))['data']
        text=message.get('text','').strip()
        parts=text.split(maxsplit=1);command=parts[0].split('@')[0].lower() if parts else ''; arg=parts[1].strip() if len(parts)>1 else ''
        async def change(**fields):
            def action(data): data.update(fields)
            await store.mutate(user,action,admin=True)
            state.update(fields)
        if command in ('/start','/help'):
            await reply(HELP);return
        if command=='/topic':
            if '|' not in arg: await reply('Use /topic YYYY-MM-DD | Topic name');return
            day,topic=map(str.strip,arg.split('|',1))
            try: date.fromisoformat(day)
            except ValueError: await reply('Use a date like 2026-10-16.');return
            if not topic or len(topic)>500: await reply('Please provide a topic under 500 characters.');return
            await change(study_date=day,topic=topic)
            await reply(f'Next upload: {topic}\nStudy day: {day}\nSend your JSON; /open releases it when you are ready.');return
        if command=='/select':
            quiz=await store.quiz(arg)
            if quiz.get('owner_id'): await reply('Select a daily test, not a personal retry.');return
            await change(quiz_id=quiz['id'],pending_image=None)
            await reply(f'Selected {quiz["topic"]}.');return
        if command in ('/open','/close'):
            if not state.get('quiz_id'): await reply('Upload a JSON file or /select a test first.');return
            await store.update_quiz(state['quiz_id'],{'status':'open' if command=='/open' else 'closed'})
            link=os.getenv('APP_URL','').rstrip('/')
            await reply(('Test is open on the website. ' if command=='/open' else 'Test closed for new attempts. ')+link);return
        if command=='/tests':
            rows=await store.quizzes(kind='eq.daily',order='created_at.desc',limit='12')
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
            try: number=int(arg)
            except ValueError: await reply('Use /image 12, then send the photo.');return
            if not 1<=number<=len(quiz['questions']): await reply('That question number is outside this test.');return
            await change(pending_image={'quiz_id':quiz['id'],'index':number-1})
            await reply(f'Send a photo or PNG/JPEG/WebP file for question {number}:\n{quiz["questions"][number-1]["question"][:500]}');return
        document=message.get('document',{})
        is_photo=bool(message.get('photo')) or document.get('mime_type','').startswith('image/')
        if is_photo:
            pending=state.get('pending_image')
            if not pending: await reply('Use /image QUESTION-NUMBER first, then send the image.');return
            file=message['photo'][-1] if message.get('photo') else document
            content=await download(file['file_id'],10*1024*1024)
            if content.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','jpg'
            elif content.startswith(b'\x89PNG\r\n\x1a\n'):mime,extension='image/png','png'
            elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime,extension='image/webp','webp'
            else: await reply('Please send a PNG, JPEG or WebP image.');return
            quiz=await store.quiz(pending['quiz_id']);index=pending['index']
            path=f'{quiz["id"]}/{index+1}-{file.get("file_unique_id",str(update.get("update_id",0)))}.{extension}'
            await store.upload_image(path,content,mime)
            quiz['questions'][index].update(image_path=path,image_url='')
            await store.update_quiz(quiz['id'],{'questions':quiz['questions']})
            await change(pending_image=None)
            await reply(f'Diagram attached to question {index+1}. New attempts will include it.');return
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
            bank=validate_bank(data,state['topic'],state['study_date'])
            await store.put_quiz(bank)
            fields={'quiz_id':bank['id'],'pending_image':{'quiz_id':bank['id'],'index':0} if command=='/question' else None}
            await change(**fields)
            await reply(f'Saved {len(bank["questions"])} questions with explanations.\n{bank["topic"]} · {bank["study_date"]}\nID: {bank["id"]}\n'+
                ('Send its diagram now, then /open.' if command=='/question' else 'Use /image 12 to attach a diagram. Use /open to release this test.'));return
        await reply('Use /help for website admin commands. Questions are answered on the website.')
    except HTTPException as exc:
        await reply(str(exc.detail))
        if exc.status_code>=500: raise
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        await reply('Could not complete that action. Please check the upload format and database configuration, then try again.')
        raise HTTPException(503,'Admin action failed.')
