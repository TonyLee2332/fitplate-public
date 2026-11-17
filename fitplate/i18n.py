"""Local UI catalogues; canonical meal values and user text are never rewritten."""
from functools import lru_cache
from html.parser import HTMLParser
from html import escape
from pathlib import Path
import json
import re
import streamlit as native

LANGUAGES={'en':'English','zh-Hans':'简体中文','zh-Hant':'繁體中文'}
ROOT=Path(__file__).parent/'data'


def language():
    try:return native.session_state.get('language','en')
    except Exception:return 'en'


@lru_cache(maxsize=8)
def load_catalog(path,stamp):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    patterns=[]
    for source,target in data.items():
        if '{0}' not in source:continue
        parts=re.split(r'(\{\d+\})',source)
        if len(re.sub(r'\{\d+\}','',source).strip())<4:continue
        pattern='';seen=set()
        for part in parts:
            if re.fullmatch(r'\{\d+\}',part):
                n=part[1:-1]
                pattern+=f'(?P=v{n})' if n in seen else f'(?P<v{n}>.*?)';seen.add(n)
            else:pattern+=re.escape(part)
        patterns.append((len(source),re.compile('^'+pattern+'$',re.S),target))
    return data,{k.casefold():v for k,v in data.items()},sorted(patterns,key=lambda p:-p[0])


def tr(text,lang=None):
    if not isinstance(text,str):return text
    lang=lang or language()
    if lang=='en':return text
    file=ROOT/('ui_zh_hans.json' if lang=='zh-Hans' else 'ui_zh_hant.json')
    if not file.exists():return text
    data,folded,patterns=load_catalog(str(file),file.stat().st_mtime_ns)
    if text in data:return data[text]
    if text.casefold() in folded:return folded[text.casefold()]
    for _,pattern,target in patterns:
        match=pattern.fullmatch(text)
        if match:
            value=target
            for key,captured in match.groupdict().items():
                value=value.replace('{'+key[1:]+'}',tr(captured,lang) if captured!=text else captured)
            return value
    output=text
    for source,target in sorted(data.items(),key=lambda pair:-len(pair[0])):
        if len(source)>20 and '{' not in source and source in output:
            output=output.replace(source,target)
    return output


class LocalHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.output=[];self.stack=[]
    def handle_starttag(self,tag,attrs):
        parent=self.stack[-1][1] if self.stack else False
        skip=parent or tag in {'style','script'} or any(k=='class' and set(v.split()) & {'user','original-source','brand'} for k,v in attrs if v)
        self.stack.append((tag,skip));self.output.append(self.get_starttag_text())
        if tag in {'br','hr','img','input','meta','link'}:self.stack.pop()
    def handle_startendtag(self,tag,attrs):self.output.append(self.get_starttag_text())
    def handle_endtag(self,tag):
        self.output.append('</'+tag+'>')
        if self.stack:self.stack.pop()
    def handle_data(self,text):
        if self.stack and self.stack[-1][1]:
            self.output.append(text if any(tag in {'style','script'} for tag,_ in self.stack) else escape(text,quote=False));return
        stripped=text.strip()
        self.output.append(escape(text.replace(stripped,tr(stripped)) if stripped else text,quote=False))
    def handle_entityref(self,name):self.output.append('&'+name+';')
    def handle_charref(self,name):self.output.append('&#'+name+';')


def html_text(value):
    if language()=='en':return value
    parser=LocalHTML();parser.feed(value);return ''.join(parser.output)


def has_english_prose(text):
    return bool(re.search(r'\b[A-Za-z]{2,}(?:[ ,;:-]+[A-Za-z]{2,}){4,}\b',text))


CONTROL_LABELS=('Add files','Show/hide columns','Download as CSV','Search','Upload','10MB per file','Upload a file','file upload','Start recording','Stop recording','Send message',
                'Remove file','Remove audio','Delete recording','Play','Pause','Download',
                'Open','Close','Clear','Drag and drop file here','Drag and drop files here',
                'Browse files','Record audio','Record','Stop','Cancel','Submit','Previous month','Next month',
                'Skip to main content','Increment','Decrement','Link to heading',
                'Show data','Download as PNG','Copy Vega-Lite spec','Fullscreen','Exit fullscreen','Choose date')


def localize_framework_controls():
    """Translate framework-owned accessible labels without modifying widget values."""
    translations={text:tr(text) for text in CONTROL_LABELS}
    reverse={tr(text,locale):text for locale in LANGUAGES for text in CONTROL_LABELS}
    config=json.dumps({'language':language(),'translations':translations,'reverse':reverse},ensure_ascii=False).replace('<','\\u003c')
    script=(ROOT.parents[1]/'assets/localize_controls.js').read_text(encoding='utf-8')
    native.html('<script>'+script.replace('__FITPLATE_LOCALE__',config)+'</script>',unsafe_allow_javascript=True)
