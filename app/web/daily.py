"""Daily permissions use the server's India calendar, never a client-supplied date."""
from datetime import date, timedelta
from fastapi import HTTPException
from app.services.planner import plan_rows


def scheduled_day(day):
    try: parsed=date.fromisoformat(day)
    except (ValueError,TypeError):raise HTTPException(400,'Invalid study date.')
    row=next((r for r in plan_rows() if r['date']==parsed.isoformat()),None)
    if not row:raise HTTPException(404,'No study topic is scheduled on this day.')
    return {k:v for k,v in row.items() if k in ('date','topic','part','kind')}


def today_topic(day):
    try:return scheduled_day(day.isoformat())['topic']
    except HTTPException:raise HTTPException(403,'There is no scheduled study topic today.')


def require_today(day,reference):
    if day!=reference.isoformat():raise HTTPException(403,'Only today’s study day can be updated.')
    return scheduled_day(day)


def release_day(quiz):
    day=date.fromisoformat(quiz['study_date'])
    return day+timedelta(days=1) if quiz.get('kind')=='daily' else day


def is_released(quiz,reference):
    return quiz['status']=='open' and release_day(quiz)<=reference
