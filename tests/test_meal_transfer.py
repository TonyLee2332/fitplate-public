import csv
import io
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from fitplate.domain import fresh_draft, today
from fitplate.i18n import tr
from fitplate.meal_transfer import COLUMNS, TransferError, export_csv, export_json, parse_import, import_meals
from fitplate.nutrition.service import enrich_meal, fingerprint, snapshot, daily_summary
from fitplate.storage import list_meals, save_meal

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def meal():
    return enrich_meal({**fresh_draft(), 'date': (today()-timedelta(days=2)).isoformat(),
                       'estimate_reviewed': True, 'note': '=SUM(1,2)\n中文備註, with comma',
                       'items': [dict(name='Egg', quantity=100, unit='g', preparation='Boiled'),
                                 dict(name='Rice', quantity=120, unit='g', preparation='Cooked')]})


def legacy_csv(records):
    rows = list(csv.DictReader(io.StringIO(export_csv(records).decode('utf-8-sig'))))
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=COLUMNS[:22], extrasaction='ignore')
    writer.writeheader(); writer.writerows(rows)
    return output.getvalue().encode('utf-8')


@pytest.mark.parametrize('fmt', ['csv', 'json'])
def test_complete_roundtrip_preserves_source_results_and_portions(fmt):
    original = meal()
    encode = export_csv if fmt == 'csv' else export_json
    batch = parse_import(encode([original]), 'history.'+fmt)
    assert batch['meals'] == [original]
    assert import_meals(batch) == {'imported': 1, 'skipped': 0}
    restored = list_meals()[0]
    assert restored['items'] == original['items']
    assert restored['note'] == original['note']
    assert snapshot(restored) == snapshot(original)
    assert restored['import_info']['format'] == 'complete_backup'
    assert daily_summary([restored], original['date'])['totals'] == daily_summary([original], original['date'])['totals']


def test_pending_confirmation_snapshot_and_unknown_source_roundtrip():
    original = meal()
    result = original['nutrition']
    result['completeness'] = 'pending_confirmation'
    result['nutrition_status'] = 'Partial estimate'
    result['items'][0].update(name=None, needs_confirmation=True, source=None)
    result['items'][0]['components'] = [dict(name=None, needs_confirmation=True, quantity=None)]
    assert parse_import(export_csv([original]), 'history.csv')['meals'] == [original]


def test_repeated_import_skips_id_and_does_not_overwrite_edited_local_record():
    original = meal()
    batch = parse_import(export_json([original]), 'history.json')
    import_meals(batch)
    changed = deepcopy(original); changed['items'][0]['quantity'] = 175
    save_meal(changed)
    before = list_meals()
    assert import_meals(batch) == {'imported': 0, 'skipped': 1}
    assert list_meals() == before


def test_legacy_csv_groups_foods_and_preserves_exported_values():
    original = meal()
    batch = parse_import(legacy_csv([original]), 'old.csv')
    assert batch['legacy']
    assert len(batch['meals']) == 1 and len(batch['meals'][0]['items']) == 2
    import_meals(batch)
    restored = list_meals()[0]
    assert restored['note'] == original['note']
    for index, detail in enumerate(restored['nutrition']['items']):
        assert detail['source']['source'] == original['nutrition']['items'][index]['source']['source']
        for nutrient in ('energy', 'protein', 'carbs', 'fat'):
            assert detail[nutrient] == original['nutrition']['items'][index][nutrient]
    assert daily_summary([restored], restored['date'])['computed_items'] == 2


def test_missing_legacy_nutrients_stay_unknown_and_source_stays_visible():
    rows = list(csv.DictReader(io.StringIO(legacy_csv([meal()]).decode('utf-8'))))
    for row in rows:
        for column in ('energy_kcal', 'protein_g', 'carbs_g', 'fat_g'):
            row[column] = ''
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=COLUMNS[:22]); writer.writeheader(); writer.writerows(rows)
    batch = parse_import(output.getvalue().encode(), 'old.csv')
    result = batch['meals'][0]['nutrition']
    assert result['totals'] == dict.fromkeys(('energy', 'protein', 'carbs', 'fat'))
    assert result['computed_count'] == 0
    assert result['items'][0]['source']['source']
    import_meals(batch)
    assert daily_summary(list_meals(), batch['meals'][0]['date'])['totals']['energy'] is None


def test_legacy_zero_nutrients_are_not_missing():
    rows = list(csv.DictReader(io.StringIO(legacy_csv([meal()]).decode('utf-8'))))
    for row in rows:
        for column in ('energy_kcal', 'protein_g', 'carbs_g', 'fat_g'):
            row[column] = '0'
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=COLUMNS[:22]); writer.writeheader(); writer.writerows(rows)
    result = parse_import(output.getvalue().encode(), 'old.csv')['meals'][0]['nutrition']
    assert result['computed_count'] == 2 and all(v == 0 for v in result['totals'].values())


@pytest.mark.parametrize('column,value', [('quantity', '-1'), ('energy_kcal', 'nan'), ('date', '2099-01-01'), ('food', 'Changed name')])
def test_invalid_or_edited_csv_does_not_write_any_records(column, value):
    rows = list(csv.DictReader(io.StringIO(export_csv([meal()]).decode('utf-8-sig'))))
    rows[-1][column] = value
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=COLUMNS); writer.writeheader(); writer.writerows(rows)
    with pytest.raises(TransferError):
        parse_import(output.getvalue().encode(), 'history.csv')
    assert list_meals() == []


def test_all_or_nothing_validation_and_duplicate_ids():
    good = meal(); bad = deepcopy(good); bad['id'] = 'bad-id'; bad['items'][0]['quantity'] = -5
    with pytest.raises(TransferError):
        import_meals({'meals': [good, bad], 'legacy': False})
    assert list_meals() == []
    with pytest.raises(TransferError, match='repeated meal IDs'):
        parse_import(export_json([good, good]), 'history.json')
    assert list_meals() == []


def test_multiline_unicode_csv_survives_reordered_food_rows():
    original = meal()
    rows = list(csv.DictReader(io.StringIO(export_csv([original]).decode('utf-8-sig'))))
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=COLUMNS); writer.writeheader(); writer.writerows(reversed(rows))
    assert parse_import(output.getvalue().encode(), 'history.csv')['meals'] == [original]


@pytest.mark.parametrize('data,name', [(b'not a backup', 'history.json'), (b'a,b\n1,2', 'history.csv'), (b'', 'history.csv'), (b'\xff', 'history.csv')])
def test_unreadable_files_fail_cleanly(data, name):
    with pytest.raises(TransferError):
        parse_import(data, name)


@pytest.mark.parametrize('lang', ['en', 'zh-Hans', 'zh-Hant'])
def test_import_preview_confirm_and_reopen_in_three_languages(monkeypatch, lang):
    original = meal()
    uploaded = SimpleNamespace(name='history.json', getvalue=lambda: export_json([original]))
    monkeypatch.setattr('streamlit.file_uploader', lambda *a, **kw: uploaded)
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.session_state.language = lang
    next(b for b in app.button if b.key=='nav_Meal records').click().run()
    assert not app.exception
    assert list_meals() == []
    next(b for b in app.button if b.key=='confirm_meal_import').click().run()
    assert not app.exception and len(list_meals()) == 1
    assert any(tr('Imported record.',lang).split('.')[0] in c.value for c in app.caption) or any(tr('Imported record. Saved nutrition values are preserved as provided; importing does not independently verify or recalculate them.',lang) == c.value for c in app.caption)
    assert next(b for b in app.button if b.key=='confirm_meal_import').disabled
    reopened = AppTest.from_file(APP, default_timeout=30).run()
    next(b for b in reopened.button if b.key=='nav_Meal records').click().run()
    assert not reopened.exception
    assert any(b.key==f"edit_{original['id']}" for b in reopened.button)
    next(b for b in reopened.button if b.key=='nav_Goals').click().run()
    assert not reopened.exception


def test_database_error_rolls_back_the_entire_batch():
    import sqlite3
    from fitplate.storage import connect
    first = meal(); second = meal(); second['id'] = 'reject-import'
    second['nutrition']['input_fingerprint'] = fingerprint(second)
    with connect() as db:
        db.execute("CREATE TRIGGER reject_import BEFORE INSERT ON meals WHEN NEW.id='reject-import' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        import_meals({'meals': [first, second], 'legacy': False})
    assert list_meals() == []


@pytest.mark.parametrize('value', [10**400, '100'])
def test_invalid_json_number_types_fail_without_an_overflow(value):
    original = meal(); original['items'][0]['quantity'] = value
    with pytest.raises(TransferError):
        parse_import(export_json([original]), 'history.json')


def test_json_digit_limit_fails_with_a_readable_transfer_error():
    with pytest.raises(TransferError):
        parse_import(('{"value":'+('1'*5000)+'}').encode(), 'history.json')


def test_missing_portion_field_is_rejected_before_rendering_records():
    original = meal(); del original['items'][0]['quantity']
    with pytest.raises(TransferError):
        parse_import(export_json([original]), 'history.json')
