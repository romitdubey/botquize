"""Conservative HTML import for scientific text. No scripts, styles or active embeds."""
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED={'p','br','strong','b','em','i','u','sub','sup','table','thead','tbody','tr','td','th','ul','ol','li','span','div','blockquote','img'}
BLOCK={'script','style','iframe','object','svg','math','template'}

def image_url(value):
    value=value.strip()
    if value.startswith('//'):value='https:'+value
    try:
        u=urlsplit(value)
        return value if u.scheme=='https' and u.hostname and not u.username and not u.password else ''
    except ValueError:return ''

class CleanHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.output=[];self.text=[];self.images=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in BLOCK:self.hidden+=1;return
        if self.hidden:return
        if tag not in ALLOWED:
            # Unknown pseudo-tags may be scientific inequalities; retain as escaped text.
            self.handle_data(self.get_starttag_text());return
        attrs=dict(attrs);extra=''
        if tag=='img':
            url=image_url(attrs.get('src',''))
            if not url:return
            self.images.append(url);self.text.append('[Diagram]')
            extra=f' src="{html.escape(url,quote=True)}" alt="{html.escape(attrs.get("alt") or "Question illustration",quote=True)}" loading="lazy" referrerpolicy="no-referrer"'
        if tag in ('td','th'):
            for key in ('colspan','rowspan'):
                if str(attrs.get(key,'')).isdigit() and 1<=int(attrs[key])<=30:extra+=f' {key}="{attrs[key]}"'
        self.output.append('<'+tag+extra+'>')
        if tag in ('p','br','div','tr','li'):self.text.append('\n')
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):
        if tag in BLOCK:
            self.hidden=max(0,self.hidden-1);return
        if self.hidden:return
        if tag in ALLOWED and tag not in ('br','img'):self.output.append('</'+tag+'>')
        if tag in ('p','div','tr','li'):self.text.append('\n')
        elif tag in ('td','th'):self.text.append(' | ')
    def handle_data(self,data):
        if not self.hidden:self.output.append(html.escape(data));self.text.append(data)


def scientific_text(value):
    if not isinstance(value,str):raise ValueError('Scientific content must be text.')
    for _ in range(4):
        decoded=html.unescape(value)
        if decoded==value:break
        value=decoded
    parser=CleanHTML();parser.feed(value);parser.close()
    plain=re.sub(r'\n[ \t]*\n+','\n\n',''.join(parser.text)).replace('\xa0',' ').strip()
    return {'text':plain,'html':''.join(parser.output).strip(),'images':parser.images}
