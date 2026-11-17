"""Reviewed food-family proxies; actual source values with explicit portion assumptions."""
import re
from fitplate.nutrition import DEFAULT_DB
from fitplate.source_portions import BY_FOOD


def family_ids(name):
    text=name.lower()
    if re.search(r'fried chicken',text) and not re.search(r'liver|heart|gizzard|skin only|meatless',text):
        if 'wing' in text:return [1170360]
        if 'breast' in text:return [1170756]
        if 'drumstick' in text:return [1170757]
        return [1170359,1170360,1170756,1170757]
    if 'chicken' in text and re.search(r'burger|sandwich',text):return [1170318,1170368]
    if re.search(r'ice[ -]?cream',text):return [1167575,1167573]
    if re.search(r'milk[ -]?shake',text):return [1170883 if 'chocolate' in text else 1170884]
    return []


def apply_family_defaults(item):
    d=item.setdefault('details',{})
    if item.get('food_id') or any(d.get(k) for k in ('ai_components','cooking')):
        return
    ids=family_ids(item.get('name',''))
    if not ids:return
    existing=d.get('reference_food_id')
    if existing and (existing not in ids or d.get('estimated_grams')):
        return
    fid=existing or ids[0];food=DEFAULT_DB.by_id[fid]
    options=BY_FOOD.get(fid,[])
    if not options:return
    name=item['name'].lower()
    portion=next((r for r in options if 'container' in r['description']),options[0])
    d['reference_food_id']=fid
    d['reference_basis']='Food-family approximation; brand, recipe, cut and flavour are not confirmed. '+food.source_food_description[:120]
    if 'chicken' in name and 'fried' in name and not re.search(r'wing|breast|drumstick|thigh',name):
        d['reference_basis']='Assume fried thigh meat, skin and breading; cut and edible weight are uncertain. Bones are excluded from nutrient weight.'
    if 'barbecue' in name:
        d['reference_basis']='Complete crispy chicken sandwich reference includes bun, chicken, lettuce and mayonnaise; barbecue sauce/vegetables differ. This is a whole-sandwich proxy, not an exact recipe.'
    q=item.get('quantity');unit=item.get('unit')
    if item.get('confirmed_grams') or q is not None and unit=='g':return
    basis=d.get('estimate_basis','')
    if q is not None and unit=='ml':
        if q<=5 and re.search(r'\b[3-9]\d\d\s*(?:g|ml)\b',basis,re.I):
            grams=portion['grams']/portion['amount']
            note=f'Recorded {q:g} ml conflicts with the earlier drink-sized estimate. Preview assumes one {portion["description"]} ({grams:g} g); confirm drink size before saving.'
        else:
            grams=q*1.05
            note=f'{q:g} ml approximated at 1.05 g/ml; milkshake density is an editable assumption, not measured.'
    else:
        count=q if q is not None else 1
        grams=count*portion['grams']/portion['amount']
        note=f'Assume {count:g} source measure(s): {portion["description"]}, USDA portion {portion["id"]}; {grams:g} g total edible weight. Confirm size/cut; this is a reference average.'
    if not d.get('estimated_grams') and 0<grams<=3000:
        d.update(estimated_grams=grams,estimate_basis=note)
