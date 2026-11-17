from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from fitplate import agent
from fitplate.domain import fresh_draft

REAL_RESPOND=agent.respond


def dinner():
    return {**fresh_draft(),'meal_type':'Dinner','items':[
        dict(name='Grilled steak',quantity=None,unit='g',preparation='Grilled',confirmed_grams=200,details=dict(estimated_grams=250,estimate_basis='Visual estimate.')),
        dict(name='Cooked white rice',quantity=150,unit='g',preparation='Cooked')]}


@pytest.mark.parametrize('text,quantity',[('350g',350),('350克',350),('0.35 kg',350),('350',350),('Actually 350 grams',350)])
def test_portion_patch_updates_only_chosen_item(text,quantity):
    draft=dinner();original=deepcopy(draft)
    result=agent.update_meal_portion(draft,dict(item_index=0,quantity=quantity,unit='g'),text)
    assert result['items'][0]['quantity']==350 and result['items'][0]['unit']=='g'
    assert 'confirmed_grams' not in result['items'][0]
    assert 'estimated_grams' not in result['items'][0]['details']
    assert result['items'][1]==original['items'][1] and draft==original
    assert result['id']==draft['id'] and result['meal_type']=='Dinner'


def test_followup_uses_question_and_does_not_reserialize_foods():
    client=Mock(usage=[])
    client.chat.side_effect=[json.dumps(dict(intent='tool',reply='',meal=None,tool=dict(name='update_meal_portion',arguments=dict(item_index=0,quantity=350,unit='g')))),
                             json.dumps(dict(intent='chat',reply='牛排份量已改為350克，米飯保持150克。',meal=None))]
    original=dinner()
    result=REAL_RESPOND('350g',draft=original,history=[dict(role='assistant',text='牛排是200g、300g還是其他重量？')],client=client,language='zh-Hant')
    assert result['intent']=='meal' and result['draft']['items'][0]['quantity']==350
    assert result['draft']['items'][1]==original['items'][1]
    assert result['tool_trace'][0]['tool']=='update_meal_portion'
    assert '牛排' in result['reply']


@pytest.mark.parametrize('arguments,text',[(dict(item_index=9,quantity=350,unit='g'),'350g'),(dict(item_index=0,quantity=300,unit='g'),'350g'),(dict(item_index=0,quantity=350,unit='ml'),'350g'),(dict(item_index=0,quantity=True,unit='g'),'350g')])
def test_invalid_patch_cannot_guess_or_change_other_units(arguments,text):
    with pytest.raises(ValueError):agent.update_meal_portion(dinner(),arguments,text)
