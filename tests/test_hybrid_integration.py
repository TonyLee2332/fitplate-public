import csv
import io
import json
from copy import deepcopy
from pathlib import Path
import zipfile

import pytest
from streamlit.testing.v1 import AppTest
from fitplate.domain import fresh_draft
from fitplate.meal_estimation import assess_meal, questions_for
from fitplate.nutrition import DEFAULT_DB
from fitplate.reference_search import reference_candidates, hybrid_scores
from fitplate.source_portions import BY_ID, CATALOG, resolve_portion
from fitplate.question_priority import rank_questions
from fitplate.storage import save_meal, list_meals


def item(name='Avocado', quantity=2, **details):
    return dict(name=name, quantity=quantity, unit='piece', preparation='Raw',
                details=dict(reference_food_id=1171705, **details))


def test_source_rows_exactly_match_original_archive():
    archive = Path(__file__).resolve().parent / 'fixtures/usda_sr_legacy_2018.zip'
    if not archive.exists():
        pytest.skip('Original source archive is retained in the development workspace.')
    with zipfile.ZipFile(archive) as z:
        raw = z.read(CATALOG['source_file'])
    source = {int(r['id']): r for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))}
    assert len(BY_ID) == 14431
    for pid, r in BY_ID.items():
        assert r['food_id'] in DEFAULT_DB.by_id
        assert r['fdc_id'] == int(source[pid]['fdc_id'])
        assert r['grams'] == float(source[pid]['gram_weight'])
        assert r['amount'] == float(source[pid]['amount'])


def test_selected_portion_overrides_app_grams_but_not_confirmed_grams():
    food = item(source_portion_id=89226, estimated_grams=30)
    result = assess_meal({'items': [food]})
    assert result['computed_count'] == 1
    assert result['items'][0]['quantity'] == 402
    assert result['items'][0]['portion_source']['id'] == 89226
    food['confirmed_grams'] = 80
    assert assess_meal({'items': [food]})['items'][0]['quantity'] == 80


def test_portion_amount_denominator_and_cross_food_protection():
    pid = next(pid for pid, row in BY_ID.items() if row['amount'] != 1)
    row = BY_ID[pid]
    food = dict(name=DEFAULT_DB.by_id[row['food_id']].name, food_id=row['food_id'], quantity=2,
                unit='piece', preparation='Not specified', details=dict(source_portion_id=pid))
    assert resolve_portion(food)['calculated_grams'] == pytest.approx(2 * row['grams'] / row['amount'])
    wrong = item(source_portion_id=84230)
    with pytest.raises(ValueError, match='another food'):
        resolve_portion(wrong)


def test_portion_provenance_survives_storage():
    meal = {**fresh_draft(), 'items': [item(source_portion_id=89226)], 'estimate_reviewed': True}
    save_meal(meal)
    portion = list_meals()[0]['nutrition']['items'][0]['portion_source']
    assert portion['id'] == 89226 and portion['source_row'] > 1
    assert len(portion['file_sha256']) == 64


@pytest.mark.parametrize('query,expected', [('aubergine', 'Eggplant'), ('courgette', 'Zucchini'), ('prawns', 'shrimp'), ('garbanzo', 'Chickpea')])
def test_synonym_retrieval_and_semantic_channel(query, expected):
    rows = reference_candidates(query, 'Raw', dataset='USDA')
    assert rows and any(expected.lower() in row['name'].lower() for row in rows[:5])
    lexical, semantic, fused = hybrid_scores(query)
    assert lexical.max() > 0 and semantic.max() > .1 and fused.max() > 0


def test_ranking_scores_are_not_automatic_match_probabilities():
    assert reference_candidates('xyzunknown completelynonsense') == []
    assert DEFAULT_DB.match('Orange Segments').needs_confirmation
    assert not any('Oil, avocado' in r['name'] for r in reference_candidates('Avocado'))


def test_impact_question_ranking_is_independent_of_item_order():
    low = dict(name='Boiled spinach', quantity=10, unit='g', preparation='Boiled', details={})
    high = item(quantity=4, estimated_grams=60, estimated_portion_form='Slice')
    meal = {'items': [low, high]}
    before = deepcopy(meal)
    questions = questions_for(meal)
    assert 'Avocado' in questions[0]
    assert len(questions) <= 2 and meal == before
    ordered = rank_questions(meal, ['Was Boiled spinach weighed after draining, and was any oil or dressing added?'])
    assert ordered[0]['impact_score'] > ordered[-1]['impact_score']
    for food in meal['items']:
        food['details']['use_defaults'] = True
    assert questions_for(meal) == []


def test_source_portion_ui_edit_save_and_rerun():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
    app.session_state['draft'] = {**fresh_draft(), 'items': [item(quantity=1, estimated_grams=60)]}
    app.session_state['draft_revision'] += 1
    app.run()
    field = next(f for f in app.selectbox if f.label == 'Source portion 1')
    field.set_value(89226)
    next(c for c in app.checkbox if c.label == 'I reviewed the estimated portions and recipe assumptions').check()
    next(b for b in app.button if b.label == 'Save meal').click().run()
    assert not app.exception
    assert list_meals()[0]['nutrition']['items'][0]['quantity'] == 201
    assert list_meals()[0]['nutrition']['items'][0]['portion_source']['id'] == 89226
