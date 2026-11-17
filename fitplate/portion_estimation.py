"""Editable count interpretations; weights are app assumptions, not measured portions."""
import re


def portion_options(item):
    name = item.get('name', '').lower()
    if re.search(r'\bavocado(?:s)?\b', name) and not re.search(r'oil|dressing|sauce', name):
        return {'Whole': 140, 'Slice': 15}
    if re.search(r'\borange(?:s)?\b', name) and not re.search(r'juice|peel|marmalade', name):
        return {'Whole': 130, 'Segment': 10, 'Serving': 100}
    if 'pickled' in name and 'ginger' in name:
        return {'Slice': 2, 'Serving': 10}
    if 'wonton' in name and ('strip' in name or 'crispy' in name):
        return {'Strip': 2, 'Serving': 15}
    return {}


def seed_portion_estimates(meal):
    """Keep counts unchanged and distinguish guessed form/grams from supplied facts."""
    items = meal.get('items', [])
    salad_context = len(items) >= 3 and any('salad' in i.get('name', '').lower() for i in items)
    for item in items:
        from fitplate.food_defaults import apply_family_defaults
        apply_family_defaults(item)
        options = portion_options(item)
        quantity = item.get('quantity')
        if not options or quantity is None or item.get('unit') not in {'piece', 'serving'} or item.get('confirmed_grams') or item.get('details', {}).get('source_portion_id'):
            continue
        details = item.setdefault('details', {})
        explicit = details.get('portion_form')
        form = explicit if explicit in options else details.get('estimated_portion_form')
        if form not in options:
            if 'Segment' in options and 'segment' in item['name'].lower():
                form = 'Segment'
            elif 'Strip' in options:
                form = 'Strip'
            elif 'avocado' in item['name'].lower() and salad_context and quantity > 1:
                form = 'Slice'
            elif 'ginger' in item['name'].lower() and quantity >= 2:
                form = 'Slice'
            else:
                form = 'Whole' if 'Whole' in options else 'Serving'
        # Keep a previously reviewed/editable weight; only seed a new interpretation.
        if details.get('estimated_grams') and details.get('estimated_portion_form') == form:
            continue
        size = {'Small': .7, 'Medium': 1, 'Large': 1.4, 'Unknown': 1}[details.get('portion_size', 'Unknown')]
        unit_grams = options[form] * size
        grams = round(quantity * unit_grams, 3)
        if not 0 < grams <= 3000:
            continue
        details['estimated_portion_form'] = form
        details['estimated_grams'] = grams
        known = explicit in options
        details['estimate_basis'] = (f"{quantity:g} recorded {item['unit']}(s) interpreted as {form.lower()}(s)"
            f" ({'selected form' if known else 'unconfirmed assumption'}); {unit_grams:g} g each, {grams:g} g total. "
            "FitPlate portion assumption, not a measured weight; adjust if needed.")
