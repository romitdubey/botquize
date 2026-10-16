"""Resolve diagram labels without guessing between printed and array numbers."""
import re
from pathlib import Path
from fastapi import HTTPException


def question_number(question,index):
    explicit=question.get('question_number',question.get('number'))
    if explicit is None and isinstance(question.get('id'),int):explicit=question['id']
    if explicit is not None:
        text=str(explicit).strip()
        if not re.fullmatch(r'[1-9]\d*',text):
            raise HTTPException(400,f'Question {index+1}: question_number must be a positive printed question number.')
        return text
    match=re.match(r'^\s*(?:Q(?:uestion)?\.?\s*)?(\d+)\s*[.):\-]',question.get('question',''),re.IGNORECASE)
    return match.group(1) if match else str(index+1)


def attachment_number(caption='',filename=''):
    text=caption.strip()
    if text:
        match=re.fullmatch(r'(?:/image\s+)?(?:q(?:uestion)?[\s_:-]*)?(#?\d+)',text,re.IGNORECASE)
        if match:return match.group(1)
    stem=Path(filename).stem.strip()
    match=re.fullmatch(r'(?:(?:image|img|diagram)[ _-]*)?(?:q(?:uestion)?[ _-]*)?(\d+)',stem,re.IGNORECASE)
    return match.group(1) if match else None


def resolve_question(questions,label):
    label=label.strip()
    if label.startswith('#'):
        try:index=int(label[1:])-1
        except ValueError:raise HTTPException(400,'Use #12 for the 12th array item.')
        if 0<=index<len(questions):return index
        raise HTTPException(400,'That array position is outside the selected test.')
    label=re.sub(r'^(?:q(?:uestion)?)[\s_:.-]*','',label,flags=re.IGNORECASE)
    if not re.fullmatch(r'[1-9]\d*',label):raise HTTPException(400,'Use /image Q12 or /image #12.')
    matches=[i for i,q in enumerate(questions) if question_number(q,i)==label]
    if len(matches)>1:raise HTTPException(400,f'Question number {label} occurs more than once. Use #ARRAY-POSITION to select one explicitly.')
    if not matches:raise HTTPException(400,f'Question number {label} was not found. Check its JSON question_number, or use #ARRAY-POSITION.')
    return matches[0]
