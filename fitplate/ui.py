"""Explicit Streamlit adapter: translated presentation with stable canonical values."""
import inspect
import streamlit as native
from fitplate.i18n import tr,html_text,language

TEXT={'caption','write','markdown','info','warning','error','success','text','subheader','header','title','toast'}
WIDGETS={'button','form_submit_button','text_input','text_area','number_input','checkbox','selectbox','radio','slider','date_input','download_button','chat_input','file_uploader','multiselect','toggle'}
CONTEXTS={'container','expander','popover','form','spinner','chat_message'}


def preserve_widget_values():
    native.session_state['_language_widget_values']={key:native.session_state[key] for key in native.session_state.get('_localized_widgets',{}) if key in native.session_state}


class UI:
    def __init__(self,target):self.target=target
    def __enter__(self):self.target.__enter__();return self
    def __exit__(self,*args):return self.target.__exit__(*args)
    def __getattr__(self,name):
        value=getattr(self.target,name)
        if name=='form':
            return lambda form_id,**kw:self.target.container(key='localized_form:'+form_id,border=False)
        if name=='form_submit_button':
            value=getattr(self.target,'button')
        if name=='sidebar':return UI(value)
        if name=='columns':return lambda *a,**kw:[UI(c) for c in value(*a,**kw)]
        if name=='html':return lambda body,**kw:value(html_text(body),**kw)
        if name=='progress':
            def progress(number,*a,**kw):
                if 'text' in kw:kw['text']=tr(kw['text'])
                return value(number,*a,**kw)
            return progress
        if name=='metric':
            def metric(label,number,*a,**kw):
                if isinstance(number,str):
                    for unit in ('kcal','g','ml'):number=number.replace(' '+unit,' '+tr(unit))
                return value(tr(label),number,*a,**kw)
            return metric
        if name=='dataframe':
            def table(data,*a,**kw):
                if isinstance(data,list) and all(isinstance(row,dict) for row in data):
                    data=[{tr(k):tr(v) for k,v in row.items()} for row in data]
                return value(data,*a,**kw)
            return table
        if name in TEXT|WIDGETS|CONTEXTS or name=='image':
            def call(*args,**kwargs):
                args=list(args)
                original=args[0] if args else kwargs.get('label','')
                if name in WIDGETS and 'key' not in kwargs:
                    frame=inspect.currentframe().f_back
                    kwargs['key']=f'ui:{frame.f_code.co_filename}:{frame.f_lineno}:{name}:{original}'
                key=kwargs.get('key')
                if name in {'text_input','text_area','number_input','checkbox','selectbox','radio','slider','date_input','multiselect','toggle'} and key:
                    native.session_state.setdefault('_localized_widgets',{})[key]=name
                    pending=native.session_state.get('_language_widget_values',{})
                    if key in pending:
                        native.session_state[key]=pending.pop(key)
                        kwargs.pop('value',None)
                        if name in {'selectbox','radio'}:
                            kwargs.pop('index',None)
                if name not in {'container','form','chat_message','image'}:
                    if args:args[0]=tr(args[0])
                    elif 'label' in kwargs:kwargs['label']=tr(kwargs['label'])
                for key in ('placeholder','help','caption'):
                    if key in kwargs:kwargs[key]=tr(kwargs[key])
                if name in {'selectbox','radio','multiselect'}:
                    formatter=kwargs.get('format_func',str)
                    rendered_language=language()
                    kwargs['format_func']=lambda v:tr(formatter(v),rendered_language)
                return value(*args,**kwargs)
            return call
        return value


st=UI(native)
