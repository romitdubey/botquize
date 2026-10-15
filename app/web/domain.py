"""Pure study/test rules, independent of Telegram and storage."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException

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
    if not isinstance(questions,list) or not 1 <= len(questions) <= 1000:
        raise HTTPException(400,'Upload between 1 and 1,000 questions per test.')
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
        output.append({'id':hashlib.sha256(identity.encode()).hexdigest()[:32], 'question':text,
            'options':options,'correct_option':correct,'explanation':explanation,
            'image_url':image if image.startswith('https://') else '', 'image_path':'', 'topic':title.strip()})
    duration=data.get('duration_minutes',max(10,len(output)*1.5))
    if isinstance(duration,bool) or not isinstance(duration,(float,int)) or not 1<=duration<=360:
        raise HTTPException(400,'duration_minutes must be between 1 and 360.')
    key=json.dumps([day.isoformat(),title,[(q['id'],q['explanation'],q['image_url']) for q in output]],ensure_ascii=False)
    return {'id':str(uuid.uuid5(uuid.NAMESPACE_URL,key)), 'study_date':day.isoformat(),
        'topic':title.strip(),'description':str(data.get('description',''))[:5000],
        'questions':output,'duration_seconds':int(duration*60),'status':'draft','kind':'daily','owner_id':None}

def visible_quiz(quiz):
    return {k:quiz.get(k) for k in ('id','study_date','topic','description','status','kind','duration_seconds')} | {'count':len(quiz['questions'])}

def question_public(question):
    return {k:question.get(k,'') for k in ('id','question','options','image_url','image_path','topic')}

def finish(attempt, stamp):
    if attempt.get('submitted_at'): return
    attempt['submitted_at']=iso(stamp)
    attempt['correct']=sum(attempt['answers'].get(str(i))==q['correct_option'] for i,q in enumerate(attempt['questions']))
    attempt['wrong']=sum(str(i) in attempt['answers'] and attempt['answers'][str(i)]!=q['correct_option'] for i,q in enumerate(attempt['questions']))
    attempt['skipped']=len(attempt['questions'])-attempt['correct']-attempt['wrong']

def mistakes(data, start=None, end=None):
    result={}
    for attempt in data.get('attempts',{}).values():
        if not attempt.get('submitted_at'): continue
        stamp=parsed(attempt['submitted_at']).astimezone(TZ)
        if start and not start<=stamp.date()<end: continue
        for index, q in enumerate(attempt['questions']):
            answer=attempt['answers'].get(str(index))
            if answer is not None and answer!=q['correct_option']:
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
