"""Two-file export parsing, English-only content and safe scientific rendering."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.web.importer import export_part,merge_exports
from app.web.domain import validate_pyq,question_public
from app.web.richtext import scientific_text
from tests.test_website import MemoryStore

ROOT=Path(__file__).resolve().parents[1]

def sample():
    return ({'success':True,'data':{'title':'Example','sections':[{'title':'Part A','questions':[{'_id':'q1','en':{'value':'&lt;p&gt;English x&lt;sup&gt;2&lt;/sup&gt; &lt;img src=&quot;//cdn.example.com/q.png&quot;&gt;&lt;/p&gt;','options':[{'prompt':str(i+1),'value':v} for i,v in enumerate(['one','two','three','four'])]},'hn':{'value':'Hindi is not imported'}}]}]}},
            {'success':True,'data':{'q1':{'correctOption':'2','sol':{'en':{'value':'&lt;p&gt;&lt;strong&gt;Reason&lt;/strong&gt; two&lt;/p&gt;'},'hn':{'value':'Not imported'}},'studentResponse':'4','marksObtained':-0.5}}})

def test_pair_keeps_english_rich_images_and_correct_label_mapping():
    question,answer=sample();q=export_part(question);a=export_part(answer)
    assert q[0]=='questions' and a[0]=='answers'
    assert 'studentResponse' not in a[1]['q1']
    m=merge_exports(q[1],a[1]);item=m['questions'][0]
    assert item['correct_option']==1 and item['options']==['one','two','three','four']
    assert '<sup>2</sup>' in item['question_html'] and 'https://cdn.example.com/q.png' in item['question_html']
    assert 'Reason' in item['explanation'] and '<strong>Reason</strong>' in item['explanation_html']
    assert 'Hindi' not in json.dumps(m) and 'Not imported' not in json.dumps(m)

@pytest.mark.parametrize('mutation',['missing','extra','invalid','duplicate'])
def test_mismatched_or_ambiguous_files_never_import(mutation):
    q,a=sample();q=export_part(q)[1];a=export_part(a)[1]
    if mutation=='missing':a={}
    if mutation=='extra':a['another']=a['q1']
    if mutation=='invalid':a['q1']['correctOption']='9'
    if mutation=='duplicate':q['sections'][0]['questions']*=2
    with pytest.raises(HTTPException):merge_exports(q,a)

def test_html_strips_active_content_and_keeps_scientific_tables():
    value='&lt;p onclick=&quot;bad()&quot;&gt;x&lt;sub&gt;2&lt;/sub&gt;&lt;/p&gt;<script>secret</script><iframe src="https://evil.test"></iframe><img src="javascript:alert(1)" onerror="bad()"><table><tr><td colspan="2">A</td></tr></table>'
    result=scientific_text(value)
    assert '<sub>2</sub>' in result['html'] and '<table>' in result['html']
    assert all(x not in result['html'] for x in ('onclick','onerror','javascript:','<script','secret','iframe'))

@pytest.mark.skipif(not (ROOT/'response.json').exists() or not (ROOT/'answer.json4').exists(),reason='User export fixtures are local, not required in CI')
def test_actual_supplied_paper_all_145_keys_and_explanations():
    question=export_part(json.loads((ROOT/'response.json').read_text()))[1]
    answer=export_part(json.loads((ROOT/'answer.json4').read_text()))[1]
    bank=validate_pyq(merge_exports(question,answer,True),'CSIR 2025','2026-10-17')
    assert len(bank['questions'])==145
    assert all(q['explanation'] and q['explanation_html'] for q in bank['questions'])
    assert bank['questions'][0]['correct_option']==1
    assert sum(q['question_html'].count('<img ') for q in bank['questions'])==26
    assert sum(''.join(q['options_html']).count('<img ') for q in bank['questions'])==8
    public=question_public(bank['questions'][0]);assert 'explanation_html' not in public and 'correct_option' not in public
    assert public['question_html'] and len(public['options_html'])==4

@pytest.mark.asyncio
@pytest.mark.parametrize('order',[('questions','answers'),('answers','questions')])
async def test_telegram_two_files_in_either_order(order,monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.admins[123456789]={'target_user_id':'me','target_alias':'me'}
    send=AsyncMock();monkeypatch.setattr(tg,'telegram',send)
    question,answer=sample();files={'questions':json.dumps(question).encode(),'answers':json.dumps(answer).encode()}
    async def download(file_id,max_size):return files[file_id]
    monkeypatch.setattr(tg,'download',download)
    async def update(text=None,**extra):
        await tg.handle_update({'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},store)
    await update('/topic 2026-10-16 | Pair import')
    await update(document={'file_id':order[0],'file_name':order[0]+'.json'})
    assert not store.banks and 'file received' in send.call_args.args[1]['text']
    await update(document={'file_id':order[1],'file_name':order[1]+'.json4'})
    bank=next(iter(store.banks.values()))
    assert bank['status']=='draft' and bank['owner_id']=='me' and bank['questions'][0]['correct_option']==1
    assert bank['questions'][0]['explanation_html']
    await update('/open');assert store.banks[bank['id']]['status']=='open'
    await update('/topic 2026-10-19 | Different paper')
    assert not store.admins[123456789]['import_parts']

@pytest.mark.asyncio
@pytest.mark.skipif(not (ROOT/'response.json').exists() or not (ROOT/'answer.json4').exists(),reason='Optional user export fixtures')
async def test_actual_two_file_telegram_full_exam_import(monkeypatch):
    from app.web import telegram as tg
    store=MemoryStore();store.admins[123456789]={'target_user_id':'my-test-account','target_alias':'me'}
    monkeypatch.setattr(tg,'telegram',AsyncMock())
    async def download(file_id,max_size):return (ROOT/file_id).read_bytes()
    monkeypatch.setattr(tg,'download',download)
    async def update(text=None,**extra):
        await tg.handle_update({'message':{'from':{'id':123456789},'chat':{'id':123456789,'type':'private'},**({'text':text} if text else {}),**extra}},store)
    await update('/pyq 2026-10-17 | CSIR July 2025')
    for name in ('response.json','answer.json4'):
        await update(document={'file_id':name,'file_name':name})
    bank=next(iter(store.banks.values()))
    assert bank['kind']=='pyq' and bank['owner_id']=='my-test-account'
    assert len(bank['questions'])==145 and all(q['explanation_html'] for q in bank['questions'])
    assert not store.admins[123456789]['import_parts']
    await update('/open');assert store.banks[bank['id']]['status']=='open'
