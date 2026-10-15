"""Supabase REST storage. Private tables; service credentials never reach the browser."""
import asyncio
import copy
import os
import httpx
from fastapi import HTTPException

class Store:
    def __init__(self):
        self.url = os.getenv('SUPABASE_URL', '').rstrip('/')
        self.key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

    def headers(self):
        # New sb_secret_ keys belong in apikey, not in a JWT Bearer header.
        return {'apikey':self.key, **({'Authorization':'Bearer '+self.key} if self.key.startswith('eyJ') else {})}

    async def request(self, method, resource, *, params=None, body=None, headers=None):
        if not self.url or not self.key:
            raise HTTPException(503, 'Study storage is not configured yet.')
        auth = {**self.headers(), 'Prefer': 'return=representation', **(headers or {})}
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(method, self.url+'/rest/v1/'+resource,
                                            params=params, json=body, headers=auth)
        if response.status_code >= 400:
            # Never return upstream messages/credentials to clients or Telegram.
            raise HTTPException(503, 'Study storage is temporarily unavailable. Check the database setup.')
        return response.json() if response.content else None

    async def quizzes(self, **filters):
        return await self.request('GET', 'study_quizzes', params={'select':'*', 'order':'study_date.asc,created_at.asc', **filters})

    async def quiz(self, quiz_id):
        rows = await self.quizzes(id='eq.'+str(quiz_id))
        if not rows: raise HTTPException(404, 'Test not found.')
        return rows[0]

    async def put_quiz(self, row):
        return (await self.request('POST', 'study_quizzes', body=row,
                params={'on_conflict':'id'}, headers={'Prefer':'resolution=ignore-duplicates,return=representation'}))

    async def update_quiz(self, quiz_id, fields):
        return await self.request('PATCH', 'study_quizzes', params={'id':'eq.'+str(quiz_id)}, body=fields)

    async def state(self, user_id, admin=False):
        table, key = ('study_admins', 'telegram_id') if admin else ('study_learners', 'user_id')
        rows = await self.request('GET', table, params={key:'eq.'+str(user_id), 'select':'data,version'})
        if rows: return rows[0]
        await self.request('POST', table, body={key:user_id,'data':{},'version':0},
                           params={'on_conflict':key}, headers={'Prefer':'resolution=ignore-duplicates,return=minimal'})
        rows = await self.request('GET', table, params={key:'eq.'+str(user_id),'select':'data,version'})
        return rows[0]

    async def mutate(self, user_id, action, admin=False):
        """Compare-and-swap prevents double submission/two devices losing updates."""
        table, key = ('study_admins','telegram_id') if admin else ('study_learners','user_id')
        for _ in range(8):
            current = await self.state(user_id, admin)
            data = copy.deepcopy(current['data'])
            result = action(data)
            rows = await self.request('PATCH', table,
                params={key:'eq.'+str(user_id),'version':'eq.'+str(current['version'])},
                body={'data':data,'version':current['version']+1})
            if rows: return result
            await asyncio.sleep(.025)
        raise HTTPException(409, 'Another device updated this session. Please try again.')

    async def upload_image(self, path, content, mime):
        if not self.url or not self.key: raise HTTPException(503, 'Storage is not configured.')
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(self.url+'/storage/v1/object/question-images/'+path,
                content=content, headers={**self.headers(), 'Content-Type':mime, 'x-upsert':'true'})
        if response.status_code >= 400: raise HTTPException(503, 'Image storage is unavailable.')
        return path

    async def image_urls(self, paths):
        paths=list(set(paths))
        if not paths: return {}
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.post(self.url+'/storage/v1/object/sign/question-images',
                json={'expiresIn':28800,'paths':paths}, headers=self.headers())
        if response.status_code >= 400: raise HTTPException(503, 'Could not load question diagrams. Please try again.')
        return {item['path']:self.url+'/storage/v1'+item['signedURL']
                for item in response.json() if item.get('path') and item.get('signedURL')}
