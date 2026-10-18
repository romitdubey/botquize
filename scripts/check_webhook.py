"""Safe webhook diagnostics. --repair switches to APP_URL after a secret check."""
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from app.config import BOT_TOKEN, WEBHOOK_SECRET, ADMIN_USER_IDS

async def main():
    url=os.getenv('APP_URL','').rstrip('/')
    if not BOT_TOKEN or not url.startswith('https://'):
        raise SystemExit('Set BOT_TOKEN and APP_URL=https://your-production-site.vercel.app in .env.')
    async with httpx.AsyncClient(timeout=20) as client:
        info=(await client.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo')).json()
        if not info.get('ok'):raise SystemExit('Telegram rejected the configured bot token.')
        status=info['result'];target=url+'/api/telegram/webhook'
        print('Registered webhook:',status.get('url') or '(none)',flush=True)
        print('Expected webhook:',target,flush=True)
        allowed=status.get('allowed_updates',[])
        print('Allowed update types:',allowed or '(Telegram default)',flush=True)
        callbacks='callback_query' in allowed
        if allowed and not callbacks:print('Button clicks are disabled. Run with --repair to enable Send/Cancel buttons.',flush=True)
        print('Pending updates:',status.get('pending_update_count',0),flush=True)
        print('Last delivery error:',status.get('last_error_message') or 'none',flush=True)
        print('Admin IDs configured:',bool(ADMIN_USER_IDS-{0}),flush=True)
        health=await client.get(url+'/api/health')
        print('Production health:',health.status_code,flush=True)
        # Empty update validates the secret without sending a message or changing data.
        probe=await client.post(target,json={},headers={'X-Telegram-Bot-Api-Secret-Token':WEBHOOK_SECRET})
        print('Webhook secret check:',probe.status_code,flush=True)
        if health.status_code!=200 or probe.status_code!=200:
            raise SystemExit('Webhook not changed. Check production URL, deployment protection and matching BOT_TOKEN/WEBHOOK_SECRET.')
        if '--repair' in sys.argv:
            result=await client.post(f'https://api.telegram.org/bot{BOT_TOKEN}/setWebhook',json={
                'url':target,'secret_token':WEBHOOK_SECRET,'allowed_updates':['message','callback_query'],
                'drop_pending_updates':False})
            if not result.is_success or not result.json().get('ok'):raise SystemExit('Could not update webhook.')
            print('Webhook switched to the verified production backend. Existing pending updates retained.',flush=True)
        elif status.get('url')!=target or (allowed and not callbacks):
            print('Run this script with --repair to fix the host or enable button-click updates.',flush=True)
if __name__=='__main__':asyncio.run(main())
