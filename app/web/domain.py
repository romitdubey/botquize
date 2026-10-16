"""Pure study/test rules, independent of Telegram and storage."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.web.attachments import question_number

TZ = ZoneInfo('Asia/Kolkata')

def now(): return datetime.now(timezone.utc)
def iso(value): return value.isoformat()
def parsed(value): return datetime.fromisoformat(value.replace('Z','+00:00'))
def today(): return now().astimezone(TZ).date()

def validate_bank(data, topic, study_date):
    try: day = date.fromisoformat(study_date)
    except (ValueError, TypeError): raise HTTPException(400,'Use a study date like 2026-10-16.')
    if not isinstance(data,dict): raise HTTPException(400,'JSON must contain a questions array.')
    questions = data.get('questions')
    if not isinstance(questions,list) or not questions:
        raise HTTPException(400,'Upload a non-empty questions array.')
    title = topic or data.get('topic') or data.get('quiz_title') or 'Daily practice'
    if not isinstance(title,str) or not title.strip() or len(title)>500: raise HTTPException(400,'Invalid topic.')
    output=[]
    for index, item in enumerate(questions,1):
        if not isinstance(item,dict): raise HTTPException(400,f'Question {index} must be an object.')
        text=item.get('question'); options=item.get('options'); correct=item.get('correct_option')
        if not isinstance(text,str) or not text.strip() or len(text)>15000:
            raise HTTPException(400,f'Question {index}: missing/too long question text.')
        if not isinstance(options,list) or not 2<=len(options)<=10 or any(not isinstance(o,str) or not o.strip() or len(o)>5000 for o in options):
            raise HTTPException(400,f'Question {index}: provide 2–10 text options.')
        if type(correct) is not int or not 0<=correct<len(options):
            raise HTTPException(400,f'Question {index}: correct_option must be a zero-based option index.')
        explanation=item.get('explanation') or ''
        image=item.get('image_url') or ''
        if not isinstance(explanation,str) or len(explanation)>30000 or not isinstance(image,str) or len(image)>3000:
            raise HTTPException(400,f'Question {index}: invalid explanation/image.')
        identity=json.dumps([text,options,correct],ensure_ascii=False,separators=(',',':'))
        output.append({'number':question_number(item,index-1),'id':hashlib.sha256(identity.encode()).hexdigest()[:32], 'question':text,
            'options':options,'correct_option':correct,'explanation':explanation,
            'image_url':image if image.startswith('https://') else '', 'image_path':'', 'topic':title.strip()})
    duration=180  # Compatibility storage field; daily practice has no time limit.
    key=json.dumps([day.isoformat(),title,[(q['id'],q['number'],q['explanation'],q['image_url']) for q in output]],ensure_ascii=False)
    return {'id':str(uuid.uuid5(uuid.NAMESPACE_URL,key)), 'study_date':day.isoformat(),
        'topic':title.strip(),'description':str(data.get('description',''))[:5000],
        'questions':output,'duration_seconds':int(duration*60),'status':'draft','kind':'daily','owner_id':None}

def visible_quiz(quiz):
    return {k:quiz.get(k) for k in ('id','study_date','topic','description','status','kind','duration_seconds')} | {'count':len(quiz['questions'])}

def question_public(question):
    return {k:question.get(k,'') for k in ('id','number','question','options','image_url','image_path','topic','section')}

SECTIONS = {'A': {'count':20,'limit':15,'correct':2,'wrong':0.5},
            'B': {'count':50,'limit':35,'correct':2,'wrong':0.5},
            'C': {'count':75,'limit':25,'correct':4,'wrong':1}}

def validate_pyq(data, topic, study_date):
    if not isinstance(data,dict) or not isinstance(data.get('sections'),dict):
        raise HTTPException(400,'PYQ JSON needs sections with arrays A (20), B (50), C (75).')
    flattened=[]
    for section,rules in SECTIONS.items():
        items=data['sections'].get(section)
        if not isinstance(items,list) or len(items)!=rules['count']:
            raise HTTPException(400,f"Part {section} needs exactly {rules['count']} questions for a full CSIR paper.")
        for item in items:
            if not isinstance(item,dict):raise HTTPException(400,'Each PYQ question must be an object.')
            flattened.append({**item,'number':item.get('question_number',item.get('number',len(flattened)+1)),'section':section})
    bank=validate_bank({**data,'questions':flattened},topic,study_date)
    for q,item in zip(bank['questions'],flattened):
        if len(q['options'])!=4:raise HTTPException(400,'Each PYQ question needs four options and one correct_option.')
        q['section']=item['section']
    if len({q['number'] for q in bank['questions']})!=145:
        raise HTTPException(400,'Use unique question numbers across all three sections (for example 1–145).')
    bank.update(kind='pyq',duration_seconds=10800,id=str(uuid.uuid5(uuid.NAMESPACE_URL,'pyq:'+bank['id'])))
    return bank

def practice_clock(attempt, stamp, pause=False):
    """Persist active time only; an abandoned tab cannot accumulate hours."""
    attempt.setdefault('elapsed_seconds',0)
    start=attempt.get('running_since')
    if start:
        end=min(stamp,parsed(attempt.get('heartbeat_at',start))+timedelta(seconds=60))
        attempt['elapsed_seconds']+=max(0,(end-parsed(start)).total_seconds())
        attempt['running_since']=None if pause else iso(stamp)
        attempt['heartbeat_at']=iso(stamp)
    return attempt

def reconcile_attempt(attempt,stamp):
    if attempt.get('submitted_at'):return
    if attempt.get('kind')=='pyq':
        if parsed(attempt['deadline'])<=stamp:finish(attempt,parsed(attempt['deadline']))
    else:
        # Upgrade existing daily attempts without losing their answers; old countdowns no longer apply.
        attempt['deadline']=None
        attempt.setdefault('elapsed_seconds',0)
        if attempt.get('running_since') and stamp>parsed(attempt.get('heartbeat_at',attempt['running_since']))+timedelta(seconds=60):
            practice_clock(attempt,stamp,pause=True)

def finish(attempt, stamp):
    if attempt.get('submitted_at'): return
    exam=attempt.get('kind')=='pyq'
    if not exam:practice_clock(attempt,stamp,pause=True)
    else:attempt['elapsed_seconds']=max(0,(stamp-parsed(attempt['started_at'])).total_seconds())
    attempt['submitted_at']=iso(stamp)
    selected={i for i in range(len(attempt['questions'])) if str(i) in attempt['answers']}
    evaluated=set(selected); sections={};score=0
    if exam:
        evaluated=set()
        for section,rules in SECTIONS.items():
            indices=[i for i,q in enumerate(attempt['questions']) if q.get('section')==section]
            answered=[i for i in indices if i in selected]
            chosen=answered[:rules['limit']];evaluated.update(chosen)
            correct=sum(attempt['answers'][str(i)]==attempt['questions'][i]['correct_option'] for i in chosen)
            wrong=len(chosen)-correct
            marks=correct*rules['correct']-wrong*rules['wrong'];score+=marks
            sections[section]={'answered':len(answered),'evaluated':len(chosen),'correct':correct,'wrong':wrong,'score':marks,'excluded':len(answered)-len(chosen),'limit':rules['limit']}
        attempt.update(score=score,max_score=200,section_results=sections,excluded_indices=sorted(selected-evaluated))
    attempt['correct']=sum(attempt['answers'][str(i)]==attempt['questions'][i]['correct_option'] for i in evaluated)
    attempt['wrong']=len(evaluated)-attempt['correct']
    attempt['skipped']=len(attempt['questions'])-len(selected)
    attempt['excluded']=len(selected-evaluated)

def mistakes(data, start=None, end=None):
    result={}
    for attempt in data.get('attempts',{}).values():
        if not attempt.get('submitted_at'): continue
        stamp=parsed(attempt['submitted_at']).astimezone(TZ)
        if start and not start<=stamp.date()<end: continue
        for index, q in enumerate(attempt['questions']):
            answer=attempt['answers'].get(str(index))
            if index not in attempt.get('excluded_indices',[]) and answer is not None and answer!=q['correct_option']:
                previous=result.get(q['id'],{})
                result[q['id']]={**q,'your_answer':answer,'last_wrong':attempt['submitted_at'],
                    'times_wrong':previous.get('times_wrong',0)+1}
    return list(result.values())

def monday_window(day):
    monday=day-timedelta(days=day.weekday())
    return monday-timedelta(days=7),monday-timedelta(days=2),monday

def timer_segments(start, end):
    """Allocate real elapsed seconds across IST calendar boundaries."""
    segments={}
    while start<end:
        local=start.astimezone(TZ)
        boundary=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),TZ).astimezone(timezone.utc)
        stop=min(boundary,end)
        segments[local.date().isoformat()]=(stop-start).total_seconds()
        start=stop
    return segments

def settle_timer(data, stamp):
    timer=data.setdefault('timer',{})
    if timer.get('running_since'):
        start=parsed(timer['running_since'])
        # Count only up to the last heartbeat + 90 seconds if the browser disappears.
        end=min(stamp,parsed(timer.get('heartbeat_at',timer['running_since']))+timedelta(seconds=90))
        for day, seconds in timer_segments(start,max(start,end)).items():
            record=data.setdefault('days',{}).setdefault(day,{})
            record['seconds']=record.get('seconds',0)+seconds
            topic=timer.get('topic') or 'Independent revision'
            by_topic=record.setdefault('topics',{})
            by_topic[topic]=by_topic.get(topic,0)+seconds
        timer['running_since']=None
    return timer
