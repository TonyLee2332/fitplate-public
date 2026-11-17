from copy import deepcopy
import math
import pytest
from fitplate.meal_estimation import assess_meal
from fitplate.nutrition import DEFAULT_DB
from fitplate.auto_estimation import prepare_auto_estimates


def item(name,quantity=1,unit='piece',preparation='Not specified',**extra):
    return dict(name=name,quantity=quantity,unit=unit,preparation=preparation,**extra)


@pytest.mark.parametrize('food',[item('Blueberry',10),item('Whole wheat bread'),item('Protein powder shake',1,'serving'),item('Scrambled eggs',2,preparation='Cooked'),item('Mushrooms',3,preparation='Cooked'),item('Milk',200,'ml'),item('全麦面包'),item('蓝莓',10)])
def test_common_unresolved_foods_get_traceable_numbers_without_activation(food):
    meal={'items':[food]};before=deepcopy(meal)
    result=assess_meal(meal)
    assert result['computed_count']==1 and result['total_count']==1
    assert all(result['items'][0][key] is not None and math.isfinite(result['items'][0][key]) for key in ('energy','protein','carbs','fat'))
    assert result['items'][0]['source'] and meal==before
    assert result['items'][0]['assumptions']


def test_fresh_blueberries_and_bread_use_source_household_measures():
    a=assess_meal({'items':[item('Blueberry',10)]})['items'][0]
    b=assess_meal({'items':[item('Whole wheat bread')]})['items'][0]
    assert a['food_id']==1171711 and a['quantity']==pytest.approx(13.6)
    assert b['food_id']==1172688 and b['quantity']==32
    assert a['portion_source']['id']==89239 and b['portion_source']['id']==91108


def test_confirmed_weight_and_user_selected_source_take_precedence():
    food=item('Whole wheat bread',2,confirmed_grams=80,food_id=1172688)
    r=assess_meal({'items':[food]})['items'][0]
    assert r['food_id']==1172688 and r['quantity']==80


def test_reviewed_proposals_are_kept_and_unreviewed_guesses_use_source_measures():
    food=item('Blueberry',10,details=dict(estimated_grams=50,estimate_basis='Visual assumption.'))
    assert assess_meal({'items':[food]})['items'][0]['quantity']==pytest.approx(13.6)
    assert assess_meal({'items':[food],'estimate_reviewed':True})['items'][0]['quantity']==50


def test_explicit_grams_are_not_multiplied_by_count_or_serving():
    food=item('Whole wheat bread',100,'g')
    r=assess_meal({'items':[food]})['items'][0]
    assert r['quantity']==100
    assert r['energy']==pytest.approx(DEFAULT_DB.by_id[1172688].kcal)


def test_identifiable_mixed_dish_has_sourced_components_and_labeled_assumptions():
    food=item('Chicken with rice and broccoli',300,'g','Cooked')
    r=assess_meal({'items':[food]})
    assert r['computed_count']==1 and r['items'][0]['components']
    assert r['items'][0]['estimated'] and any('ingredient-equivalent' in a for a in r['items'][0]['assumptions'])


def test_missing_identity_and_invalid_input_do_not_receive_fabricated_zeroes():
    for food in [item('unknown food xyz',100,'g'),item(''),item('Whole wheat bread',-1,'g')]:
        r=assess_meal({'items':[food]})
        assert r['computed_count']==0 and r['totals']['energy'] is None


def test_strict_mode_remains_available_to_explicit_ai_planners():
    meal={'items':[item('Blueberry',10)]}
    assert assess_meal(meal,automatic=False)['computed_count']==0
    assert assess_meal(meal)['computed_count']==1


def test_processed_foods_are_not_replaced_with_their_raw_ingredient():
    from fitplate.auto_estimation import select_reference
    assert select_reference('Blueberry muffin','Not specified')[0]!=1171711
    assert select_reference('Mushroom pizza','Cooked')[0] not in (1169251,1169252)
    assert select_reference('Whole wheat bread with butter','Not specified')[0] not in (1172688,1172689)


def test_automatic_estimation_never_calls_a_remote_model(monkeypatch):
    from unittest.mock import Mock
    from fitplate import model_client
    remote=Mock(side_effect=AssertionError('Unexpected remote request'))
    monkeypatch.setattr(model_client,'post_json',remote)
    result=assess_meal({'items':[item('Blueberry',10),item('Whole wheat bread'),item('Protein powder shake',1,'serving')]})
    assert result['computed_count']==3 and remote.call_count==0


def test_automatic_results_work_with_existing_uncertainty_tools():
    from fitplate.uncertainty import sample_meal
    result=sample_meal({'items':[item('Blueberry',10)]},samples=64)
    assert result['statistics']['energy']['p05']<result['statistics']['energy']['p95']


def test_sourced_scrambled_egg_does_not_add_oil_twice():
    result=assess_meal({'items':[item('Scrambled eggs',100,'g','Fried')]})['items'][0]
    assert result['food_id']==1172187
    assert result['energy']==pytest.approx(DEFAULT_DB.by_id[1172187].kcal)


def test_bad_quantities_are_not_replaced_by_guessed_portions():
    for quantity in ('not a number',False,-1,float('nan')):
        result=assess_meal({'items':[item('Blueberry',quantity)]})
        assert result['computed_count']==0 and result['totals']['energy'] is None


def test_generic_foods_do_not_match_related_species_parts_or_processed_products():
    from fitplate.auto_estimation import select_reference
    for name,disallowed in [('Apple',('rose-apple',)),('Potato',('leaf','bread',', skin [','fried')),('Tomato',('babyfood','puree','paste')),('Salmon',('smoked',)),('Milk',('sheep','goat'))]:
        fid,_=select_reference(name,'Not specified')
        assert fid is not None
        assert not any(word in DEFAULT_DB.by_id[fid].name.lower() for word in disallowed)
