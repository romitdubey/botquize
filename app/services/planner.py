"""Dated revision plan; preserve the original schedule through 22 October 2026."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from app.config import STUDY_TIMEZONE

REVISION = [
    'Biochemistry: enzymes, energetics and central pathways',
    'Biochemistry integration + Cell Biology: organelles, cycle and signaling',
    'Developmental Biology: gametes, fertilization, germ layers and organogenesis',
    'Genetics: inheritance, nucleic acids, replication, transcription and translation',
    'Genetics: chromatin, gene regulation, repair and genetic engineering',
    'Immunology: innate/adaptive, antibodies, antigen presentation and development',
    'Immunology: complement, hypersensitivity, vaccines, clinical topics and methods',
    'Weakest two topics from PYQ/mock errors + recurring wrong answers',
    'All five parts: diagrams, comparison tables and experimental interpretation',
    'Final closure: due re-tests, flagged questions and one-page summaries',
]


def today():
    return datetime.now(ZoneInfo(STUDY_TIMEZONE)).date()


def _original_book_rows():
    topics=json.loads((Path(__file__).parent.parent/'data'/'study_topics.json').read_text())
    day=date(2026,10,16); end=date(2026,12,10); index=0; rev=0; rows=[]
    while day<=end:
        row={'key':day.isoformat(),'date':day.isoformat(),'week':(day-timedelta(days=day.weekday())).isoformat()}
        if day.weekday()==5:
            row.update(topic='Full PYQ test + analysis',part='Mixed',kind='PYQ',pages=0)
        elif day.weekday()==6:
            row.update(topic='Paid mock + analysis',part='Mixed',kind='Mock',pages=0)
        elif index<len(topics):
            row.update(topics[index]);row.update(kind='Study',pages=row['page_end']-row['page_start']+1);index+=1
        else:
            row.update(topic=REVISION[rev],part='Revision',kind='Revision',pages=0);rev+=1
        rows.append(row);day+=timedelta(days=1)
    return rows


def aptitude_plan():
    """Printed ranges from the supplied aptitude contents; at most six pages a day."""
    topics=json.loads((Path(__file__).parent.parent/'data'/'aptitude_topics.json').read_text())
    day=date(2026,10,23);blocks=[]
    for chapter in topics:
        length=chapter['page_end']-chapter['page_start']+1
        count=(length+5)//6
        base,extra=divmod(length,count);page=chapter['page_start']
        for part in range(1,count+1):
            size=base+(part<=extra)
            blocks.append({'date':day.isoformat(),'id':f'aptitude-{day.isoformat()}',
                'chapter':chapter['chapter'],'topic':chapter['topic'],'part':part,'parts':count,
                'page_start':page,'page_end':page+size-1})
            page+=size;day+=timedelta(days=1)
    return blocks


def plan_rows():
    revised=json.loads((Path(__file__).parent.parent/'data'/'revised_study_plan.json').read_text())
    by_day={row['date']:row for row in revised}
    rows=[]
    for original in _original_book_rows():
        if original['date']<='2026-10-22' or original['kind'] in ('PYQ','Mock'):
            rows.append(original)
        else:
            replacement=by_day[original['date']]
            # Do not attach invented book pages to units absent from the original book.
            rows.append({**{key:original[key] for key in ('key','date','week')},**replacement,'pages':0})
    aptitude={item['date']:{k:v for k,v in item.items() if k not in ('date','page_start','page_end')} for item in aptitude_plan()}
    for row in rows:
        if row['date'] in aptitude:row['aptitude']=aptitude[row['date']]
    return rows


def date_window(selector='today',reference=None):
    """Return [start,end) in UTC; weeks are local Monday through Sunday."""
    day=reference or today();monday=day-timedelta(days=day.weekday())
    if selector=='today': first,last=day,day+timedelta(days=1)
    elif selector=='yesterday':first,last=day-timedelta(days=1),day
    elif selector=='week':first,last=monday,monday+timedelta(days=7)
    elif selector=='lastweek':first,last=monday-timedelta(days=7),monday
    else:
        first=date.fromisoformat(selector);last=first+timedelta(days=1)
    tz=ZoneInfo(STUDY_TIMEZONE)
    return (datetime.combine(first,datetime.min.time(),tz).astimezone(timezone.utc),
            datetime.combine(last,datetime.min.time(),tz).astimezone(timezone.utc))
