"""FAO recipe mass-balance calculation over source-state edible ingredient weights."""
import math
from copy import deepcopy
from fitplate.nutrition import DEFAULT_DB

METHOD = 'https://www.fao.org/4/y4705e/y4705e23.htm'
KEYS = ('energy', 'protein', 'carbs', 'fat')


def positive(value, label, maximum=100000):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f'{label} must be a finite positive number within {maximum:g}.')
    return float(value)


def validate_cooking(recipe):
    if not isinstance(recipe, dict) or set(recipe) - {'ingredients', 'finished_weight_g', 'note'}:
        raise ValueError('Invalid cooked-recipe fields.')
    positive(recipe.get('finished_weight_g'), 'Finished batch weight')
    ingredients = recipe.get('ingredients')
    if not isinstance(ingredients, list) or not 1 <= len(ingredients) <= 20:
        raise ValueError('Enter one to twenty weighed ingredients.')
    for row in ingredients:
        if not isinstance(row, dict) or set(row) - {'food_id', 'grams', 'edible_fraction', 'retention', 'retention_source'}:
            raise ValueError('Invalid ingredient fields.')
        fid = row.get('food_id')
        if type(fid) is not int or fid not in DEFAULT_DB.by_id:
            raise ValueError('Select a source-identified ingredient.')
        positive(row.get('grams'), 'Ingredient weight')
        positive(row.get('edible_fraction', 1), 'Edible fraction', 1)
        factors = row.get('retention', {})
        if not isinstance(factors, dict) or set(factors) - set(KEYS):
            raise ValueError('Unsupported retained nutrient.')
        if factors:
            if DEFAULT_DB.by_id[fid].state == 'cooked':
                raise ValueError('Do not apply retention again to a cooked source ingredient.')
            source = row.get('retention_source', '')
            if not isinstance(source, str) or not source.startswith('https://') or len(source) > 500:
                raise ValueError('Retention factors require an HTTPS evidence reference.')
            for value in factors.values():
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Retention factors must be between zero and one.')
    return deepcopy(recipe)


def project_cooking(item):
    if item.get('preparation') == 'Raw':
        raise ValueError('A cooked batch requires its cooked edible portion, not a raw portion.')
    recipe = validate_cooking(item['details']['cooking'])
    portion = item.get('confirmed_grams') or (item.get('quantity') if item.get('unit') == 'g' else None)
    portion = positive(portion, 'Cooked edible portion in grams')
    finished = recipe['finished_weight_g']
    if portion > finished:
        raise ValueError('The eaten portion cannot exceed the finished batch weight.')
    ratio = portion / finished
    rows, input_mass = [], 0
    for ingredient in recipe['ingredients']:
        food = DEFAULT_DB.by_id[ingredient['food_id']]
        grams = ingredient['grams'] * ingredient.get('edible_fraction', 1)
        input_mass += grams
        rows.append(dict(name=food.name, food_id=food.food_id, quantity=grams * ratio, unit='g',
                         preparation='Not specified', estimated=True,
                         recipe_retention=ingredient.get('retention', {}),
                         retention_source=ingredient.get('retention_source')))
    assumptions = [f'FAO recipe calculation: {input_mass:g} g edible input, {finished:g} g finished batch, {portion:g} g eaten; batch yield {finished/input_mass:.3f}.',
                   'Weigh ingredients in the state named by their selected source; include oil and other consumed additions as ingredients.',
                   'Unspecified nutrient retention is left at 1 for accounting only; nutrient losses and discarded fat/liquid are not inferred or empirically validated.']
    if any(row.get('retention') for row in recipe['ingredients']):
        assumptions.append('Supplied nutrient-retention factors are applied once; reference links are recorded but their applicability requires human review.')
    if finished > input_mass:
        assumptions.append('Finished weight exceeds edible ingredient input; verify absorbed/added water and the batch weight.')
    provenance = dict(method=METHOD, recipe=recipe, edible_input_g=input_mass, finished_weight_g=finished,
                      yield_factor=finished/input_mass, eaten_weight_g=portion)
    return rows, assumptions, provenance
