"""Read-only email diagnostics. Never prints keys, message bodies or draft subjects."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from app.config import BOT_TOKEN, ADMIN_USER_IDS
from app.web.store import Store

async def main():
    store=Store()
    async with httpx.AsyncClient(timeout=20) as client:
        async def read(url,**kwargs):
            for attempt in range(3):
                try:return await client.get(url,**kwargs)
                except httpx.TransportError:
                    if attempt==2:print('Connection unavailable for this check.');return None
        response=await read(f'https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo')
        if response is not None:
            info=response.json().get('result',{})
            print('Webhook update types:',info.get('allowed_updates','default'))
            print('Pending updates:',info.get('pending_update_count',0))
        response=await read(store.url+'/rest/v1/study_email_events',headers=store.headers(),params={'select':'status,last_error,created_at','order':'created_at.desc','limit':'5'})
        if response is not None:
            print('Outbox HTTP:',response.status_code)
            print('Recent delivery statuses:',response.json() if response.is_success else response.json().get('code'))
        for ident in ADMIN_USER_IDS-{0}:
            response=await read(store.url+'/rest/v1/study_admins',headers=store.headers(),params={'telegram_id':'eq.'+str(ident),'select':'data'})
            if response is not None and response.is_success:
                for row in response.json():
                    state=row['data'];draft=state.get('email_draft') or {}
                    print('Admin email state:',{'account':state.get('target_alias'),'upload_mode':state.get('upload_mode'),'has_draft':bool(draft),'send_requested':bool(draft.get('send_requested')),'html':bool(draft.get('html_body'))})
if __name__=='__main__':asyncio.run(main())
