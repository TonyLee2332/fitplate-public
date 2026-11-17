"""Regression cases from the real-provider and browser acceptance audit."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from fitplate import agent
from fitplate.domain import fresh_draft, today
from fitplate.i18n import tr
from fitplate.model_client import ServiceError

REAL_RESPOND = agent.respond
APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def final(reply, intent='chat', meal=None):
    return json.dumps(dict(intent=intent, reply=reply, meal=meal))


def steak():
    return {**fresh_draft(), 'meal_type':'Dinner', 'items':[
        dict(name='Steak', quantity=None, unit='g', preparation='Cooked'),
        dict(name='Rice', quantity=150, unit='g', preparation='Cooked')]}


@pytest.mark.parametrize('lang,claim', [
    ('en', "I've updated the steak portion to 350g."),
    ('zh-Hans', '牛排份量已改为350克。'),
    ('zh-Hant', '牛排份量已改為350克。')])
def test_false_update_claim_requires_a_real_mutation(lang, claim):
    original=steak(); before=deepcopy(original)
    call=json.dumps(dict(intent='tool', reply='', meal=None, tool=dict(
        name='update_meal_portion', arguments=dict(item_index=0,quantity=350,unit='g'))))
    client=Mock(usage=[])
    client.chat.side_effect=[final(claim),call,final(claim)]
    result=REAL_RESPOND('350g',draft=original,client=client,language=lang)
    assert result['draft']['items'][0]['quantity']==350
    assert result['draft']['items'][1]==before['items'][1]
    assert result['draft']['id']==before['id'] and original==before
    assert result['tool_trace'][0]['tool']=='update_meal_portion'
    assert 'No draft mutation' in client.validation_errors[0]['reason']


@pytest.mark.parametrize('reply',["I've updated the steak to 350g.",'Updated: steak 350g.','The steak is now 350g.'])
def test_repeated_false_update_cannot_report_success(reply):
    original=steak(); before=deepcopy(original)
    client=Mock(usage=[])
    client.chat.side_effect=[final(reply)]*2
    with pytest.raises(ServiceError):REAL_RESPOND('350g',draft=original,client=client)
    assert original==before and client.chat.call_count==2


def test_ambiguous_question_can_remain_a_question_without_mutation():
    client=Mock(usage=[])
    client.chat.return_value=final('Which food does 350g refer to?')
    result=REAL_RESPOND('350g',draft=steak(),client=client)
    assert result['draft'] is None and result['reply'].endswith('?')
    assert client.chat.call_count==1


def test_successful_mutation_survives_malformed_final_reply():
    call=json.dumps(dict(intent='tool',reply='',meal=None,tool=dict(name='update_meal_portion',arguments=dict(item_index=0,quantity=350,unit='g'))))
    client=Mock(usage=[])
    client.chat.side_effect=[call,'not JSON','still not JSON']
    result=REAL_RESPOND('350g',draft=steak(),client=client)
    assert result['draft']['items'][0]['quantity']==350
    assert result['reply']=='Portion updated in the draft. Review before saving.'


@pytest.mark.parametrize('length',[1279,1290,4000])
def test_normal_analysis_length_is_accepted(length):
    reply='A'*length
    assert agent.decode_result(final(reply),None,'Text')['reply']==reply


def test_oversize_analysis_gives_precise_constraint():
    with pytest.raises(ValueError,match='at most 4000 characters'):
        agent.decode_result(final('A'*4001),None,'Text')
    with pytest.raises(ValueError):agent.decode_result(final(''),None,'Text')


@pytest.mark.parametrize('text',[
    '午餐我吃了两个鸡蛋和150克米饭。',
    '午餐我吃了兩個雞蛋和150克米飯。',
    'For lunch I ate two eggs and 150 g rice.',
    'For lunch I ate 2 boiled eggs and 150 g rice.'])
def test_explicit_count_is_restored_in_voice_meal(text):
    meal=dict(date=today().isoformat(),meal_type='Lunch',note='',items=[
        dict(name='Egg',quantity=None,unit='g',preparation='Boiled',details=dict(estimated_grams=100,estimate_basis='Typical assumption.')),
        dict(name='Rice',quantity=150,unit='g',preparation='Cooked')])
    client=Mock(usage=[]);client.chat.return_value=final('Please review your draft.','meal',meal)
    result=REAL_RESPOND(text,client=client,source='Voice')
    egg,rice=result['draft']['items']
    assert (egg['quantity'],egg['unit'])==(2,'piece')
    assert egg['details']['quantity_origin']=='User'
    assert (rice['quantity'],rice['unit'])==(150,'g')


def test_photo_without_accompanying_amounts_keeps_unknown_quantity():
    draft={'items':[dict(name='Egg',quantity=None,unit='g',preparation='Boiled')]}
    agent._restore_portion_evidence(draft,'Please identify this meal. I do not know the weights.')
    assert draft['items'][0]['quantity'] is None


def test_identical_foods_do_not_receive_an_ambiguous_count():
    draft={'items':[dict(name='Egg',quantity=None,unit='g',preparation=prep) for prep in ('Boiled','Fried')]}
    agent._restore_portion_evidence(draft,'two eggs')
    assert all(item['quantity'] is None for item in draft['items'])


@pytest.mark.parametrize('lang',['zh-Hans','zh-Hant'])
def test_status_and_missing_portion_fragment_are_fully_translated(lang):
    assert 'not provided' not in tr('Portion not provided: Egg, Rice',lang)
    assert tr('Partial',lang)!='Partial'


@pytest.mark.parametrize('lang',['en','zh-Hans','zh-Hant'])
def test_rolling_caption_matches_selected_window(lang):
    app=AppTest.from_file(APP,default_timeout=30).run()
    if lang!='en':next(s for s in app.selectbox if s.key=='language_choice').set_value(lang).run()
    next(b for b in app.button if b.label==tr('Goals & insights',lang)).click().run()
    next(s for s in app.selectbox if s.key=='weekly_mode').set_value('rolling_7').run()
    assert not app.exception
    caption='The last 7 days include the review date and the six preceding days. No records means unknown intake, not zero.'
    assert any(c.value==tr(caption,lang) for c in app.caption)
    assert not any('Monday to Sunday' in c.value or '週一至週日' in c.value or '周一至周日' in c.value for c in app.caption)
