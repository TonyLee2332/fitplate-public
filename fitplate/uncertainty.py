"""Seeded Latin-hypercube portion/oil scenarios and recipe composition screening."""
import hashlib
import json
import numpy as np
from fitplate.nutrition import DEFAULT_DB

VERSION = 'FitPlate uncertainty 1.0'


def input_hash(meal):
    payload = {'items': meal.get('items', []), 'food_version': DEFAULT_DB.version, 'version': VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def sample_meal(meal, samples=256, seed=42):
    from fitplate.meal_estimation import assess_meal, INGREDIENTS
    if type(samples) is not int or not 64 <= samples <= 2048 or type(seed) is not int:
        raise ValueError('Choose 64 to 2048 samples and an integer seed.')
    checked = assess_meal({k:v for k,v in meal.items() if k != 'uncertainty_analysis'})
    if checked['computed_count'] != checked['total_count'] or not checked['computed_count']:
        raise ValueError('Resolve all foods before exploring whole-meal uncertainty.')
    rng = np.random.default_rng(seed)
    outputs = np.zeros((samples, 4))
    variables = []
    def lhs():
        return (rng.permutation(samples) + rng.random(samples)) / samples
    for original, detail in zip(meal['items'], checked['items']):
        d = original.get('details', {})
        parts = detail['components']
        masses = np.array([p.get('quantity') or 0 for p in parts], dtype=float)
        total = masses.sum()
        if total <= 0:
            raise ValueError('Food mass is unavailable.')
        unit = np.array([[p[k] / p['quantity'] if p['quantity'] else 0 for k in ('energy','protein','carbs','fat')] for p in parts])
        weights = np.tile(masses, (samples, 1))
        measured = original.get('confirmed_grams') or original.get('unit') == 'g' and original.get('quantity') is not None
        if not measured:
            factor = .65 + .75 * lhs()
            weights *= factor[:, None]
            variables.append((original['name'] + ': portion', factor))
        if detail['estimate_kind'] == 'Recipe estimate' and not d.get('ingredient_grams') and not d.get('cooking') and len(parts) > 1:
            proportions = rng.dirichlet(np.maximum(masses/total * 100, .1), size=samples)
            weights = proportions * weights.sum(axis=1)[:, None]
            variables.append((original['name'] + ': main ingredient share', proportions[:, int(np.argmax(masses))]))
        oils = [i for i,p in enumerate(parts) if p.get('food_id') == INGREDIENTS['oil']]
        if oils and d.get('oil','Unknown') == 'Unknown' and d.get('oil_grams') is None and not d.get('cooking'):
            oil_index = oils[0]
            factor = .4 + 1.4 * lhs()
            previous = weights[:, oil_index].copy()
            updated = np.minimum(previous * factor, weights.sum(axis=1) * .8)
            rest = weights.sum(axis=1) - previous
            multiplier = np.divide(weights.sum(axis=1)-updated, rest, out=np.ones_like(rest), where=rest>0)
            weights *= multiplier[:, None]; weights[:, oil_index] = updated
            variables.append((original['name'] + ': retained oil', factor))
        outputs += weights @ unit
    statistics = {}
    for n,key in enumerate(('energy','protein','carbs','fat')):
        statistics[key] = None if checked['totals'][key] is None else dict(p05=round(float(np.quantile(outputs[:,n],.05)),2), median=round(float(np.median(outputs[:,n])),2), p95=round(float(np.quantile(outputs[:,n],.95)),2))
    drivers = []
    for name, values in variables:
        correlations = []
        for col in outputs.T:
            correlations.append(float(np.corrcoef(values,col)[0,1]**2) if np.std(values)>1e-10 and np.std(col)>1e-10 else 0)
        drivers.append(dict(variable=name, screening_score=round(max(correlations),4)))
    return dict(version=VERSION, input_hash=input_hash(meal), samples=samples, seed=seed,
                method='Latin-hypercube portion/oil draws; Dirichlet recipe composition draws', statistics=statistics,
                drivers=sorted(drivers,key=lambda r:-r['screening_score']),
                assumptions=['Portion multipliers: uniform 0.65–1.40 for unweighed portions.',
                             'Unknown oil multipliers: uniform 0.4–1.8; recipe shares: Dirichlet concentration 100.',
                             'Distributions are engineering assumptions, not fitted empirical error models.',
                             'Intervals are modelled scenario percentiles, not calibrated confidence intervals. Food identity and hidden ingredients may add unmodelled error.',
                             'Sensitivity scores are squared correlations, not causal effects or additive variance contributions.'])
