"""Merge bilingual paper/answer exports by immutable source question ID."""
from fastapi import HTTPException
from app.web.richtext import scientific_text


def export_part(payload):
    if not isinstance(payload,dict):return None
    data=payload.get('data',payload)
    if not isinstance(data,dict):return None
    if isinstance(data.get('sections'),list):
        sections=[]
        for section in data['sections']:
            if not isinstance(section,dict) or not isinstance(section.get('questions'),list):raise HTTPException(400,'Export sections need question arrays.')
            questions=[]
            for q in section['questions']:
                if not isinstance(q,dict) or not isinstance(q.get('en'),dict):raise HTTPException(400,'An English question is missing from this export.')
                questions.append({'_id':q.get('_id'),'en':q['en']})
            sections.append({'title':section.get('title',''),'questions':questions})
        return 'questions',{'title':data.get('title','Imported paper'),'sections':sections}
    if data and all(isinstance(v,dict) and 'correctOption' in v for v in data.values()):
        # Source personal scores/responses/analytics never enter our study database.
        return 'answers',{key:{'correctOption':v.get('correctOption'),'multiCorrectOptions':v.get('multiCorrectOptions'),'sol':{'en':v.get('sol',{}).get('en',{})}} for key,v in data.items()}
    return None


def merge_exports(paper,answers,pyq=False):
    result={'quiz_title':paper['title'],'questions':[]};sections={};seen=set()
    for si,section in enumerate(paper['sections']):
        label=section.get('title','').strip().upper().removeprefix('PART ').strip()
        if pyq and label not in ('A','B','C'):raise HTTPException(400,'Full paper section names must be Part A, Part B and Part C.')
        if pyq and label in sections:raise HTTPException(400,'Duplicate section in the paper export.')
        group=[]
        for raw in section['questions']:
            ident=raw.get('_id');number=len(result['questions'])+1
            if not isinstance(ident,str) or not ident or ident in seen:raise HTTPException(400,'Missing or duplicate source question ID in paper.')
            seen.add(ident)
            if ident not in answers:raise HTTPException(400,f'Answer file does not match this paper: answer missing for question {number} (ID {ident}). Upload its matching answer export.')
            answer=answers[ident];english=raw['en'];options=english.get('options')
            if not isinstance(options,list) or not options or any(not isinstance(o,dict) for o in options):raise HTTPException(400,f'Question {number}: English options are missing.')
            if answer.get('multiCorrectOptions'):raise HTTPException(400,f'Question {number}: multiple-answer questions need a different exam format.')
            key=answer.get('correctOption')
            matches=[i for i,o in enumerate(options) if str(o.get('prompt'))==str(key)]
            if type(key) not in (int,str) or len(matches)!=1:raise HTTPException(400,f'Question {number}: correctOption must match exactly one original option label.')
            stem=scientific_text(english.get('value',''));choices=[scientific_text(o.get('value','')) for o in options]
            sol=answer.get('sol',{}).get('en',{})
            explanation=scientific_text((sol.get('value','') if isinstance(sol,dict) else sol) or '')
            q={'question_number':number,'source_id':ident,'question':stem['text'] or '[See question image]',
               'question_html':stem['html'],'options':[o['text'] or '[See option image]' for o in choices],
               'options_html':[o['html'] for o in choices],'correct_option':matches[0],
               'explanation':explanation['text'],'explanation_html':explanation['html'],'image_url':''}
            group.append(q);result['questions'].append(q)
        sections[label if pyq else str(si)]=group
    extra=set(answers)-seen
    if extra:raise HTTPException(400,f'Answer file contains {len(extra)} question IDs outside this paper. Upload matching files; nothing was imported.')
    if pyq:result['sections']=sections
    return result
