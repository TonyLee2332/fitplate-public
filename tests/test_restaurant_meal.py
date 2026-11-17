from copy import deepcopy
from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest
from fitplate.domain import fresh_draft
from fitplate.meal_estimation import assess_meal
from fitplate.portion_estimation import seed_portion_estimates
from fitplate import agent
from fitplate.reference_search import reference_candidates
from fitplate.storage import connect, list_meals, save_meal


def restaurant_meal():
    data=[('Fried chicken',3,'piece','Fried','Typical 3 pieces.'),
          ('Chicken burger with barbecue sauce and vegetables',1,'piece','Not specified','One sandwich.'),
          ('Ice cream',1,'serving','Not specified','One scoop.'),
          ('Sweetened milkshake',1,'ml','Not specified','One drink approximately 400g.')]
    return {**fresh_draft(),'items':[dict(name=n,quantity=q,unit=u,preparation=p,details=dict(use_defaults=True,estimate_basis=b)) for n,q,u,p,b in data],
            'estimation_notice':'Some AI food matches could not be validated.'}


def test_screenshot_meal_has_complete_local_preview_with_explicit_proxy_assumptions():
    m=restaurant_meal();original=deepcopy(m);result=assess_meal(m)
    assert m==original
    assert result['computed_count']==result['total_count']==4
    assert result['requires_estimate_review']
    assert all(result['totals'][k]>0 for k in result['totals'])
    assert 'barbecue' in ' '.join(result['items'][1]['assumptions']).lower()
    assert any('conflicts' in s for s in result['items'][3]['assumptions'])
    seed_portion_estimates(m)
    assert m['items'][3]['quantity']==1 and m['items'][3]['unit']=='ml'
    assert m['items'][3]['details']['estimated_grams']==313
    m['estimate_reviewed']=True
    save_meal(m)
    assert 'estimation_notice' not in list_meals()[0]


def test_fried_chicken_and_long_burger_name_retrieve_whole_foods():
    rows=reference_candidates('Fried chicken','Fried',5,dataset='USDA')
    assert rows[0]['food_id']==1170359
    assert not any(any(w in r['name'].lower() for w in ['liver','gizzard','heart']) for r in rows)
    assert reference_candidates('Chicken burger with barbecue sauce and vegetables',dataset='USDA')[0]['food_id']==1170318


def test_count_is_not_a_reason_to_delete_the_proposed_total_weight():
    draft={'items':[dict(name='Fried chicken',quantity=3,unit='piece',preparation='Fried',details=dict(estimated_grams=250))]}
    agent._guard_quantities(draft,'3 pieces of fried chicken',None)
    assert draft['items'][0]['details']['estimated_grams']==250


def test_literal_one_ml_is_not_converted_into_a_whole_drink():
    m=restaurant_meal();m['items']=m['items'][3:]
    m['items'][0]['details']['estimate_basis']=''
    assert assess_meal(m)['items'][0]['quantity']==pytest.approx(1.05)


def test_correcting_drink_unit_rebuilds_the_estimated_total():
    m=restaurant_meal();seed_portion_estimates(m)
    drink=m['items'][3];drink['unit']='serving';drink['details'].pop('estimated_grams')
    seed_portion_estimates(m)
    assert drink['quantity']==1 and drink['details']['estimated_grams']==313
    assert assess_meal(m)['computed_count']==4


def test_failed_zero_result_is_not_saved_as_a_success():
    m={**fresh_draft(),'items':[dict(name='xyzunknown',quantity=100,unit='g',preparation='Raw')],
       'estimation_notice':'Matching failed.'}
    with pytest.raises(ValueError,match='incomplete'):
        save_meal(m)
    assert list_meals()==[]


def test_old_restaurant_record_previews_without_model_calls_or_silent_storage_changes(monkeypatch):
    from unittest.mock import Mock
    m=restaurant_meal();m['estimate_reviewed']=True
    with connect() as db:
        db.execute('INSERT INTO meals VALUES (?,?,?)',(m['id'],json.dumps(m),'2026-11-16'))
    before=list_meals()
    model=Mock(side_effect=AssertionError('No model call on record rendering'))
    monkeypatch.setattr(agent,'reestimate',model)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    next(b for b in app.button if b.label=='Meal records').click().run()
    assert not app.exception
    assert any('4/4 foods calculated' in c.value for c in app.caption)
    assert any('conflicts' in w.value for w in app.warning)
    assert any(b.label=='Review estimate' for b in app.button)
    assert model.call_count==0 and list_meals()==before
