import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import database as db
from app.services import notion_sync as ns
from app.services.planner import plan_rows
from tests.test_tracking import running


class FakeNotion:
    """Stateful HTTP fake exercises request payloads, retries and stable row keys."""
    def __init__(self):
        self.blocks={'parent':[]};self.databases={};self.schemas={};self.pages={};self.calls=[]
        self.counter=0;self.timeout_after_create=False;self.fail_next_update=False

    def next_id(self):
        self.counter+=1;return f'id-{self.counter}'

    def request(self,request):
        assert request.headers['Notion-Version']=='2025-09-03'
        self.calls.append((request.method,request.url.path))
        path=request.url.path.removeprefix('/v1/');body=json.loads(request.content) if request.content else {}
        parts=path.split('/');method=request.method
        if parts[0]=='blocks' and method=='GET':
            return httpx.Response(200,json={'results':self.blocks.get(parts[1],[]),'has_more':False})
        if path=='pages' and method=='POST':
            pid=self.next_id();parent=body['parent']
            self.pages[pid]={'id':pid,'properties':body['properties'],'source':parent.get('data_source_id')}
            if 'page_id' in parent:
                title=body['properties']['title']['title'][0]['text']['content']
                self.blocks.setdefault(parent['page_id'],[]).append({'id':pid,'type':'child_page','child_page':{'title':title}})
                self.blocks[pid]=[]
            if self.timeout_after_create:
                self.timeout_after_create=False
                raise httpx.ReadTimeout('response lost',request=request)
            return httpx.Response(200,json=self.pages[pid])
        if parts[0]=='pages' and method=='PATCH':
            if self.fail_next_update:
                self.fail_next_update=False;return httpx.Response(503,json={'message':'unavailable'})
            # Empty properties must not be sent to update endpoints.
            assert body['properties']
            self.pages[parts[1]]['properties'].update(body['properties'])
            return httpx.Response(200,json=self.pages[parts[1]])
        if path=='databases' and method=='POST':
            did=self.next_id();sid=self.next_id()
            self.databases[did]={'id':did,'data_sources':[{'id':sid}]}
            self.schemas[sid]={'id':sid,'properties':{k:{**v,'type':next(iter(v))} for k,v in body['initial_data_source']['properties'].items()}}
            self.blocks[body['parent']['page_id']].append({'id':did,'type':'child_database','child_database':{'title':body['title'][0]['text']['content']}})
            return httpx.Response(200,json=self.databases[did])
        if parts[0]=='databases' and method=='GET':return httpx.Response(200,json=self.databases[parts[1]])
        if parts[0]=='data_sources' and len(parts)==2:
            if method=='PATCH':
                self.schemas[parts[1]]['properties'].update({k:{**v,'type':next(iter(v))} for k,v in body['properties'].items()})
            return httpx.Response(200,json=self.schemas[parts[1]])
        if parts[0]=='data_sources' and parts[-1]=='query':
            key=body['filter']['rich_text']['equals']
            rows=[p for p in self.pages.values() if p['source']==parts[1] and p['properties'].get('Key',{}).get('rich_text')==ns.rich(key)]
            return httpx.Response(200,json={'results':rows,'has_more':False})
        raise AssertionError((method,path,body))

    def page(self,source,key):
        return next(p for p in self.pages.values() if p['source']==source and p['properties']['Key']['rich_text']==ns.rich(key))


@pytest.mark.asyncio
async def test_setup_seeds_full_plan_and_is_repeatable():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        url=await ns.setup_hub(client,'parent')
        assert url.startswith('https://www.notion.so/')
        counts=(len(fake.pages),len(fake.databases))
        assert len(fake.databases)==4
        assert sum(p['source']==db.get_setting('notion_source:plan') for p in fake.pages.values())==56
        assert sum(p['source']==db.get_setting('notion_source:weekly') for p in fake.pages.values())==9
        plan=fake.page(db.get_setting('notion_source:plan'),'2026-10-16')
        plan['properties']['Study status']=ns.select('Done')
        await ns.setup_hub(client,'parent')
        assert (len(fake.pages),len(fake.databases))==counts
        assert plan['properties']['Study status']==ns.select('Done')


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_preserves_manual_fields():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client,'parent')
        running(2)
        db.record_answer('quiz','quiz-poll-0',1,False,123,datetime(2026,10,20,6,tzinfo=timezone.utc))
        db.record_answer('quiz','quiz-poll-1',0,True,123,datetime(2026,10,20,6,tzinfo=timezone.utc))
        assert db.complete_session('quiz')
        plan=fake.page(db.get_setting('notion_source:plan'),'2026-10-16')
        plan['properties'].update({'Study status':ns.select('Done'),'Minutes':ns.number(210),'Notes':ns.text('My own notes')})
        assert await ns.sync_results(client,'all')==1
        count=len(fake.pages)
        mistake=next(p for p in fake.pages.values() if p['source']==db.get_setting('notion_source:mistakes'))
        mistake['properties']['Review status']=ns.select('Revised')
        await ns.sync_results(client,'all')
        assert len(fake.pages)==count
        assert plan['properties']['Attempted']==ns.number(2)
        assert plan['properties']['Wrong']==ns.number(1)
        assert plan['properties']['Minutes']==ns.number(210)
        assert plan['properties']['Notes']==ns.text('My own notes')
        assert plan['properties']['Study status']==ns.select('Done')
        assert mistake['properties']['Review status']==ns.select('Revised')
        result=fake.page(db.get_setting('notion_source:results'),'quiz')
        assert result['properties']['Study day']['relation']==[{'id':plan['id']}]


@pytest.mark.asyncio
async def test_uncertain_create_resumes_without_duplicate():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        fake.timeout_after_create=True
        with pytest.raises(ns.NotionError):
            await client.upsert('source','stable-key',{'Name':{'title':ns.rich('Quiz')}})
        assert len(fake.pages)==1
        await client.upsert('source','stable-key',{'Name':{'title':ns.rich('Quiz')}})
        assert len(fake.pages)==1


@pytest.mark.asyncio
async def test_failed_sync_retains_local_answers_and_can_resume():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client,'parent');running(1)
        db.record_answer('quiz','quiz-poll-0',1,False,123)
        await ns.sync_results(client,'all')
        fake.fail_next_update=True
        with pytest.raises(ns.NotionError):await ns.sync_results(client,'all')
        assert db.load_session('quiz').wrong==1
        await ns.sync_results(client,'all')
        assert len([p for p in fake.pages.values() if p['source']==db.get_setting('notion_source:results')])==1


@pytest.mark.asyncio
async def test_today_sync_includes_yesterdays_quiz_answered_today():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client,'parent')
        s=running(1)
        s.started_at=datetime(2026,10,16,6,tzinfo=timezone.utc);db.save_session(s)
        db.record_answer('quiz','quiz-poll-0',1,False,123,datetime(2026,10,17,6,tzinfo=timezone.utc))
        assert await ns.sync_results(client,'today',date(2026,10,17))==1
        row=fake.page(db.get_setting('notion_source:results'),'quiz')
        assert row['properties']['Wrong']==ns.number(1)


@pytest.mark.asyncio
async def test_setup_recovers_hub_when_response_was_lost():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        fake.timeout_after_create=True
        with pytest.raises(ns.NotionError):await ns.setup_hub(client,'parent')
        await ns.setup_hub(client,'parent')
        assert len(fake.blocks['parent'])==1
        assert len(fake.databases)==4


@pytest.mark.asyncio
async def test_schema_mismatch_does_not_rewrite_user_database():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client,'parent')
        source=db.get_setting('notion_source:plan')
        fake.schemas[source]['properties']['Minutes']={'type':'rich_text','rich_text':{}}
        with pytest.raises(ns.NotionError,match='schema differs'):await ns.setup_hub(client,'parent')
        assert fake.schemas[source]['properties']['Minutes']['type']=='rich_text'


def test_no_notion_token_is_a_clear_setup_error():
    with pytest.raises(ns.NotionError,match='NOTION_TOKEN'):ns.NotionClient('')


@pytest.mark.asyncio
async def test_partial_setup_cannot_sync_incomplete_plan():
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client,'parent')
        db.set_setting('notion_setup_complete',False)
        running(1)
        with pytest.raises(ns.NotionError,match='notion_setup'):await ns.sync_results(client,'all')


@pytest.mark.asyncio
async def test_cancelled_quiz_attempts_remain_in_study_day_totals():
    from app.models import SessionStatus
    fake=FakeNotion()
    async with ns.NotionClient('test',httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client,'parent');running(2)
        db.record_answer('quiz','quiz-poll-0',1,False,123)
        db.update_session_status('quiz',SessionStatus.CANCELLED)
        await ns.sync_results(client,'all')
        plan=fake.page(db.get_setting('notion_source:plan'),'2026-10-16')
        assert plan['properties']['Attempted']==ns.number(1)
        assert plan['properties']['Wrong']==ns.number(1)


@pytest.mark.asyncio
async def test_runtime_binds_existing_live_manifest_without_new_hub(tmp_path,monkeypatch):
    fake=FakeNotion()
    base_request=fake.request
    def request(req):
        if req.method=='GET' and req.url.path.startswith('/v1/pages/'):
            return httpx.Response(200,json=fake.pages[req.url.path.rsplit('/',1)[1]])
        return base_request(req)
    async with ns.NotionClient('test',httpx.MockTransport(request)) as client:
        await ns.setup_hub(client,'parent')
        hub=db.get_setting('notion_hub')
        config={'hub_id':hub,'databases':{key:db.get_setting('notion_database:'+key) for key in ns.schema()}}
        manifest=tmp_path/'workspace.json';manifest.write_text(json.dumps(config))
        monkeypatch.setattr(ns,'WORKSPACE_CONFIG_PATH',manifest)
        before=(len(fake.pages),len(fake.databases))
        plan=fake.page(db.get_setting('notion_source:plan'),'2026-10-16')
        plan['properties']['Study status']=ns.select('Done')
        with db.get_conn() as conn:conn.execute('DELETE FROM settings')
        await ns.setup_hub(client)
        assert db.get_setting('notion_hub')==hub
        assert (len(fake.pages),len(fake.databases))==before
        assert plan['properties']['Study status']==ns.select('Done')
        assert db.get_setting('notion_setup_complete') is True


@pytest.mark.asyncio
async def test_simple_profile_never_recreates_removed_trackers(tmp_path, monkeypatch):
    workspace = tmp_path / 'simple-workspace.json'
    workspace.write_text(json.dumps({'profile': 'simple'}))
    monkeypatch.setattr(ns, 'WORKSPACE_CONFIG_PATH', workspace)
    fake = FakeNotion()
    async with ns.NotionClient('test', httpx.MockTransport(fake.request)) as client:
        await ns.setup_hub(client, 'parent')
        assert len(fake.databases) == 3
        assert set(ns.schema()) == {'plan', 'results', 'questions'}
        source = db.get_setting('notion_source:plan')
        assert 'Book pages' not in fake.schemas[source]['properties']
        assert 'Planned pages' not in fake.schemas[source]['properties']
        running(1)
        db.record_answer('quiz', 'quiz-poll-0', 1, False, 123)
        await ns.sync_results(client, 'all')
        question_source = db.get_setting('notion_source:questions')
        assert len([p for p in fake.pages.values() if p['source'] == question_source]) == 1
        assert db.get_setting('notion_source:mistakes') is None
        assert db.get_setting('notion_source:weekly') is None
        assert len(fake.databases) == 3
        await ns.sync_results(client, 'all')
        assert len([p for p in fake.pages.values() if p['source'] == question_source]) == 1
