from copy import deepcopy
import json
from unittest.mock import Mock
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from fitplate import agent
from fitplate.coaching import validate_profile,estimate_needs,execute_tool,intake_context,profile_context
from fitplate.storage import read_body_profile,save_body_profile,read_settings,save_settings,list_meals
from fitplate.i18n import tr

REAL_RESPOND=agent.respond
APP=str(Path(__file__).resolve().parents[1]/'app.py')


def profile(**changes):
    return {**dict(age=25,height_cm=175.0,weight_kg=70.0,goal='Build muscle',training_days=3,
                experience='Beginner',training_type='Strength training',activity='Lightly active',
                sex='Male',health='None reported',share_with_ai=True),**changes}


def tool(name,arguments=None):
    return json.dumps(dict(intent='tool',reply='',meal=None,tool=dict(name=name,arguments=arguments or {})))


def final(reply='Start with a manageable routine and review how you recover.'):
    return json.dumps(dict(intent='chat',reply=reply,meal=None))


def test_profile_storage_does_not_change_existing_targets_or_meals():
    assert read_body_profile()['share_with_ai'] is False
    settings=dict(name='User',focus='Build consistent habits',preferences='Vegetarian',allergies='Peanuts',energy=2200,protein=100,carbs=None,fat=None)
    save_settings(settings);save_body_profile(profile())
    assert read_body_profile()==profile() and read_settings()==settings and list_meals()==[]


@pytest.mark.parametrize('key,value',[('age',17),('age',float('nan')),('weight_kg',True),('height_cm',-1),('training_days',8),('training_days',2.5),('health','healthy'),('share_with_ai','yes')])
def test_profile_rejects_invalid_or_inapplicable_values(key,value):
    p=profile();p[key]=value
    with pytest.raises(ValueError):validate_profile(p)


def test_numbers_are_calculated_and_optional_sex_is_not_inferred():
    p=profile();before=deepcopy(p)
    result=estimate_needs(p)
    assert result['protein_g_per_day']==[98,140]
    assert result['resting_energy_kcal']==1674
    assert result['maintenance_energy_kcal']==2343
    assert p==before
    p['sex']='Not provided';result=estimate_needs(p)
    assert result['maintenance_energy_kcal'] is None and result['protein_g_per_day']==[98,140]


def test_restricted_or_unshared_profiles_do_not_produce_numeric_plans():
    p=profile();p['health']='Professional guidance needed'
    assert estimate_needs(p)['status']=='professional_review'
    p['health']='Not shared'
    assert estimate_needs(p)['status']=='needs_information'
    p['share_with_ai']=False
    assert estimate_needs(p)['status']=='not_shared'
    assert '70' not in json.dumps(profile_context(p))
    p=profile();p['weight_kg']=45
    assert estimate_needs(p)['status']=='professional_review'


def test_empty_days_remain_unknown_and_food_tool_uses_real_rows():
    result=intake_context([],{},3)
    assert len(result['days'])==3 and all(day['totals']['energy'] is None for day in result['days'])
    result=execute_tool('search_foods',{'query':'Egg'},None,[],{})
    assert result['foods'] and all(food['source_url'] and food['energy_kcal']>=0 for food in result['foods'])
    with pytest.raises(ValueError):execute_tool('save_targets',{'energy':1200},None,[],{})
    with pytest.raises(ValueError):execute_tool('summarize_intake',{'days':30},None,[],{})


def test_model_selects_tools_and_receives_results_without_writing():
    client=Mock(usage=[])
    client.chat.side_effect=[tool('estimate_needs'),tool('summarize_intake',{'days':2}),final('Your reference protein range is 98–140 g; there are no recorded meals to compare yet.')]
    p=profile();before=deepcopy(p)
    result=REAL_RESPOND('How can I support my training?',body_profile=p,client=client)
    assert [t['tool'] for t in result['tool_trace']]==['estimate_needs','summarize_intake']
    assert result['sources'] and client.chat.call_count==3 and p==before and list_meals()==[]
    client=Mock(usage=[]);client.chat.return_value=final('Hello! What would you like help with?')
    assert REAL_RESPOND('Hello',client=client)['tool_trace']==[]
    assert client.chat.call_count==1


def test_unshared_measurements_never_enter_model_messages():
    p=profile();p.update(weight_kg=73.9,share_with_ai=False)
    captures=[]
    replies=iter([tool('get_coaching_profile'),final('You can enable profile sharing or ask for general guidance.')])
    def answer(messages):captures.append(deepcopy(messages));return next(replies)
    client=Mock(usage=[]);client.chat.side_effect=answer
    REAL_RESPOND('Suggest a routine',body_profile=p,client=client)
    assert all('73.9' not in json.dumps(messages) for messages in captures)


def test_tool_and_format_budgets_stop_without_changing_draft():
    client=Mock(usage=[]);client.chat.return_value=tool('reference_guidance',{'topic':'training'})
    with pytest.raises(agent.ServiceError,match='tool limit'):REAL_RESPOND('Help me train',client=client)
    assert client.chat.call_count==5
    client=Mock(usage=[]);client.chat.return_value=tool('delete_meals')
    with pytest.raises(agent.ServiceError):REAL_RESPOND('Help',client=client)
    assert client.chat.call_count==2 and list_meals()==[]


def test_native_function_call_roundtrip_and_tool_role(monkeypatch):
    from fitplate import model_client
    requests=[]
    responses=iter([
        {'choices':[{'message':{'tool_calls':[{'id':'call_1','type':'function','function':{'name':'estimate_needs','arguments':'{}'}}]}}]},
        {'choices':[{'message':{'content':final('The reference range is 98–140 g of protein per day.')}}]},
    ])
    def request(config,path,payload):requests.append(deepcopy(payload));return next(responses)
    monkeypatch.setattr(model_client,'post_json',request)
    client=model_client.ModelClient(model_client.ModelConfig('fake-key','ws-example','cn-beijing'))
    result=REAL_RESPOND('How much protein?',body_profile=profile(),client=client)
    assert result['tool_trace'][0]['tool']=='estimate_needs'
    assert requests[0]['tool_choice']=='auto' and requests[0]['parallel_tool_calls'] is False
    assert 'response_format' not in requests[0]
    assert requests[1]['messages'][-1]['role']=='tool'
    assert requests[1]['messages'][-1]['tool_call_id']=='call_1'
    assert '98' in requests[1]['messages'][-1]['content']


def test_ungrounded_quantities_trigger_one_correction_and_json_fences_are_tolerated():
    client=Mock(usage=[])
    client.chat.side_effect=[final('Aim for 1.6–2.2 g/kg protein.'),tool('estimate_needs'),final('Your reference protein range is 98–140 g per day.')+'\n```']
    result=REAL_RESPOND('Help me eat for training',body_profile=profile(),client=client)
    assert result['tool_trace'][0]['tool']=='estimate_needs' and client.chat.call_count==3
    client=Mock(usage=[])
    client.chat.side_effect=[tool('estimate_needs'),final('Use a 300–500 kcal deficit.'),final('Use a 300 kcal deficit.')]
    p=profile();p['health']='Professional guidance needed'
    with pytest.raises(agent.ServiceError):REAL_RESPOND('Help me lose weight',body_profile=p,client=client)
    assert client.chat.call_count==3


@pytest.mark.parametrize('lang',['en','zh-Hans','zh-Hant'])
def test_profile_ui_saves_explicitly_and_coaching_keeps_draft(lang,monkeypatch):
    app=AppTest.from_file(APP,default_timeout=30).run()
    next(s for s in app.selectbox if s.key=='language_choice').set_value(lang).run()
    next(b for b in app.button if b.key=='profile_shortcut').click().run()
    assert not app.exception
    for key,value in [('body_age',25),('body_height',175.0),('body_weight',70.0),('body_days',3)]:
        next(n for n in app.number_input if n.key==key).set_value(value)
    for key,value in [('body_goal','Build muscle'),('body_training','Strength training'),('body_experience','Beginner'),('body_activity','Lightly active'),('body_health','None reported')]:
        next(s for s in app.selectbox if s.key==key).set_value(value)
    assert read_body_profile()['weight_kg'] is None
    next(b for b in app.button if b.label==tr('Save body & training profile',lang)).click().run()
    assert not app.exception and read_body_profile()['weight_kg']==70
    assert read_body_profile()['share_with_ai'] is False
    model=Mock(return_value=dict(intent='chat',reply='Start gradually.',draft=None,tool_trace=[dict(tool='reference_guidance',label='Nutrition & training references')]))
    monkeypatch.setattr(agent,'respond',model)
    next(b for b in app.button if b.label==tr('Ask for a diet & training suggestion',lang)).click().run()
    assert not app.exception and app.session_state['draft'] is None and list_meals()==[]
    assert model.call_args.kwargs['body_profile']['weight_kg']==70
    assert app.session_state['messages'][-1]['tool_trace']


def test_unsaved_body_fields_survive_language_switch_and_sharing_can_be_revoked():
    save_body_profile(profile())
    app=AppTest.from_file(APP,default_timeout=30).run()
    next(b for b in app.button if b.key=='profile_shortcut').click().run()
    next(n for n in app.number_input if n.key=='body_weight').set_value(72.5)
    next(s for s in app.selectbox if s.key=='language_choice').set_value('zh-Hant').run()
    assert not app.exception and next(n for n in app.number_input if n.key=='body_weight').value==72.5
    assert read_body_profile()['weight_kg']==70
    next(c for c in app.checkbox if c.key=='body_share').uncheck()
    next(b for b in app.button if b.label==tr('Save body & training profile','zh-Hant')).click().run()
    assert not app.exception and read_body_profile()['share_with_ai'] is False
    assert read_body_profile()['weight_kg']==72.5
