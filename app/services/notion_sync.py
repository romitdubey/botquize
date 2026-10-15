"""Explicit, repeatable Notion setup and sync. Never called by /result or answers.

Manual study fields and notes belong to the learner; score sync never writes them.
API docs: https://developers.notion.com/docs/upgrade-guide-2025-09-03
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app import database as db
from app.config import NOTION_TOKEN, NOTION_PARENT_PAGE_ID, NOTION_API_VERSION, STUDY_TIMEZONE
from app.services.planner import plan_rows, date_window, today

SYNC_LOCK = asyncio.Lock()
HUB_TITLE = 'CSIR Life Science - Study Hub'
WORKSPACE_CONFIG_PATH = Path(__file__).parent.parent / 'data' / 'notion_workspace.json'


def rich(value):
    text=str(value)
    return [{'type':'text','text':{'content':text[i:i+1900]}} for i in range(0,min(len(text),9500),1900)]


def text(value): return {'rich_text':rich(value)}
def number(value): return {'number':value}
def select(value): return {'select':{'name':value}}
def day(value): return {'date':{'start':value}}


def _full_schema():
    key={'Name':{'title':{}},'Key':{'rich_text':{}}}
    return {
      'plan': ('Daily Study Plan', {**key,'Date':{'date':{}},'Week':{'rich_text':{}},
        'Part':{'select':{}},'Kind':{'select':{}},'Book pages':{'rich_text':{}},'Planned pages':{'number':{}},
        'Study %':{'formula':{'expression':'if(prop("Planned pages") > 0, min(100, 100 * prop("Studied pages") / prop("Planned pages")), 0)'}},
        'Study status':{'select':{'options':[{'name':x} for x in ['Not started','In progress','Done','Needs revision']]}},
        'Studied pages':{'number':{}},'Minutes':{'number':{}},'Notes':{'rich_text':{}},
        **{x:{'number':{}} for x in ['Book questions','Attempted','Correct','Wrong','Remaining','Accuracy','Revision attempted','Revision correct']},
        'Last synced':{'date':{}}}),
      'results': ('Quiz Results', {**key,'Topic':{'rich_text':{}},'Study date':{'date':{}},'Kind':{'select':{}},
        'Learner ID':{'rich_text':{}},'Quiz status':{'select':{}},
        **{x:{'number':{}} for x in ['Total','Attempted','Correct','Wrong','Remaining','Accuracy']},
        'Started':{'date':{}},'Last synced':{'date':{}}}),
      'mistakes': ('Wrong Question Bank', {**key,'Topic':{'rich_text':{}},'Question':{'rich_text':{}},
        'Options':{'rich_text':{}},'Correct answer':{'rich_text':{}},'Previous answer':{'rich_text':{}},
        'Explanation':{'rich_text':{}},'Image':{'url':{}},'Last wrong':{'date':{}},'Wrong attempts':{'number':{}},
        'Review status':{'select':{'options':[{'name':x} for x in ['To retry','Revised','Needs help']]}},
        'Notes':{'rich_text':{}}}),
      'weekly': ('Weekly Review', {**key,'Week start':{'date':{}},
        **{x:{'number':{}} for x in ['Attempted','Correct','Wrong','Accuracy','Revision attempted','Revision correct','Unique mistakes']},
        'PYQ score':{'number':{}},'Mock score':{'number':{}},'Weak topics':{'rich_text':{}},
        'Monday retry done':{'checkbox':{}},'Last synced':{'date':{}}})}


def schema():
    """Keep removed Notion trackers out of future setup/sync operations."""
    definitions = _full_schema()
    workspace = json.loads(WORKSPACE_CONFIG_PATH.read_text()) if WORKSPACE_CONFIG_PATH.exists() else {}
    if workspace.get('profile') != 'simple':
        return definitions
    return {
        'plan': ('Schedule', {name: definitions['plan'][1][name] for name in
            ('Name', 'Key', 'Date', 'Part', 'Kind', 'Study status', 'Minutes', 'Notes')}),
        'results': ('Results', definitions['results'][1]),
        'questions': ('Questions', {
            'Name': {'title': {}}, 'Key': {'rich_text': {}}, 'Topic': {'rich_text': {}},
            'Question': {'rich_text': {}}, 'Options': {'rich_text': {}}, 'Study date': {'date': {}},
            'Question status': {'select': {'options': [{'name': 'Not attempted'}, {'name': 'Attempted'}]}}
        }),
    }


class NotionError(RuntimeError): pass


class NotionClient:
    def __init__(self,token=None,transport=None):
        self.token=token if token is not None else NOTION_TOKEN
        if not self.token:
            raise NotionError('Set NOTION_TOKEN in the deployment environment and connect the parent page to that integration. Do not send the token in Telegram.')
        self.http=httpx.AsyncClient(base_url='https://api.notion.com/v1/',timeout=30,
            headers={'Authorization':f'Bearer {self.token}','Notion-Version':NOTION_API_VERSION},transport=transport)

    async def __aenter__(self):return self
    async def __aexit__(self,*args):await self.http.aclose()

    async def request(self,method,path,**kwargs):
        # Retry only explicit rate limits. An uncertain create is recovered by Key on the next invocation.
        for attempt in range(4):
            try: response=await self.http.request(method,path,**kwargs)
            except httpx.HTTPError as exc:
                raise NotionError('Notion connection failed. Local answers are safe; retry the same command to resume.') from exc
            if response.status_code==429 and attempt<3:
                try:delay=min(max(float(response.headers.get('Retry-After','1')),1),30)
                except ValueError:delay=2
                await asyncio.sleep(delay);continue
            if response.is_error:
                # Do not expose tokens, request headers, or user data through Telegram/logging.
                raise NotionError(f'Notion returned HTTP {response.status_code}. Check integration access and database setup, then retry. Successful rows are retained.')
            return response.json()

    async def children(self,parent):
        rows=[];cursor=None
        while True:
            params={'page_size':100}
            if cursor:params['start_cursor']=cursor
            payload=await self.request('GET',f'blocks/{parent}/children',params=params)
            rows.extend(payload['results'])
            if not payload.get('has_more'):return rows
            cursor=payload['next_cursor']

    async def find(self,source,key):
        payload=await self.request('POST',f'data_sources/{source}/query',json={
            'filter':{'property':'Key','rich_text':{'equals':key}},'page_size':2})
        rows=payload['results']
        if len(rows)>1:raise NotionError('Duplicate tracker keys found. Resolve duplicate rows before syncing.')
        return rows[0]['id'] if rows else None

    async def upsert(self,source,key,properties,initial=None):
        # Query the remote stable key even after restarts or an ambiguous create response.
        page_id=await self.find(source,key)
        if page_id and properties:
            await self.request('PATCH',f'pages/{page_id}',json={'properties':properties})
        elif not page_id:
            props={**(initial or {}),**properties,'Key':text(key)}
            row=await self.request('POST','pages',json={'parent':{'type':'data_source_id','data_source_id':source},'properties':props})
            page_id=row['id']
        db.set_notion_link(source,key,page_id)
        return page_id


async def setup_hub(client,parent=None):
    workspace = json.loads(WORKSPACE_CONFIG_PATH.read_text()) if WORKSPACE_CONFIG_PATH.exists() else {}
    parent=parent or NOTION_PARENT_PAGE_ID or workspace.get('hub_id')
    linked_workspace = workspace if parent == workspace.get('hub_id') else {}
    if not parent:raise NotionError('Set NOTION_PARENT_PAGE_ID to the parent page shared with the bot integration.')
    configured=db.get_setting('notion_parent')
    if configured and configured!=parent:
        raise NotionError('This database is already linked to another Notion parent. Use the existing parent or a separate local database.')
    db.set_setting('notion_parent',parent)
    db.set_setting('notion_setup_complete',False)
    hub=db.get_setting('notion_hub')
    if not hub and linked_workspace:
        # Reuse the hub already created through the connected Notion app.
        # The bot's own token must independently prove access before linking it.
        await client.request('GET', f'pages/{parent}')
        hub = parent
        db.set_setting('notion_hub', hub)
    if not hub:
        # Recover only the explicitly named hub within the chosen parent, not arbitrary workspace pages.
        matches=[b['id'] for b in await client.children(parent) if b['type']=='child_page' and b['child_page']['title']==HUB_TITLE]
        if len(matches)>1:raise NotionError('Multiple study hubs found under the parent. Choose one before setup.')
        if matches:hub=matches[0]
        else:
            instructions=[
              'Plan: 16 Oct - 10 Dec 2026. First coverage ends 26 Nov; then consolidate mistakes. This covers only the five supplied book sections.',
              'Learner updates Study status, Studied pages, Minutes and Notes in Daily Study Plan. Bot sync updates quiz fields only and never overwrites these manual fields.',
              'Weekdays: study the planned topic; next day solve its book MCQs. Saturday: full PYQ + analysis. Sunday: paid mock + analysis. Monday: retry last week\'s wrong questions.',
              'Telegram: /topic YYYY-MM-DD | Topic before upload; /result shows only; /sync updates Notion; /wrong lastweek exports Monday\'s revision JSON. Re-upload that JSON to publish it.',
              'Use Weekly Review to enter PYQ/mock scores, weak topics and Monday retry completion. Wrong Question Bank keeps historical mistakes; original scores are never replaced by retry scores.',
              'Useful views to add: calendar by Date; Study status board; today/date filter; Part filter; and Week filter. Views are not access restrictions. Share this hub with your friend using Notion Share > Invite > Can edit.',
              'Database values come from explicit /sync snapshots, not live answer-by-answer updates. Exam date must be checked against the official notice; 10 Dec is the preparation target.'
            ]
            payload=await client.request('POST','pages',json={'parent':{'type':'page_id','page_id':parent},
                'properties':{'title':{'title':rich(HUB_TITLE)}},'children':[
                  {'object':'block','type':'paragraph','paragraph':{'rich_text':rich(t)}} for t in instructions]})
            hub=payload['id']
        db.set_setting('notion_hub',hub)
    sources={}; existing=await client.children(hub)
    for name,(title,properties) in schema().items():
        database=db.get_setting('notion_database:'+name) or linked_workspace.get('databases', {}).get(name)
        if not database:
            matches=[b['id'] for b in existing if b['type']=='child_database' and b['child_database']['title']==title]
            if len(matches)>1:raise NotionError(f'Multiple {title} databases found; resolve before retrying setup.')
            if matches:database=matches[0]
            else:
                row=await client.request('POST','databases',json={'parent':{'type':'page_id','page_id':hub},
                  'title':rich(title),'is_inline':False,'initial_data_source':{'properties':properties}})
                database=row['id']
            db.set_setting('notion_database:'+name,database)
        db.set_setting('notion_database:'+name,database)
        info=await client.request('GET',f'databases/{database}')
        if len(info.get('data_sources',[]))!=1:raise NotionError(f'{title} needs exactly one configured data source.')
        source=info['data_sources'][0]['id']
        actual=await client.request('GET',f'data_sources/{source}')
        if any(k not in actual['properties'] or actual['properties'][k]['type']!=next(iter(v)) for k,v in properties.items()):
            raise NotionError(f'{title} schema differs from the expected tracker. Existing data was left unchanged.')
        sources[name]=source;db.set_setting('notion_source:'+name,source)
    # Create relation targets only after all data sources exist.
    results_schema=await client.request('GET',f'data_sources/{sources["results"]}')
    if 'Study day' not in results_schema['properties']:
        await client.request('PATCH',f'data_sources/{sources["results"]}',json={'properties':{
            'Study day':{'relation':{'data_source_id':sources['plan'],'single_property':{}}}}})
    else:
        relation=results_schema['properties']['Study day']
        if relation['type']!='relation' or relation['relation'].get('data_source_id')!=sources['plan']:
            raise NotionError('Quiz Results has a Study day relation pointing elsewhere. No existing relation was changed.')
    for row in plan_rows():
        date_key = row['date']
        initial = {
            'Name': {'title': rich(row['topic'])}, 'Date': day(date_key), 'Week': text(row['week']),
            'Part': select(row['part']), 'Kind': select(row['kind']),
            'Book pages': text(f"{row['page_start']}-{row['page_end']}" if 'page_start' in row else ''),
            'Planned pages': number(row['pages']), 'Study status': select('Not started'),
        }
        initial = {key: value for key, value in initial.items() if key in schema()['plan'][1]}
        await client.upsert(sources['plan'], date_key, {}, initial=initial)
    if 'weekly' in sources:
        for week in sorted({r['week'] for r in plan_rows()}):
            await client.upsert(sources['weekly'],week,{},initial={'Name':{'title':rich('Week of '+week)},'Week start':day(week)})
    db.set_setting('notion_setup_complete',True)
    return 'https://www.notion.so/'+hub.replace('-','')


def score_properties(s):
    props={'Name':{'title':rich(s.quiz_title)},'Topic':text(s.topic),'Study date':day(s.study_date or today().isoformat()),
      'Kind':select(s.quiz_kind),'Learner ID':text(s.learner_user_id or 'Not answered yet'),
      'Quiz status':select(s.status.value),'Total':number(s.total_questions),'Attempted':number(s.attempted),
      'Correct':number(s.correct),'Wrong':number(s.wrong),'Remaining':number(s.unattempted),
      'Accuracy':number(s.accuracy),'Last synced':day(datetime.now(timezone.utc).isoformat())}
    if s.started_at:props['Started']=day(s.started_at.isoformat())
    return props


async def sync_results(client,selector='today',reference=None):
    sources={key:db.get_setting('notion_source:'+key) for key in schema()}
    if not db.get_setting('notion_setup_complete') or not all(sources.values()):raise NotionError('Run /notion_setup once after configuring the Notion integration.')
    sessions=[s for s in db.list_sessions() if s.quiz_kind!='test']
    def in_window(value,start,end):
        if value is None:return False
        if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
        return start<=value<end
    if selector=='all':chosen=sessions
    else:
        start,end=date_window(selector,reference)
        chosen=[s for s in sessions if in_window(s.started_at or s.created_at,start,end)
                or any(in_window(q.answered_at,start,end) for q in s.questions)]
    plan_dates={r['date'] for r in plan_rows()}
    for s in chosen:
        props=score_properties(s)
        if s.study_date in plan_dates:
            plan_id=await client.find(sources['plan'],s.study_date)
            if plan_id:props['Study day']={'relation':[{'id':plan_id}]}
        await client.upsert(sources['results'],s.session_id,props)
        if 'questions' in sources:
            for question in s.questions:
                await client.upsert(sources['questions'], question.source_id or f'{s.session_id}:{question.question_index}', {
                    'Name': {'title': rich(question.question_text[:180])},
                    'Topic': text(question.source_topic or s.topic),
                    'Question': text(question.question_text),
                    'Options': text('\n'.join(f'{i+1}. {option}' for i, option in enumerate(question.options))),
                    'Study date': day(s.study_date or today().isoformat()),
                    'Question status': select('Attempted' if question.user_answer is not None else 'Not attempted'),
                })

    aggregate_dates = {s.study_date for s in chosen} & plan_dates if 'Book questions' in schema()['plan'][1] else set()
    for study_date in sorted(aggregate_dates):
        book=[s for s in sessions if s.study_date==study_date and s.quiz_kind=='book' and (s.status.value!='CANCELLED' or s.attempted>0)]
        retry=[s for s in sessions if s.study_date==study_date and s.quiz_kind=='revision' and (s.status.value!='CANCELLED' or s.attempted>0)]
        attempted=sum(s.attempted for s in book); correct=sum(s.correct for s in book)
        props={'Book questions':number(sum(s.total_questions for s in book)),'Attempted':number(attempted),
          'Correct':number(correct),'Wrong':number(sum(s.wrong for s in book)),
          'Remaining':number(sum(s.unattempted for s in book)),'Accuracy':number(round(correct/attempted*100,2) if attempted else 0),
          'Revision attempted':number(sum(s.attempted for s in retry)),'Revision correct':number(sum(s.correct for s in retry)),
          'Last synced':day(datetime.now(timezone.utc).isoformat())}
        # The row was seeded during setup; never overwrite manual study fields.
        await client.upsert(sources['plan'],study_date,props)
    if 'weekly' not in sources:
        return len(chosen)
    if selector=='all':
        weeks={r['week'] for r in plan_rows()}
        for s in chosen:
            for q in s.questions:
                if q.answered_at:
                    local=q.answered_at.astimezone(ZoneInfo(STUDY_TIMEZONE)).date()
                    weeks.add((local-timedelta(days=local.weekday())).isoformat())
    else:
        start,end=date_window(selector,reference)
        first=start.astimezone(ZoneInfo(STUDY_TIMEZONE)).date()
        last=(end-timedelta(microseconds=1)).astimezone(ZoneInfo(STUDY_TIMEZONE)).date()
        weeks=set()
        while first<=last:
            weeks.add((first-timedelta(days=first.weekday())).isoformat());first+=timedelta(days=1)
    for week in sorted(weeks):
        week_date=date.fromisoformat(week)
        wstart,wend=date_window('week',week_date)
        answer_pairs=[(s,q) for s in sessions for q in s.questions if in_window(q.answered_at,wstart,wend)]
        originals=[q for s,q in answer_pairs if s.quiz_kind=='book'];retries=[q for s,q in answer_pairs if s.quiz_kind=='revision']
        correct=sum(q.is_correct is True for q in originals)
        wrong=db.wrong_questions_between(wstart,wend)
        props={'Name':{'title':rich('Week of '+week)},'Week start':day(week),
          'Attempted':number(len(originals)),'Correct':number(correct),'Wrong':number(sum(q.is_correct is False for q in originals)),
          'Accuracy':number(round(correct/len(originals)*100,2) if originals else 0),
          'Revision attempted':number(len(retries)),'Revision correct':number(sum(q.is_correct is True for q in retries)),
          'Unique mistakes':number(len({r['source_id'] for r in wrong})),
          'Last synced':day(datetime.now(timezone.utc).isoformat())}
        await client.upsert(sources['weekly'],week,props)
        # Update only auto-owned mistake fields, preserving the learner's review status.
        for source_id in sorted({r['source_id'] for r in wrong}):
            all_wrong=[(s,q) for s in sessions for q in s.questions if q.source_id==source_id and q.is_correct is False]
            if not all_wrong:continue
            s,q=all_wrong[-1]
            key=source_id
            await client.upsert(sources['mistakes'],key,{
                'Name':{'title':rich(q.question_text[:180])},'Topic':text(q.source_topic or s.topic),
                'Question':text(q.question_text),'Options':text('\n'.join(f'{i+1}. {opt}' for i,opt in enumerate(q.options))),
                'Correct answer':text(q.options[q.correct_option]),'Previous answer':text(q.options[q.user_answer]),
                'Explanation':text(q.explanation or ''),'Image':{'url':q.image_url if q.image_url and q.image_url.startswith(('https://','http://')) else None},
                'Last wrong':day(q.answered_at.isoformat()),'Wrong attempts':number(len(all_wrong))},
                initial={'Review status':select('To retry')})
    return len(chosen)
