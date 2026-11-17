"""Retrieve source choices for reviewed estimates, without automatic food selection."""
from functools import lru_cache
import re
import math
from collections import Counter
import gzip
from importlib.metadata import distribution
import numpy as np
from nltk.stem.snowball import SnowballStemmer

from fitplate.nutrition import DEFAULT_DB

DESCRIPTORS = set('seared grilled boiled steamed baked fried cooked raw fresh crispy sliced slice slices segment segments strip strips piece pieces serving servings regular mixed unfamiliar small medium large with and of the'.split())
SYNONYMS = {'aubergine': 'eggplant', 'courgette': 'zucchini', 'prawn': 'shrimp', 'prawns': 'shrimp', 'rocket': 'arugula', 'yoghurt': 'yogurt', 'garbanzo': 'chickpea', 'scallion': 'onion', 'scallions': 'onion','avocados': 'avocado', 'oranges': 'orange', 'tomatoes': 'tomato',
            'potatoes': 'potato', 'wontons': 'wonton', 'noodles': 'noodle'}


def tokens(text):
    return {SYNONYMS.get(t, t[:-1] if t.endswith('s') and len(t) > 4 and not t.endswith(('ss', 'us')) else t)
            for t in re.findall(r'[a-z]+', text.lower())}


def identity_tokens(text):
    return tokens(text) - tokens(' '.join(DESCRIPTORS))


STEMMER = SnowballStemmer('english')


@lru_cache(maxsize=1)
def hybrid_index():
    """Offline BM25 and IDF-weighted recipe GloVe index over the current source table."""
    docs = [Counter(STEMMER.stem(t) for t in tokens(f.source_food_description or f.name)) for f in DEFAULT_DB.foods]
    df = Counter(t for doc in docs for t in doc)
    n = len(docs)
    idf = {t: math.log(1 + (n - count + .5) / (count + .5)) for t, count in df.items()}
    path = distribution('ingredient-parser-nlp').locate_file('ingredient_parser/en/data/ingredient_embeddings.35d.glove.txt.gz')
    vectors = {}
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        count, dimension = map(int, next(handle).split())
        for line in handle:
            parts = line.split()
            vectors[parts[0]] = np.asarray(parts[1:], dtype=np.float32)
    def encode(doc):
        values = [vectors[t] * idf.get(t, 1) for t in doc if t in vectors]
        value = np.sum(values, axis=0) if values else np.zeros(dimension, dtype=np.float32)
        return value / max(float(np.linalg.norm(value)), 1e-9)
    matrix = np.asarray([encode(doc) for doc in docs], dtype=np.float32)
    return docs, idf, matrix, encode, sum(sum(d.values()) for d in docs) / n


def hybrid_scores(name):
    docs, idf, matrix, encode, average = hybrid_index()
    query = {STEMMER.stem(t) for t in tokens(name)}
    lexical = np.asarray([sum(idf.get(t, 0) * d.get(t, 0) * 2.2 / (d.get(t, 0) + 1.2 * (.25 + .75 * sum(d.values()) / average)) for t in query) for d in docs])
    semantic = matrix @ encode(query)
    fused = np.zeros(len(docs))
    for ranking in (np.argsort(-lexical)[:200], np.argsort(-semantic)[:200]):
        for rank, index in enumerate(ranking, 1):
            fused[index] += 1 / (60 + rank)
    return lexical, semantic, fused


@lru_cache(maxsize=256)
def reference_candidates(name, preparation='Not specified', limit=12, dataset=None):
    """Keep identity words while tolerating cuts, plurals and preparation descriptions."""
    identity = identity_tokens(name)
    desired = tokens(name)
    ranked = []
    from fitplate.food_defaults import family_ids
    family = family_ids(name)
    lexical, semantic, fused = hybrid_scores(name)
    for position, food in enumerate(DEFAULT_DB.foods):
        if dataset and food.reference_metadata['source_dataset'] != dataset:
            continue
        description = food.source_food_description or food.name
        words = tokens(description)
        if family and food.food_id in family:
            ranked.append((30 - family.index(food.food_id),food))
        if 'chicken' in desired and not desired & {'liver','heart','gizzard'} and words & {'liver','heart','gizzard'}:
            continue
        if not identity or not identity <= words:
            continue
        if any(extra in words and extra not in desired for extra in ('oil', 'juice', 'powder')):
            continue
        score = 10.0 + .2 * len(desired & words) + float(fused[position]) * 5
        # A fruit/vegetable name does not imply its oil, juice, powder or a branded dish.
        for extra in ('oil', 'juice', 'powder', 'baby', 'sandwich', 'soup', 'salad', 'dressing', 'sweetener', 'peel', 'seed', 'fried'):
            if extra in words and extra not in desired:
                score -= 6
        if preparation == 'Raw':
            score += 2 if 'raw' in words else -1
        elif preparation not in ('Not specified', None):
            score += 2 if food.state == 'cooked' else -1
            score += 1 if tokens(preparation) & words else 0
        if {'all', 'commercial', 'variety'} <= words or 'all' in words:
            score += .3
        if 'fresh' in words:
            score += .2
        score -= .015 * len(words)
        if not dataset and food.reference_metadata['source_dataset'] == 'USDA':
            score += .5
        ranked.append((score, food))
    # Existing aliases still reach references whose publisher uses a different name.
    exact = DEFAULT_DB.named(name)
    if exact and (not dataset or exact.reference_metadata['source_dataset'] == dataset):
        ranked.append((20, exact))
    choices = []
    seen = set()
    for score, food in sorted(ranked, key=lambda pair: (-pair[0], pair[1].food_id)):
        if food.food_id in seen:
            continue
        seen.add(food.food_id)
        choices.append({'food_id': food.food_id, 'name': food.name, 'state': food.state,
                        'score': round(score, 3), 'retrieval': 'BM25 + recipe GloVe + reciprocal-rank fusion; attribute reranking'})
        if len(choices) == limit:
            break
    return choices
