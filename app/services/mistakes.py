"""Re-uploadable exports; original attempts remain untouched by re-tests."""
import json
from app import database as db
from app.services.planner import date_window, today


def export_wrong(selector='today',reference=None,user_id=None):
    start,end=date_window(selector,reference)
    rows=db.wrong_questions_between(start,end,user_id)
    seen=set();questions=[]
    for row in rows:
        # Re-tests of the same source question appear once in a weekly export.
        key=row['source_id'] or f"{row['session_id']}:{row['question_index']}"
        if key in seen:continue
        seen.add(key)
        q={'question':row['question_text'],'options':json.loads(row['options']),
           'correct_option':row['correct_option'],'explanation':row['explanation'] or '',
           'source_id':key,'source_topic':row['source_topic'] or row['topic'] or row['quiz_title'],
           'previous_answer':row['user_answer']}
        if row['image_url']:q['image_url']=row['image_url']
        questions.append(q)
    return {'quiz_title':f'Wrong-answer revision - {selector}',
            'topic':f'Wrong-answer revision - {selector}',
            'study_date':(reference or today()).isoformat(),
            'description':'Consolidated mistakes by answer time; repeated source questions appear once.',
            'quiz_kind':'revision','questions':questions}
