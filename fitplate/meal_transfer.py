"""Versioned meal transfers with legacy CSV support and atomic, add-only imports."""
import csv
import io
import json
import math
import re
from copy import deepcopy
from datetime import date, datetime, timezone

from fitplate.domain import UNITS, PREPARATIONS, today
from fitplate.nutrition.service import fingerprint, snapshot

MAX_BYTES = 10 * 1024 * 1024
MAX_MEALS = 2000
KEYS = ('energy', 'protein', 'carbs', 'fat')
COLUMNS = ('meal_id', 'date', 'meal', 'food', 'quantity', 'unit', 'preparation', 'note',
           'nutrition_status', 'food_id', 'calculated_portion_grams', 'calculation_grams',
           'energy_kcal', 'protein_g', 'carbs_g', 'fat_g', 'source', 'source_version',
           'source_verification', 'estimate_kind', 'estimate_assumptions', 'ingredient_breakdown_json',
           'format_version', 'item_index', 'meal_payload_json')
REQUIRED = {'meal_id', 'date', 'meal', 'food', 'quantity', 'unit', 'preparation'}


class TransferError(ValueError):
    pass


def fail(message):
    raise TransferError(message)


def _number(value, *, positive=False):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        fail('Numeric fields must contain finite, non-negative numbers.')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        fail('Numeric fields must contain finite, non-negative numbers.')
    if not math.isfinite(number) or number < 0 or positive and number <= 0:
        fail('Numeric fields must contain finite, non-negative numbers.')
    return number


def _saved_number(value, *, positive=False):
    if value is not None and type(value) not in (int, float):
        fail('Numeric fields must contain finite, non-negative numbers.')
    return _number(value, positive=positive)


def _safe_tree(value, depth=0):
    if depth > 30:
        fail('The backup structure is too deeply nested.')
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('source_ref', 'source_url', 'method') and isinstance(child, str) and re.match(r'(?i)\s*(javascript|vbscript|data|file):', child):
                fail('The file contains an unsupported source link.')
            _safe_tree(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _safe_tree(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        fail('Numeric fields must contain finite, non-negative numbers.')
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        fail('The backup contains an unsupported value.')


def validate_meal(meal):
    if not isinstance(meal, dict):
        fail('Each meal must be an object with an ID, date and foods.')
    _safe_tree(meal)
    if not isinstance(meal.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', meal['id']):
        fail('Each meal needs a valid, non-empty meal ID.')
    try:
        recorded = date.fromisoformat(meal['date'])
        if recorded.isoformat() != meal['date'] or recorded > today():
            raise ValueError
    except (ValueError, TypeError, KeyError):
        fail('Meal dates must use YYYY-MM-DD and cannot be in the future.')
    if meal.get('meal_type') not in ('Breakfast', 'Lunch', 'Dinner', 'Snack'):
        fail('Meal types must be Breakfast, Lunch, Dinner or Snack.')
    items = meal.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        fail('Each meal must contain between 1 and 100 foods.')
    if not isinstance(meal.get('note', ''), str):
        fail('Meal notes must be text.')
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'].strip():
            fail('Every food needs a name.')
        if item.get('unit') not in UNITS or item.get('preparation') not in PREPARATIONS:
            fail('The file contains an unsupported unit or preparation.')
        if 'quantity' not in item:
            fail('Every food needs a portion field, even when the amount is unknown.')
        quantity = _saved_number(item.get('quantity'), positive=True)
        if quantity is not None and quantity > 100000:
            fail('Food portions cannot exceed 100,000 units.')
        if item.get('confirmed_grams') is not None:
            _saved_number(item['confirmed_grams'], positive=True)
        if item.get('details') is not None and not isinstance(item['details'], dict):
            fail('Food details must be an object.')
        if item.get('food_id') is not None and (type(item['food_id']) is not int or item['food_id'] <= 0):
            fail('Food IDs must be positive integers.')
    nutrition = meal.get('nutrition')
    if nutrition is not None:
        _validate_snapshot(meal, nutrition)
    return meal


def _validate_snapshot(meal, result):
    if not isinstance(result, dict) or result.get('input_fingerprint') != fingerprint(meal):
        fail('A saved nutrition result does not match its meal details.')
    if not isinstance(result.get('items'), list) or len(result['items']) != len(meal['items']):
        fail('The saved nutrition result has an invalid food count.')
    if result.get('total_count') != len(meal['items']) or type(result.get('computed_count')) is not int or not 0 <= result['computed_count'] <= result['total_count']:
        fail('The saved nutrition result has an invalid food count.')
    if result.get('completeness') not in ('complete', 'partial', 'none', 'pending_confirmation') or not isinstance(result.get('nutrition_status'), str):
        fail('The saved nutrition result has an invalid status.')
    if not isinstance(result.get('totals'), dict) or not set(KEYS) <= result['totals'].keys():
        fail('The saved nutrition result is missing nutrient fields.')
    for key in KEYS:
        _saved_number(result['totals'][key])
    for key in ('warnings', 'pending_items'):
        if not isinstance(result.get(key), list):
            fail('The saved nutrition result has an invalid detail list.')
    if not all(isinstance(x, str) for x in result['warnings']):
        fail('Nutrition warnings must be text.')
    for pending in result['pending_items']:
        if not isinstance(pending, dict) or type(pending.get('input_index')) is not int or not 0 <= pending['input_index'] < len(meal['items']) or not isinstance(pending.get('reason'), str):
            fail('The saved nutrition result has an invalid detail list.')
    for item in result['items']:
        if not isinstance(item, dict) or not (isinstance(item.get('name'), str) or item.get('name') is None and item.get('needs_confirmation') is True):
            fail('The saved nutrition result has invalid food details.')
        for key in KEYS:
            _saved_number(item.get(key))
        if item.get('source') is not None:
            source = item['source']
            if not isinstance(source, dict) or not all(isinstance(source.get(k), str) for k in ('source', 'source_version', 'verification')):
                fail('The saved nutrition result has invalid source details.')
            if source.get('carb_definition') is not None and not isinstance(source['carb_definition'], str):
                fail('The saved nutrition result has invalid source details.')
        if not isinstance(item.get('needs_confirmation'), bool):
            fail('The saved nutrition result has invalid food details.')
        for key in ('quantity', 'calculation_grams'):
            _saved_number(item.get(key))
        for key in ('assumptions',):
            if key in item and (not isinstance(item[key], list) or not all(isinstance(x, str) for x in item[key])):
                fail('Food assumptions must be a list of text values.')
        if 'components' in item:
            if not isinstance(item['components'], list) or not all(isinstance(c, dict) and (isinstance(c.get('name'), str) or c.get('name') is None and c.get('needs_confirmation') is True) for c in item['components']):
                fail('Ingredient details must be a list of named foods.')
            for component in item['components']:
                _saved_number(component.get('quantity'))
                ref = component.get('source')
                if ref is not None and not isinstance(ref, dict):
                    fail('The saved nutrition result has invalid source details.')
        portion = item.get('portion_source')
        if portion is not None:
            if not isinstance(portion, dict) or not all(k in portion for k in ('id', 'description', 'calculated_grams', 'source_url')) or not isinstance(portion['description'], str) or not isinstance(portion['source_url'], str):
                fail('The saved nutrition result has invalid portion details.')
            if _saved_number(portion['calculated_grams'], positive=True) is None:
                fail('The saved nutrition result has invalid portion details.')
        cooking = item.get('cooking_source')
        if cooking is not None and (not isinstance(cooking, dict) or not isinstance(cooking.get('method'), str)):
            fail('The saved nutrition result has invalid cooking details.')
    sampling = result.get('uncertainty_analysis')
    if sampling is not None:
        if not isinstance(sampling, dict) or type(sampling.get('samples')) is not int or not isinstance(sampling.get('statistics'), dict) or not isinstance(sampling.get('drivers'), list) or not isinstance(sampling.get('assumptions'), list) or not all(isinstance(x, str) for x in sampling['assumptions']):
            fail('The saved nutrition result has invalid sampling details.')
        if not all(isinstance(x, dict) for x in sampling['drivers']) or not all(v is None or isinstance(v, dict) for v in sampling['statistics'].values()):
            fail('The saved nutrition result has invalid sampling details.')
    bounds = result.get('scenario_range', {})
    if not isinstance(bounds, dict):
        fail('Nutrition scenario ranges are invalid.')
    for values in bounds.values():
        if values is not None and (not isinstance(values, (list, tuple)) or len(values) != 2 or _saved_number(values[0]) is None or _saved_number(values[1]) is None or values[0] > values[1]):
            fail('Nutrition scenario ranges are invalid.')


def _payload(meal):
    result = deepcopy(meal)
    if snapshot(result) is None:
        result.pop('nutrition', None)
    return result


def export_json(meals):
    return json.dumps({'format': 'fitplate-meals', 'version': 1, 'meals': [_payload(m) for m in meals]}, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')


def _cell(value):
    return "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value


def export_csv(meals):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for meal in meals:
        result = snapshot(meal)
        for index, item in enumerate(meal['items']):
            detail = result['items'][index] if result else {}
            source = detail.get('source') or {}
            values = (meal['id'], meal['date'], meal['meal_type'], item['name'], item['quantity'], item['unit'], item['preparation'], meal.get('note', ''),
                      result['nutrition_status'] if result else 'Not calculated', detail.get('food_id'), detail.get('quantity'), detail.get('calculation_grams'),
                      detail.get('energy'), detail.get('protein'), detail.get('carbs'), detail.get('fat'), source.get('source'), source.get('source_version'), source.get('verification'),
                      detail.get('estimate_kind'), '; '.join(detail.get('assumptions', [])), json.dumps(detail.get('components', []), ensure_ascii=False),
                      '1', index, json.dumps(_payload(meal), ensure_ascii=False, allow_nan=False) if index == 0 else '')
            writer.writerow([_cell(v) for v in values])
    return output.getvalue().encode('utf-8-sig')


def _json(text):
    try:
        return json.loads(text, parse_constant=lambda x: fail('Numeric fields must contain finite, non-negative numbers.'))
    except TransferError:
        raise
    except (ValueError, RecursionError):
        fail('The file contains invalid JSON data.')


def _unescape(value):
    return value[1:] if value.startswith("'") and len(value) > 1 and value[1] in '=+-@\t\r' else value


def _legacy(rows):
    first = rows[0]
    meal = dict(id=first['meal_id'], date=first['date'], meal_type=first['meal'], note=first.get('note', ''), input_source='Import', items=[])
    details = []
    for row in rows:
        item = dict(name=row['food'], quantity=_number(row['quantity'], positive=True), unit=row['unit'], preparation=row['preparation'])
        meal['items'].append(item)
        nutrients = {key: _number(row.get(column)) for key, column in zip(KEYS, ('energy_kcal', 'protein_g', 'carbs_g', 'fat_g'))}
        source = None
        if row.get('source'):
            source = dict(source=row['source'], source_version=row.get('source_version') or 'Not recorded', verification=row.get('source_verification') or 'Imported; not independently verified', carb_definition='Definition not recorded')
        components = _json(row.get('ingredient_breakdown_json') or '[]')
        fid = _number(row.get('food_id'))
        if fid is not None and not fid.is_integer():
            fail('Food IDs must be integers.')
        details.append(dict(name=item['name'], input_name=item['name'], input_index=len(details), food_id=int(fid) if fid is not None else None,
                            quantity=_number(row.get('calculated_portion_grams')), calculation_grams=_number(row.get('calculation_grams')), unit='g', preparation=item['preparation'],
                            source=source, match_type='recipe' if components else 'imported', estimate_kind=row.get('estimate_kind') or 'Imported history',
                            assumptions=[row['estimate_assumptions']] if row.get('estimate_assumptions') else [], components=components, **nutrients))
        if fid is not None:
            item['food_id'] = int(fid)
    available = [all(item[key] is not None for key in KEYS) for item in details]
    count = sum(any(item[key] is not None for key in KEYS) for item in details)
    if details:
        totals = {key: round(sum(item[key] for item in details if item[key] is not None), 1) if any(item[key] is not None for item in details) else None for key in KEYS}
        pending = [dict(input_index=i, reason='The imported file has missing nutrient values.') for i, ready in enumerate(available) if not ready]
        for item, ready in zip(details, available):
            item['needs_confirmation'] = not ready
        meal['nutrition'] = dict(items=details, total_count=len(details), computed_count=count, totals=totals,
                                 completeness='complete' if all(available) else 'partial', nutrition_status='Imported history' if all(available) else 'Partial imported history' if count else 'Not calculated',
                                 warnings=['Legacy CSV values are preserved as provided. Original calculation settings and some source details were not included in that export.'],
                                 pending_items=pending, input_fingerprint=fingerprint(meal))
    return meal


def parse_import(data, filename):
    if not data or len(data) > MAX_BYTES:
        fail('Choose a non-empty file no larger than 10 MB.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        fail('The file must use UTF-8 encoding.')
    legacy = False
    if filename.lower().endswith('.json'):
        document = _json(text)
        if not isinstance(document, dict) or document.get('format') != 'fitplate-meals' or document.get('version') != 1 or not isinstance(document.get('meals'), list):
            fail('Choose a FitPlate meal backup with a supported format version.')
        meals = document['meals']
    elif filename.lower().endswith('.csv'):
        csv.field_size_limit(MAX_BYTES)
        try:
            reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
            if not reader.fieldnames or not REQUIRED <= set(reader.fieldnames) or len(reader.fieldnames) != len(set(reader.fieldnames)):
                fail('This CSV is missing required FitPlate meal-detail columns.')
            grouped = {}
            for index, raw in enumerate(reader):
                if index >= MAX_MEALS * 100 or None in raw or any(v is None for v in raw.values()):
                    fail('The CSV contains an incomplete or oversized row.')
                row = {k: _unescape(v) for k, v in raw.items()}
                grouped.setdefault(row['meal_id'], []).append(row)
                if len(grouped) > MAX_MEALS:
                    fail('Import no more than 2,000 meals at a time.')
            meals = []
            for identity, rows in grouped.items():
                for row in rows:
                    if (row['date'], row['meal'], row.get('note', '')) != (rows[0]['date'], rows[0]['meal'], rows[0].get('note', '')):
                        fail('Rows with the same meal ID must have the same date, meal type and note.')
                payloads = [row['meal_payload_json'] for row in rows if row.get('meal_payload_json')]
                if any(row.get('format_version') not in ('', None, '1') for row in rows):
                    fail('Choose a FitPlate meal backup with a supported format version.')
                if payloads:
                    if len(payloads) != 1:
                        fail('Each meal must contain exactly one complete backup payload.')
                    meal = _json(payloads[0])
                    validate_meal(meal)
                    if meal['id'] != identity or len(meal['items']) != len(rows):
                        fail('The CSV rows do not match the complete meal backup.')
                    indices = [_number(row.get('item_index')) for row in rows]
                    if any(v is None or not v.is_integer() for v in indices) or sorted(int(v) for v in indices) != list(range(len(rows))):
                        fail('The CSV food positions are invalid or repeated.')
                    for row, position in zip(rows, indices):
                        item = meal['items'][int(position)]
                        if (row['date'], row['meal'], row.get('note', ''), row['food'], _number(row['quantity'], positive=True), row['unit'], row['preparation']) != (meal['date'], meal['meal_type'], meal.get('note', ''), item['name'], _number(item.get('quantity'), positive=True), item['unit'], item['preparation']):
                            fail('The CSV rows do not match the complete meal backup. Re-export after editing records in FitPlate.')
                        saved = (meal.get('nutrition') or {}).get('items', [{}] * len(rows))[int(position)]
                        for column, key in (('food_id', 'food_id'), ('calculated_portion_grams', 'quantity'), ('calculation_grams', 'calculation_grams'), ('energy_kcal', 'energy'), ('protein_g', 'protein'), ('carbs_g', 'carbs'), ('fat_g', 'fat')):
                            if _number(row.get(column)) != _number(saved.get(key)):
                                fail('The CSV rows do not match the complete meal backup. Re-export after editing records in FitPlate.')
                        source = saved.get('source') or {}
                        for column, expected in (('source', source.get('source')), ('source_version', source.get('source_version')), ('source_verification', source.get('verification')), ('estimate_kind', saved.get('estimate_kind')), ('estimate_assumptions', '; '.join(saved.get('assumptions', [])))):
                            if row.get(column, '') != (expected or ''):
                                fail('The CSV rows do not match the complete meal backup. Re-export after editing records in FitPlate.')
                        if _json(row.get('ingredient_breakdown_json') or '[]') != saved.get('components', []):
                            fail('The CSV rows do not match the complete meal backup. Re-export after editing records in FitPlate.')
                    meals.append(meal)
                else:
                    if any(row.get('format_version') for row in rows):
                        fail('A complete meal backup payload is missing. Use an original export.')
                    legacy = True
                    meals.append(_legacy(rows))
        except csv.Error:
            fail('The CSV file could not be read. Check its quoting and columns.')
    else:
        fail('Choose a FitPlate CSV export or JSON meal backup.')
    if not 1 <= len(meals) <= MAX_MEALS:
        fail('The file must contain between 1 and 2,000 meals.')
    identities = set()
    for meal in meals:
        validate_meal(meal)
        if meal['id'] in identities:
            fail('The backup contains repeated meal IDs.')
        identities.add(meal['id'])
    return {'meals': meals, 'legacy': legacy}


def import_meals(batch):
    from fitplate.storage import connect
    meals = batch['meals']
    prepared = []
    stamp = datetime.now(timezone.utc).isoformat()
    for meal in meals:
        validate_meal(meal)
        payload = deepcopy(meal)
        payload['import_info'] = {'imported_at': stamp, 'format': 'legacy_csv' if batch['legacy'] else 'complete_backup'}
        prepared.append((payload['id'], json.dumps(payload, ensure_ascii=False, allow_nan=False), stamp))
    with connect() as db:
        before = db.total_changes
        db.executemany('INSERT INTO meals (id,payload,created_at) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING', prepared)
        inserted = db.total_changes - before
    return {'imported': inserted, 'skipped': len(prepared) - inserted}
