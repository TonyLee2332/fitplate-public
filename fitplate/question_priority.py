"""Counterfactual nutrition-impact ordering; heuristic priorities, not learned probabilities."""
from copy import deepcopy
from fitplate.portion_estimation import portion_options


def rank_questions(meal, questions):
    from fitplate.meal_estimation import assess_meal
    candidates = []
    for index, item in enumerate(meal.get('items', [])):
        d = item.get('details', {})
        if d.get('use_defaults'):
            continue
        options = portion_options(item)
        unit_question = None
        if (len(options) > 1 and item.get('unit') in {'piece', 'serving'} and item.get('quantity')
                and not item.get('confirmed_grams') and not d.get('source_portion_id')
                and d.get('portion_form', 'Unknown') == 'Unknown'):
            unit_question = f"For {item['name']}, do you mean {' or '.join(k.lower() for k in options)}? The preview uses an unconfirmed portion interpretation."
        own = [q for q in questions if item['name'] in q or q.startswith('Was the milk') and item['name'].lower() == 'milk']
        if d.get('source_portion_id') or item.get('confirmed_grams'):
            own = [q for q in own if 'weight or portion size' not in q]
        if unit_question:
            own = [q for q in own if 'weight or portion size' not in q]
            own.insert(0, unit_question)
        for question in own:
            variants = []
            if question == unit_question:
                for value in options.values():
                    v = deepcopy(item)
                    v['confirmed_grams'] = value * item['quantity']
                    variants.append(v)
            elif 'oil' in question.lower() and 'drain' not in question.lower():
                for oil in ('None', 'Generous'):
                    v = deepcopy(item); v.setdefault('details', {})['oil'] = oil
                    v['details'].pop('oil_grams', None); variants.append(v)
            elif 'lean' in question:
                for fat in ('Lean', 'Fatty'):
                    v = deepcopy(item); v.setdefault('details', {})['meat_fat'] = fat; variants.append(v)
            elif 'drain' in question.lower():
                for drainage in ('Drained', 'With liquid'):
                    v = deepcopy(item); v.setdefault('details', {})['drained'] = drainage; variants.append(v)
            elif 'broth' in question.lower():
                for broth in ('None', 'All'):
                    v = deepcopy(item); v.setdefault('details', {})['broth_consumed'] = broth; variants.append(v)
            elif 'weight or portion size' in question:
                point = assess_meal({'items': [item]})['items'][0].get('quantity') or 200
                for factor in (.5, 1.5):
                    v = deepcopy(item); v['confirmed_grams'] = point * factor; variants.append(v)
            elif 'raw or cooked' in question:
                for prep in ('Raw', 'Cooked'):
                    v = deepcopy(item); v['preparation'] = prep; variants.append(v)
            values = [assess_meal({'items': [v]})['totals'] for v in variants]
            spreads = {}
            for key in ('energy', 'protein', 'carbs', 'fat'):
                numbers = [v[key] for v in values if v.get(key) is not None]
                spreads[key] = max(numbers) - min(numbers) if len(numbers) >= 2 else None
            # Macronutrient impact matters even if the total energy barely changes.
            score = max([spreads.get('energy') or 0, 4 * (spreads.get('protein') or 0),
                         4 * (spreads.get('carbs') or 0), 9 * (spreads.get('fat') or 0)])
            unresolved = not variants or any(s is None for s in spreads.values())
            if unresolved:
                score = max(score, 200 if 'raw or cooked' in question or 'ingredients' in question else 100)
            candidates.append(dict(question=question, input_index=index, impact_score=round(score, 2),
                                   nutrient_spread=spreads, method='counterfactual scenario spread' if not unresolved else 'uncertainty fallback priority'))
    unique = {row['question']: row for row in candidates}
    return sorted(unique.values(), key=lambda row: (-row['impact_score'], row['input_index'], row['question']))
