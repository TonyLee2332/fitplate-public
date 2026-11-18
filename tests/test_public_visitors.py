from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from fitplate import visitors
from fitplate.domain import fresh_draft
from fitplate.storage import save_meal,list_meals,delete_meal,save_settings,read_settings,save_language,read_language
from fitplate.usage_guard import consume_request
from fitplate.model_client import ServiceError


def test_random_tokens_persist_and_reject_forgery():
    a,b=visitors.create_token(),visitors.create_token()
    assert a!=b and visitors.validate_token(a)
    assert visitors.validate_token(a)==visitors.validate_token(a)
    assert not visitors.validate_token(a[:-1]+('0' if a[-1]!='0' else '1'))
    assert not visitors.validate_token('../../other')
    assert not visitors.validate_token(None)


def test_two_visitors_have_independent_records_settings_and_language():
    a,b=visitors.create_token(),visitors.create_token()
    meal={**fresh_draft(),'id':'same-id','estimate_reviewed':True,'items':[dict(name='Egg',quantity=100,unit='g',preparation='Boiled')]}
    visitors.activate(a);save_meal(meal);save_settings({'name':'Visitor A'});save_language('zh-Hant')
    visitors.activate(b)
    assert list_meals()==[] and read_settings()['name']=='' and read_language()=='en'
    delete_meal('same-id');save_settings({'name':'Visitor B'});save_language('zh-Hans')
    visitors.activate(a)
    assert len(list_meals())==1 and read_settings()['name']=='Visitor A' and read_language()=='zh-Hant'


def test_legacy_root_records_are_not_given_to_visitors():
    save_settings({'name':'Private old workspace'})
    visitors.activate(visitors.create_token())
    assert read_settings()['name']==''


def test_signing_key_is_retained_across_calls():
    token=visitors.create_token();key=visitors.signing_key()
    assert len(key)==32 and visitors.signing_key()==key
    assert visitors.validate_token(token)


def test_no_daily_allowance_even_with_legacy_environment(monkeypatch):
    monkeypatch.setenv('FITPLATE_VISITOR_DAILY_REQUESTS','1')
    monkeypatch.setenv('FITPLATE_GLOBAL_DAILY_REQUESTS','1')
    for i in range(500):
        consume_request('same-visitor')
    from fitplate import usage_guard
    token=visitors.create_token()
    visitors.activate(token)
    for i in range(350):
        with usage_guard.request_slot():
            pass
    assert not (visitors.data_root()/'ai_usage.sqlite3').exists()


def test_request_slot_released_on_error():
    from fitplate.usage_guard import request_slot, _slots
    visitors.activate(visitors.create_token())
    with pytest.raises(RuntimeError):
        with request_slot():
            raise RuntimeError('test')
    with request_slot():
        with request_slot():
            with pytest.raises(ServiceError,match='busy'):
                with request_slot():
                    pass
