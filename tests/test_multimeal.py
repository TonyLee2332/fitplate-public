from pathlib import Path
from copy import deepcopy
from unittest.mock import Mock
import json
import pytest
from streamlit.testing.v1 import AppTest
from fitplate import agent
from fitplate.domain import today,fresh_draft
from fitplate.storage import list_meals
from fitplate.draft_workspace import analyze_drafts,review_goals,combine_drafts
from fitplate.i18n import tr

REAL_RESPOND=agent.respond
APP=str(Path(__file__).resolve().parents[1]/'app.py')


def meal(kind,weight):
    return dict(date=today().isoformat(),meal_type=kind,items=[dict(name='Boiled egg',quantity=weight,unit='g',preparation='Boiled')],note='')


@pytest.mark.parametrize('prompt',['先把这几餐整理成可编辑的草稿','请你先把这几餐整理成可编辑的草稿。'])
def test_batch_keeps_separate_meals_and_historical_user_amounts(prompt):
    client=Mock(usage=[])
    client.chat.side_effect=[json.dumps(dict(intent='tool',reply='',meal=None,tool=dict(name='create_meal_drafts',arguments={'meals':[meal('Breakfast',100),meal('Dinner',150)]}))),json.dumps(dict(intent='chat',reply='已整理为两份可编辑草稿，尚未保存。',meal=None))]
    r=REAL_RESPOND(prompt,history=[dict(role='user',text='早餐100g鸡蛋，晚餐150g鸡蛋')],client=client,language='zh-Hans')
    assert len(r['drafts'])==2 and r['drafts'][0]['id']!=r['drafts'][1]['id']
    assert [d['items'][0]['quantity'] for d in r['drafts']]==[100,150]
    assert all(d['items'][0]['details']['quantity_origin']=='User' for d in r['drafts'])
    assert list_meals()==[]


def test_transport_aliases_are_normalized_without_trusting_nutrients():
    data=meal('Lunch',1);item=data['items'][0]
    item.update(unit='slice',preparation='stir-fried',calories=999,estimated_grams=30,estimate_basis='Typical portion.')
    normalized=agent.normalize_batch_meal(data)['items'][0]
    assert normalized['unit']=='piece' and normalized['preparation']=='Fried'
    assert 'calories' not in normalized and normalized['details']['estimated_grams']==30


def test_unknown_draft_is_not_zero_and_goals_are_reviewed_without_mutation():
    unknown={**fresh_draft(),'items':[dict(name='unknown food xyz',quantity=None,unit='g',preparation='Not specified')]}
    assert analyze_drafts([unknown])['combined_totals']['energy'] is None
    settings=dict(energy=2000,protein=200,carbs=500,fat=50);before=deepcopy(settings)
    reviewed=review_goals(settings)
    assert reviewed['macro_energy_scenario']==3250 and reviewed['mismatch_kcal']==1250
    assert settings==before


@pytest.mark.parametrize('lang',['en','zh-Hans','zh-Hant'])
def test_ui_can_switch_edit_and_save_separate_drafts(lang,monkeypatch):
    drafts=[{**fresh_draft(),**meal(kind,weight)} for kind,weight in [('Breakfast',100),('Dinner',150)]]
    model=Mock(return_value=dict(intent='meal',draft=drafts[0],drafts=drafts,reply='草稿已备好。',usage=[]))
    monkeypatch.setattr(agent,'respond',model)
    app=AppTest.from_file(APP,default_timeout=30).run()
    next(s for s in app.selectbox if s.key=='language_choice').set_value(lang).run()
    app.chat_input[0].set_value('整理这两餐').run()
    assert not app.exception and len(app.session_state['draft_queue'])==1 and list_meals()==[]
    next(s for s in app.selectbox if s.key=='active_meal_draft').set_value(drafts[1]['id']).run()
    assert not app.exception and app.session_state['draft']['meal_type']=='Dinner'
    for checkbox in app.checkbox:
        if checkbox.label==tr('I reviewed the estimated portions and recipe assumptions',lang):checkbox.check()
    next(b for b in app.button if b.label==tr('Save meal',lang)).click().run()
    assert not app.exception and len(list_meals())==1
    assert list_meals()[0]['meal_type']=='Dinner' and app.session_state['draft']['meal_type']=='Breakfast'


def test_model_format_failure_is_a_conversation_without_food_format_error(monkeypatch):
    def fail(*args,**kwargs):raise agent.ConversationError('I understood your request, but could not complete the action reliably this time. Your messages and records are preserved. Please retry; you do not need to reformat your food description.')
    monkeypatch.setattr(agent,'respond',fail)
    app=AppTest.from_file(APP,default_timeout=30).run()
    app.chat_input[0].set_value('先整理这些餐点').run()
    assert not app.exception and not app.error
    assert app.session_state['messages'][-1]['role']=='assistant'
    assert list_meals()==[]
