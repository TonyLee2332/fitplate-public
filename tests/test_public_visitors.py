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


def test_per_visitor_and_global_limits(monkeypatch):
    monkeypatch.setenv('FITPLATE_VISITOR_DAILY_REQUESTS','2')
    monkeypatch.setenv('FITPLATE_GLOBAL_DAILY_REQUESTS','3')
    consume_request('a');consume_request('a')
    with pytest.raises(ServiceError,match='Your daily'):consume_request('a')
    consume_request('b')
    with pytest.raises(ServiceError,match='shared AI service'):consume_request('c')
    consume_request('a','2099-01-01')


def test_quota_is_atomic_across_threads(monkeypatch):
    monkeypatch.setenv('FITPLATE_VISITOR_DAILY_REQUESTS','100')
    monkeypatch.setenv('FITPLATE_GLOBAL_DAILY_REQUESTS','5')
    def call(i):
        try:consume_request(str(i));return True
        except ServiceError:return False
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(call,range(12)))==5


def test_invalid_limit_does_not_disable_budgets(monkeypatch):
    from fitplate.usage_guard import limit
    monkeypatch.setenv('LIMIT_TEST','0');assert limit('LIMIT_TEST',30)==30
    monkeypatch.setenv('LIMIT_TEST','bad');assert limit('LIMIT_TEST',30)==30
