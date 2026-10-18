"""Run AFTER deployment to switch the existing bot to website administration."""
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from app.config import BOT_TOKEN, WEBHOOK_SECRET, ADMIN_USER_IDS

async def main():
    url=os.getenv('APP_URL','').rstrip('/')
    if not url.startswith('https://') or not BOT_TOKEN or not ADMIN_USER_IDS:
        raise SystemExit('Set APP_URL=https://your-site.vercel.app, BOT_TOKEN and ADMIN_USER_ID in .env first.')
    async with httpx.AsyncClient(timeout=30) as client:
        health=await client.get(url+'/api/health')
        if health.status_code!=200 or health.json().get('status')!='ok':
            raise SystemExit('The new website API is not healthy. Webhook was not changed.')
        if url=='https://YOUR_SITE.vercel.app':raise SystemExit('Replace the APP_URL placeholder with your actual production URL.')
        probe=await client.post(url+'/api/telegram/webhook',json={},
            headers={'X-Telegram-Bot-Api-Secret-Token':WEBHOOK_SECRET})
        if probe.status_code!=200:raise SystemExit('Webhook secret check failed. Match BOT_TOKEN/WEBHOOK_SECRET locally and in Vercel. Webhook was not changed.')
        result=await client.post(f'https://api.telegram.org/bot{BOT_TOKEN}/setWebhook',json={
            'url':url+'/api/telegram/webhook','secret_token':WEBHOOK_SECRET,
            'allowed_updates':['message','callback_query'],'drop_pending_updates':False})
        if not result.is_success or not result.json().get('ok'):raise SystemExit('Could not update webhook. Check your bot credentials.')
        commands=[('start','Admin guide'),('email','Preview and send a custom email to both'),('account','Select my test account or Vishu'),('copyto','Copy quiz and notes to another account'),('topic','Set study day and upload topic'),('open','Open the selected test'),
            ('close','Close the selected test'),('tests','List uploaded tests'),('select','Select a test by ID'),
            ('bulk','Upload daily quiz JSON'),('pyq','Upload a full CSIR exam paper'),('images','Attach named diagrams in bulk'),('image','Attach a diagram to a question'),('question','Add a single question'),('status','Selected test status'),
            ('plan','Today’s study topic'),('notes','Upload PDFs/photos for a study date'),('done','Finish uploading notes'),('help','Admin guide')]
        menu=await client.post(f'https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands',json={'commands':[{'command':c,'description':d} for c,d in commands]})
        if not menu.is_success or not menu.json().get('ok'):print('Webhook updated; Telegram command menu could not be refreshed.')
        else:print('Website admin webhook and command menu are ready. Send /start in your private bot chat.')
        print('Telegram no longer posts quiz polls. Learners take tests on the website.')

if __name__=='__main__':asyncio.run(main())
