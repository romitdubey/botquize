"""Account scoping shared by the learner API and Telegram administration."""
import uuid
import copy
import json
import hashlib
from fastapi import HTTPException


def content_visible(row,user):
    owner=row.get('owner_id')
    return owner==user['id'] if owner else user.get('account_alias')!='me'


def scoped_quiz(bank,owner):
    bank=copy.deepcopy(bank)
    bank.update(id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"account-bank:{owner}:{bank['id']}")),owner_id=owner)
    return bank


async def copy_content(store,quiz,target):
    # Content snapshots only. Never copy learner state, attempts or study completions.
    version=hashlib.sha256(json.dumps(quiz['questions'],sort_keys=True).encode()).hexdigest()
    copied={k:copy.deepcopy(v) for k,v in quiz.items() if k!='created_at'}
    copied.update(id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"copy:{target}:{quiz['id']}:{version}")),owner_id=target,status='draft')
    existing=await store.quizzes(id='eq.'+copied['id'])
    if existing:copied=existing[0]
    else:await store.put_quiz(copied)
    count=0
    for note in await store.notes(quiz['study_date']):
        if note.get('owner_id')!=quiz.get('owner_id'):continue
        row={k:v for k,v in note.items() if k!='created_at'}
        row.update(id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"copy-note:{target}:{note['id']}")),owner_id=target)
        await store.put_note(row);count+=1
    return copied,count
