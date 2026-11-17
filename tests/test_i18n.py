from pathlib import Path
from copy import deepcopy
import json,re
import pytest
from streamlit.testing.v1 import AppTest
from fitplate.i18n import tr,html_text
from fitplate.domain import fresh_draft,today
from fitplate.meal_estimation import assess_meal
from fitplate.storage import read_language,save_language,save_settings,read_settings,list_meals
from fitplate import agent

APP=str(Path(__file__).resolve().parents[1]/'app.py')


def choose(app,lang):
    next(s for s in app.selectbox if s.key=='language_choice').set_value(lang).run()
    assert not app.exception


def click(app,label):
    next(b for b in app.button if b.label==label).click().run()
    assert not app.exception


def test_catalog_placeholders_and_golden_semantics():
    root=Path(__file__).resolve().parents[1]/'fitplate/data'
    hans=json.loads((root/'ui_zh_hans.json').read_text(encoding='utf-8'))
    hant=json.loads((root/'ui_zh_hant.json').read_text(encoding='utf-8'))
    assert set(hans)==set(hant)
    for source in hans:
        for target in [hans[source],hant[source]]:
            assert sorted(re.findall(r'\{\d+\}',source))==sorted(re.findall(r'\{\d+\}',target))
    assert tr('Protein','zh-Hans')=='蛋白质'
    assert tr('Protein','zh-Hant')=='蛋白質'
    assert tr('kcal','zh-Hant')=='千卡'
    assert tr('Save meal','zh-Hant')=='儲存餐點'
    assert '2' in tr('Portion 2','zh-Hans')


@pytest.mark.parametrize('lang',['zh-Hans','zh-Hant'])
def test_nested_pending_reasons_and_entity_labels_are_fully_translated(lang,monkeypatch):
    import streamlit as native
    from fitplate.i18n import has_english_prose
    for reason in ['Choose the matching food from the candidates.','Food not found. Select an alternative or supply a verified entry.','Confirm the complete dish or list its ingredients separately.']:
        assert not has_english_prose(tr('Food 1: '+reason,lang))
    monkeypatch.setitem(native.session_state,'language',lang)
    translated=html_text('<p>Body &amp; training profile</p><div class="user">&lt;script&gt;hello&lt;/script&gt;</div>')
    assert 'Body' not in translated and '&lt;script&gt;' in translated
    assert '<script>' not in translated


def test_chinese_reply_rejects_english_prose():
    raw=json.dumps(dict(intent='chat',reply='你好。You should follow this training plan every single day.',meal=None))
    with pytest.raises(ValueError,match='selected Chinese language'):
        agent.decode_result(raw,None,'Text',language='zh-Hant')


def test_language_preference_is_separate_from_profile():
    profile={'name':'User','focus':'Support my training','preferences':'No onions','allergies':'Peanuts'}
    save_settings(profile);save_language('zh-Hant')
    assert read_language()=='zh-Hant' and read_settings()==profile
    with pytest.raises(ValueError):save_language('invalid')


@pytest.mark.parametrize('lang',['en','zh-Hans','zh-Hant'])
def test_three_language_navigation_save_edit_and_internal_codes(lang):
    app=AppTest.from_file(APP,default_timeout=30).run();choose(app,lang)
    meal={**fresh_draft(),'items':[dict(name='Egg',quantity=100,unit='g',preparation='Boiled')]}
    before=assess_meal(meal)['totals']
    app.session_state['draft']=deepcopy(meal);app.session_state['draft_revision']+=1;app.run()
    assert not app.exception
    for checkbox in app.checkbox:
        if checkbox.label==tr('I reviewed the estimated portions and recipe assumptions',lang):checkbox.check()
    click(app,tr('Save meal',lang))
    saved=list_meals()[0]
    assert saved['items'][0]['unit']=='g' and saved['items'][0]['preparation']=='Boiled'
    assert saved['nutrition']['totals']==before
    click(app,tr('Meal records',lang))
    click(app,tr('Edit meal',lang))
    assert app.session_state['draft']['id']==meal['id']
    choose(app,'en')
    assert app.session_state['draft']['id']==meal['id']


def test_language_switch_preserves_unsaved_goal_values_and_draft():
    app=AppTest.from_file(APP,default_timeout=30).run()
    click(app,'Goals & insights')
    field=next(n for n in app.number_input if n.label=='Protein target (g)');field.set_value(123)
    choose(app,'zh-Hans')
    field=next(n for n in app.number_input if n.label==tr('Protein target (g)','zh-Hans'))
    assert field.value==123
    click(app,tr('Save targets','zh-Hans'))
    choose(app,'zh-Hant')
    assert read_settings()['protein']==123
    choose(app,'en')
    assert next(n for n in app.number_input if n.label=='Protein target (g)').value==123


def test_chinese_chat_reply_keeps_food_schema_english():
    payload={'intent':'chat','reply':'可以，我会帮助你记录饮食。','meal':None}
    result=agent.decode_result(json.dumps(payload),None,'Text',language='zh-Hans')
    assert result['reply']==payload['reply']
    with pytest.raises(ValueError):agent.decode_result(json.dumps(payload),None,'Text')


def test_ui_language_is_forwarded_to_ai(monkeypatch):
    from unittest.mock import Mock
    model=Mock(return_value=dict(intent='chat',reply='請描述這餐吃了甚麼。',draft=None,usage=[]))
    monkeypatch.setattr(agent,'respond',model)
    app=AppTest.from_file(APP,default_timeout=30).run();choose(app,'zh-Hant')
    app.chat_input[0].set_value('你好').run()
    assert not app.exception
    assert model.call_args.kwargs['language']=='zh-Hant'
    assert app.session_state['messages'][-2]['text']=='你好'


def test_source_filter_and_language_preference_survive_new_session():
    app=AppTest.from_file(APP,default_timeout=30).run();choose(app,'zh-Hant')
    click(app,tr('Add food manually','zh-Hant'))
    widget=next(s for s in app.selectbox if s.key=='reference_source');widget.set_value('USDA').run()
    choose(app,'zh-Hans')
    assert next(s for s in app.selectbox if s.key=='reference_source').value=='USDA'
    assert app.session_state['draft'] is not None
    fresh=AppTest.from_file(APP,default_timeout=30).run()
    assert fresh.session_state['language']=='zh-Hans'


def test_chinese_record_search_and_delete_preserve_canonical_data():
    from fitplate.storage import save_meal
    meal={**fresh_draft(),'estimate_reviewed':True,'items':[dict(name='Fried chicken',quantity=100,unit='g',preparation='Fried')]}
    save_meal(meal)
    app=AppTest.from_file(APP,default_timeout=30).run();choose(app,'zh-Hant')
    click(app,tr('Meal records','zh-Hant'))
    query=next(t for t in app.text_input if t.label==tr('Search foods','zh-Hant'))
    query.set_value('炸鸡').run()
    assert any(b.label==tr('Edit meal','zh-Hant') for b in app.button)
    assert list_meals()[0]['items'][0]['preparation']=='Fried'
    click(app,tr('Confirm delete','zh-Hant'))
    assert list_meals()==[]


@pytest.mark.parametrize('lang',['zh-Hans','zh-Hant'])
def test_advanced_tools_render_and_sample_in_chinese(lang):
    meal={**fresh_draft(),'items':[dict(name='Egg',quantity=100,unit='g',preparation='Boiled')]}
    app=AppTest.from_file(APP,default_timeout=30).run();choose(app,lang)
    app.session_state['draft']=meal;app.session_state['draft_revision']+=1;app.run()
    assert not app.exception
    click(app,tr('Run sampling analysis',lang))
    assert app.session_state['draft']['uncertainty_analysis']['samples']==256
    assert not app.exception
