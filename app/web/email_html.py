"""Email-only HTML: inline presentation, no scripts, embeds or remote assets."""
import html
import re
from html.parser import HTMLParser
from app.web.richtext import image_url

TAGS={'html','body','table','thead','tbody','tr','td','th','p','div','span','h1','h2','h3','br','hr','strong','b','em','i','ul','ol','li','a'}
BLOCK={'head','script','style','iframe','object','svg','template','form'}
CSS={'background','background-color','color','font-family','font-size','font-weight','font-style','line-height','letter-spacing','text-align','text-decoration','padding','padding-top','padding-bottom','margin','margin-top','margin-bottom','border','border-radius','border-top','border-bottom','width','max-width','height','vertical-align','overflow-wrap'}

class EmailHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.text=[];self.hidden=[]
    def handle_starttag(self,tag,attrs):
        if self.hidden:
            if tag in BLOCK:self.hidden.append(tag)
            return
        if tag in BLOCK:self.hidden.append(tag);return
        if tag not in TAGS:return
        safe=[]
        for key,value in attrs:
            if value is None:continue
            if key=='style':
                declarations=[]
                for declaration in value.split(';'):
                    prop,sep,val=declaration.partition(':');prop=prop.strip().lower();val=val.strip()
                    if sep and prop in CSS and re.fullmatch(r"[a-zA-Z0-9#%,.()'\s\-]+",val) and not re.search(r'url|expression|var\s*\(',val,re.I):declarations.append(prop+':'+val)
                value=';'.join(declarations)
            elif key=='href' and tag=='a':value=image_url(value)
            elif key in ('width','height','cellpadding','cellspacing','colspan','rowspan'):
                if not re.fullmatch(r'\d{1,4}%?',value):continue
            elif key=='align':
                if value not in ('left','right','center'):continue
            elif key=='role' and value=='presentation':pass
            else:continue
            if value:safe.append(f' {key}="{html.escape(value,quote=True)}"')
        self.parts.append('<'+tag+''.join(safe)+'>')
        if tag in ('br','p','div','tr','h1','h2','h3'):self.text.append('\n')
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):
        if self.hidden:
            if tag==self.hidden[-1]:self.hidden.pop()
            return
        if tag in TAGS and tag not in ('br','hr'):self.parts.append('</'+tag+'>')
        if tag in ('p','div','tr','h1','h2','h3'):self.text.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(html.escape(data));self.text.append(data)

def clean_email_html(value):
    if not isinstance(value,str) or len(value.encode('utf-8'))>100_000:raise ValueError('HTML email limit is 100 KB.')
    parser=EmailHTML();parser.feed(value);parser.close()
    text=re.sub(r'\n[ \t]*\n+','\n\n',''.join(parser.text)).strip()
    if not text:raise ValueError('HTML email must contain a readable message.')
    return '<!doctype html>'+''.join(parser.parts),text
