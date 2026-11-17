"""Regression coverage for old multi-food meals and editable AI assumptions."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from fitplate import agent
from fitplate.domain import fresh_draft
from fitplate.meal_estimation import assess_meal, cautions_for, INGREDIENTS
from fitplate.model_client import ServiceError
from fitplate.reference_search import reference_candidates
from fitplate.portion_estimation import seed_portion_estimates
from fitplate.storage import connect, list_meals


APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def screenshot_meal():
    return {**fresh_draft(), 'date': '2026-11-11', 'meal_type': 'Lunch', 'items': [
        dict(name=n, quantity=q, unit=u, preparation=p) for n, q, u, p in [
            ('Tuna Salad', 50, 'g', 'Raw'), ('Seared Tuna Slices', 300, 'g', 'Grilled'),
            ('Avocado', 4, 'piece', 'Raw'), ('Orange Segments', 4, 'serving', 'Raw'),
            ('Pickled Ginger', 5, 'serving', 'Raw'), ('Crispy Wonton Strips', 4, 'serving', 'Fried')]]}


def plans():
    entries = [(1175160, None, 'Assume a separate mayonnaise-based tuna salad; confirm recipe and possible whole-dish overlap.'),
               (1172006, None, 'Cooked yellowfin tuna is an approximation for seared slices; doneness and retained oil are uncertain.'),
               (1171705, 60, 'Assume four avocado slices, 15 g each, 60 g total; not four whole avocados.'),
               (1169097, 40, 'Assume four orange segments, 10 g each, 40 g total; not four full servings.'),
               (1169765, 10, 'Assume five drained slices, 10 g total. Artificially sweetened reference may differ from actual sugar-pickled ginger.'),
               (None, 8, 'Assume four small fried wonton strips, 8 g total; wrapper/oil equivalents approximate unmeasured cooking moisture and oil.')]
    return {'plans': [dict(index=i, reference_food_id=fid,
                           components=[] if fid else [{'food_id': 1172802, 'fraction': .9}, {'food_id': INGREDIENTS['oil'], 'fraction': .1}],
                           estimated_grams=g, basis=b) for i, (fid, g, b) in enumerate(entries)]}


def client_for_plan():
    return Mock(usage=[], chat=Mock(return_value=json.dumps(plans())))


@pytest.mark.parametrize('name,prep,expected', [('Avocado', 'Raw', 1171705),
    ('Orange Segments', 'Raw', 1169097), ('Seared Tuna Slices', 'Grilled', 1172005),
    ('Crispy Wonton Strips', 'Fried', 1172802)])
def test_identity_search_reaches_sources_hidden_by_plural_or_cut_description(name, prep, expected):
    choices = reference_candidates(name, prep, dataset='USDA')
    if name == 'Seared Tuna Slices':
        assert expected in {c['food_id'] for c in choices[:3]}
        assert all('tuna' in c['name'].lower() and c['state'] == 'cooked' for c in choices[:3])
    else:
        assert choices[0]['food_id'] == expected
    assert not any('Oil, avocado' in c['name'] or 'Chicken Strips' in c['name'] for c in choices)


def test_whole_screenshot_meal_is_estimated_in_one_bounded_request_without_changing_inputs():
    original = screenshot_meal()
    before = deepcopy(original)
    client = client_for_plan()
    proposal = agent.reestimate(original, client)['draft']
    result = assess_meal(proposal)
    assert client.chat.call_count == 1
    assert 'json' in json.dumps(client.chat.call_args.args[0]).lower()
    assert original == before
    assert proposal['id'] == original['id']
    assert result['computed_count'] == result['total_count'] == 6
    assert result['requires_estimate_review'] and not proposal['estimate_reviewed']
    assert result['completeness'] == 'complete'
    assert all(value is not None and value > 0 for value in result['totals'].values())
    for old, new in zip(original['items'], proposal['items']):
        assert {k: old[k] for k in ('name', 'quantity', 'unit', 'preparation')} == {k: new[k] for k in ('name', 'quantity', 'unit', 'preparation')}
    assert result['items'][2]['quantity'] == 60
    assert sum(p['quantity'] for p in result['items'][5]['components']) == pytest.approx(8, abs=.001)
    assert 'Artificially sweetened' in ' '.join(result['items'][4]['assumptions'])
    assert cautions_for(proposal)
    assert list_meals() == []


def test_estimated_recipe_total_is_not_multiplied_by_count_twice():
    meal = agent.reestimate(screenshot_meal(), client_for_plan())['draft']
    meal['items'][5]['details']['estimated_grams'] = 12
    result = assess_meal(meal)
    assert sum(c['quantity'] for c in result['items'][5]['components']) == pytest.approx(12, abs=.001)
    meal['items'][2]['confirmed_grams'] = 95
    assert assess_meal(meal)['items'][2]['quantity'] == 95


def test_slice_whole_and_count_edits_refresh_assumptions_locally():
    meal = agent.reestimate(screenshot_meal(), client_for_plan())['draft']
    avocado = meal['items'][2]
    avocado['details']['portion_form'] = 'Whole'
    seed_portion_estimates(meal)
    assert assess_meal(meal)['items'][2]['quantity'] == 560
    avocado['quantity'] = 1
    avocado['details'].pop('estimated_grams')
    seed_portion_estimates(meal)
    assert assess_meal(meal)['items'][2]['quantity'] == 140
    assert avocado['quantity'] == 1 and avocado['unit'] == 'piece'


def test_ai_estimate_failure_is_transactional_and_has_one_format_correction():
    original = screenshot_meal()
    before = deepcopy(original)
    client = Mock(usage=[], chat=Mock(return_value=json.dumps({'plans': plans()['plans'][:2]})))
    with pytest.raises(ServiceError, match='one correction'):
        agent.reestimate(original, client)
    assert client.chat.call_count == 2
    assert original == before
    assert not list_meals()


def test_service_failure_is_not_retried_and_preserves_input():
    original = screenshot_meal()
    before = deepcopy(original)
    client = Mock(usage=[], chat=Mock(side_effect=ServiceError('Temporarily unavailable.')))
    with pytest.raises(ServiceError):
        agent.reestimate(original, client)
    assert client.chat.call_count == 1
    assert original == before


def test_unresolved_food_has_no_fabricated_zero_nutrition():
    original = {**fresh_draft(), 'items': [dict(name='Unidentified food', quantity=None, unit='g', preparation='Not specified')]}
    client = Mock(usage=[], chat=Mock(return_value=json.dumps({'plans': [dict(index=0, reference_food_id=None,
                    components=[], estimated_grams=None, basis='No defensible identity supplied.')]})))
    with pytest.raises(ServiceError, match='No defensible'):
        agent.reestimate(original, client)
    assert original['items'][0]['quantity'] is None
    assert assess_meal(original)['totals']['energy'] is None


def test_known_manual_reference_gets_weight_without_changing_identity():
    original = {**fresh_draft(), 'items': [dict(name='Avocado', quantity=4, unit='piece', preparation='Raw', food_id=1171705)]}
    plan = dict(index=0, reference_food_id=1171705, components=[], estimated_grams=60, basis='Assume four slices, 60 g total.')
    client = Mock(usage=[], chat=Mock(return_value=json.dumps({'plans': [plan]})))
    proposed = agent.reestimate(original, client)['draft']
    assert proposed['items'][0]['food_id'] == 1171705
    assert assess_meal(proposed)['computed_count'] == 1


def test_follow_up_size_change_invalidates_the_old_total_weight():
    previous = agent.reestimate(screenshot_meal(), client_for_plan())['draft']
    items = [{k: i[k] for k in ('name', 'quantity', 'unit', 'preparation')} for i in previous['items']]
    items[2]['details'] = {'portion_size': 'Large'}
    output = dict(intent='meal', reply='Review', meal=dict(date=previous['date'], meal_type='Lunch', items=items, note=''))
    updated = agent.decode_result(json.dumps(output), previous, 'Text')['draft']
    assert 'estimated_grams' not in updated['items'][2]['details']


def insert_old_meal(meal):
    with connect() as db:
        db.execute('INSERT INTO meals VALUES (?, ?, ?)', (meal['id'], json.dumps(meal), '2026-11-11'))


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def test_old_record_reanalysis_is_explicit_and_save_updates_same_record(monkeypatch):
    meal = screenshot_meal()
    insert_old_meal(meal)
    before = list_meals()
    proposed = agent.reestimate(meal, client_for_plan())
    reanalyse = Mock(return_value=proposed)
    monkeypatch.setattr(agent, 'reestimate', reanalyse)
    app = AppTest.from_file(APP, default_timeout=30).run()
    click(app, 'Meal records')
    assert reanalyse.call_count == 0
    click(app, 'Reanalyse with AI')
    assert reanalyse.call_count == 1
    assert list_meals() == before
    assert any('≈' in m.value for m in app.metric)
    app.run()
    assert reanalyse.call_count == 1
    assert next(f for f in app.number_input if f.label == 'Estimated total weight (g) 3').value == 60
    next(f for f in app.number_input if f.label == 'Estimated total weight (g) 3').set_value(80)
    next(c for c in app.checkbox if c.label == 'I reviewed the estimated portions and recipe assumptions').check()
    click(app, 'Save meal')
    saved = list_meals()
    assert len(saved) == 1 and saved[0]['id'] == meal['id']
    assert saved[0]['nutrition']['computed_count'] == 6
    assert saved[0]['nutrition']['items'][2]['quantity'] == 80


def test_failed_record_reanalysis_keeps_saved_meal(monkeypatch):
    meal = screenshot_meal()
    insert_old_meal(meal)
    before = list_meals()
    monkeypatch.setattr(agent, 'reestimate', Mock(side_effect=ServiceError('Temporarily unavailable.')))
    app = AppTest.from_file(APP, default_timeout=30).run()
    click(app, 'Meal records')
    click(app, 'Reanalyse with AI')
    assert app.error
    assert app.session_state['draft'] is None
    assert list_meals() == before
