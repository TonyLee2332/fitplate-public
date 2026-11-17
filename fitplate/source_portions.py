"""Source-identified household measures; reference averages, not individual measurements."""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / 'data/source_portions.json').read_text(encoding='utf-8'))
BY_ID = {r['id']: r for r in CATALOG['portions']}
BY_FOOD = {}
for row in BY_ID.values():
    BY_FOOD.setdefault(row['food_id'], []).append(row)


def portions_for(item):
    from fitplate.nutrition import DEFAULT_DB
    fid = item.get('food_id') or item.get('details', {}).get('reference_food_id')
    if fid is None:
        food = DEFAULT_DB.named(item.get('name', ''))
        fid = food.food_id if food else None
    return BY_FOOD.get(fid, [])


def resolve_portion(item):
    details = item.get('details', {})
    pid = details.get('source_portion_id')
    if pid is None or item.get('confirmed_grams') or item.get('unit') == 'g':
        return None
    if type(pid) is not int or pid not in BY_ID:
        raise ValueError('Choose a valid source portion.')
    row = BY_ID[pid]
    if row not in portions_for(item):
        raise ValueError('The source portion belongs to another food. Choose a matching portion.')
    if item.get('quantity') is None or item['quantity'] <= 0:
        raise ValueError('Enter the number of selected source portions.')
    grams = item['quantity'] * row['grams'] / row['amount']
    if grams > 100000:
        raise ValueError('Source portion weight exceeds the input limit.')
    return dict(**row, calculated_grams=grams, source_url=CATALOG['source_url'],
                archive_sha256=CATALOG['archive_sha256'], file_sha256=CATALOG['file_sha256'],
                source_file=CATALOG['source_file'], source_version=CATALOG['version'])
