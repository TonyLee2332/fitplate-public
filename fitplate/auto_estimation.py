"""On-demand local estimation over traceable references; never writes user records."""
from copy import deepcopy
from functools import lru_cache
import re


def words(text):
    result=set(re.findall('[a-z]+',text.lower()))
    return {w[:-3]+'y' if w.endswith('ies') else w[:-2] if w.endswith('oes') else w[:-1] if w.endswith('s') and len(w)>3 and not w.endswith(('ss','us')) else w for w in result}


@lru_cache(maxsize=1)
def index():
    from fitplate.nutrition import DEFAULT_DB
    return [(f,words(f.source_food_description or f.name)) for f in DEFAULT_DB.foods]


@lru_cache(maxsize=512)
def select_reference(name,preparation):
    from fitplate.nutrition import DEFAULT_DB
    translated={'苹果':'apple','蘋果':'apple','香蕉':'banana','燕麦':'oats','燕麥':'oats','番茄':'tomato','西红柿':'tomato','西紅柿':'tomato','牛奶':'milk','鲜奶':'milk','鮮奶':'milk','三文鱼':'salmon','三文魚':'salmon','鸡蛋':'egg','雞蛋':'egg','白蘑菇':'mushrooms','蘑菇':'mushrooms'}
    if name.strip() in translated:return select_reference(translated[name.strip()],preparation)
    tokens=words(name)
    if tokens & {'with','and'}:return None,None
    if tokens=={'milk'} or name in ('牛奶','鮮奶','鲜奶'):
        return 1171265,'Generic whole cow milk assumed; species, brand and fat level were not provided.'
    # Curated identities prevent fresh food from being replaced by a dessert or mix.
    if (tokens & {'blueberry'} or name in ('蓝莓','藍莓')) and not tokens & {'muffin','pie','cake','yogurt','jam','juice','mix','dried'}:return 1171711,'Generic fresh blueberries.'
    if (('bread' in tokens and {'whole','wheat'}<=tokens) or name in ('全麦面包','全麥麵包','全麦吐司','全麥吐司')) and not tokens & {'butter','jam','cheese','sandwich','pudding'}:return 1172689 if 'toast' in tokens else 1172688,'Generic whole-wheat bread; brand and slice size may differ.'
    if ('protein' in tokens and tokens & {'powder','shake'}) or re.search('蛋白粉|蛋白奶昔',name):return 1174181,'Generic high-protein powder; brand and formulation are unknown. Water contributes no nutrients; milk or other additions must be recorded separately.'
    if ('egg' in tokens and 'scrambled' in tokens) or re.search('炒蛋|炒鸡蛋|炒雞蛋',name):return 1172187,'Generic cooked scrambled egg source; its preparation fat is already included, so no extra oil is counted.'
    if tokens & {'mushroom'} and not tokens & {'shiitake','oyster','portabella','soup','sauce','chicken','pork','beef','pizza','pasta','noodle','rice','bread','omelet'}:
        return (1169251 if preparation=='Raw' else 1169252),'White button mushrooms assumed; cooking state follows the selected reference.'
    ignored=words('fresh raw cooked grilled boiled steamed baked fried stir seared chopped sliced slice serving portion regular unknown unspecified with and of the small medium large')
    identity=tokens-ignored
    if not identity:return None,None
    forbidden=words('cake muffin pie candy cookie biscuit dessert yogurt ice cream sandwich soup sauce dressing juice powder oil sweetener supplement baby babyfood bread butter flour mix filling leaf leaves stem stems peel seed seeds puree paste concentrate dehydrated dried canned pickled smoked product products')-tokens
    if preparation!='Fried' and 'fried' not in tokens:forbidden.add('fried')
    choices=[]
    for food,terms in index():
        if not identity<=terms or terms & forbidden:continue
        if 'skin' in terms and 'flesh' not in terms and 'skin' not in tokens and re.search(r',\s*skin\s*(?:\[|$)',food.name,re.I):continue
        if preparation=='Raw' and food.state=='cooked':continue
        if preparation not in ('Raw','Not specified',None) and food.state=='raw':continue
        score=20-len(terms)*.12+(.8 if food.reference_metadata.get('source_dataset')=='USDA' else 0)
        if 'raw' in terms and preparation in ('Raw','Not specified',None):score+=1
        if preparation not in (None,'Not specified') and words(preparation) & terms:score+=2
        if {'year','round','average'}<=terms:score+=2
        choices.append((score,-food.food_id,food.food_id))
    if not choices:return None,None
    exact_head=[c for c in choices if words((DEFAULT_DB.by_id[c[2]].source_food_description or DEFAULT_DB.by_id[c[2]].name).split(',')[0])==identity]
    if exact_head:choices=exact_head
    usda=[c for c in choices if DEFAULT_DB.by_id[c[2]].reference_metadata.get('source_dataset')=='USDA']
    return max(usda or choices)[2],'Closest compatible whole-food source; variety, brand and recipe may differ.'


def choose_measure(food_id,name,unit,size='Unknown'):
    from fitplate.source_portions import BY_FOOD
    measures=BY_FOOD.get(food_id,[])
    tokens=words(name)
    if size in ('Small','Medium','Large') and unit=='piece':
        exact=[m for m in measures if m['description'].lower()==size.lower()]
        if exact:return exact[0]
    preferred=['serving','scoop','tbsp'] if 'powder' in tokens or 'protein' in tokens else ['slice'] if 'bread' in tokens else ['berries','berry'] if 'blueberry' in tokens else ['mushroom','medium'] if 'mushroom' in tokens else ['medium','piece','whole','fruit','fillet','steak','breast','large','small'] if unit=='piece' else ['serving','portion','cup']
    for term in preferred:
        found=[m for m in measures if term in m['description'].lower() and not any(x in m['description'].lower() for x in ('oz','lb','diameter'))]
        if found:return found[0]
    return None


def estimate_item(original,reviewed=False):
    from fitplate.nutrition import DEFAULT_DB,parse_count
    from fitplate.domain import UNITS,PREPARATIONS
    from fitplate.meal_estimation import recipe_for
    item=deepcopy(original)
    if item.get('unit','g') not in UNITS or item.get('preparation','Not specified') not in PREPARATIONS:return item,[]
    if item.get('details') is not None and not isinstance(item['details'],dict):return item,[]
    item['details']=dict(item.get('details') or {})
    details=item['details']
    if item.get('quantity') is not None:
        quantity,valid=parse_count(item['quantity'])
        if not valid:return item,[]
        item['quantity']=quantity
    if not isinstance(item.get('name'),str) or not item['name'].strip():return item,[]
    if details.get('cooking') or details.get('ai_components'):return item,[]
    assumptions=[]
    explicit=item.get('food_id') or details.get('reference_food_id')
    if explicit in DEFAULT_DB.by_id:fid=explicit
    else:
        # Existing dish recipes remain the preferred composition method.
        if recipe_for(item):return item,[]
        composite=estimate_composition(item)
        if composite is not None:return composite
        fid,basis=select_reference(item['name'],item.get('preparation','Not specified'))
        if fid not in DEFAULT_DB.by_id:return item,[]
        details['reference_food_id']=fid
        assumptions.append('Automatic source estimate: '+basis)
    food=DEFAULT_DB.by_id[fid]
    quantity=item.get('quantity');unit=item.get('unit','g')
    if item.get('confirmed_grams') or quantity is not None and unit=='g':
        pass
    elif details.get('source_portion_id'):
        pass
    elif reviewed and details.get('estimated_grams'):
        assumptions.append('Previously reviewed portion estimate retained.')
    else:
        size=details.get('portion_size','Unknown')
        measure=choose_measure(fid,item['name'],unit,size)
        if measure and unit!='ml':
            count=quantity if quantity is not None else 1
            grams=count*measure['grams']/measure['amount']
            factor=1 if size=='Unknown' or size.lower() in measure['description'].lower() else {'Small':.7,'Medium':1,'Large':1.4}.get(size,1)
            grams*=factor
            if quantity is not None and factor==1:
                details['source_portion_id']=measure['id']
            if 0<grams<=3000:details['estimated_grams']=round(grams,3)
            assumptions.append(f"Automatic source portion: {count:g} × {measure['description']} = {grams:g} g. This is a reference average, not a measured portion.")
            if factor!=1:assumptions.append(f'Size factor {factor:g} is an editable assumption applied to the source reference, not a publisher-measured size.')
        elif details.get('estimated_grams'):
            assumptions.append('Existing editable weight proposal retained; no compatible source measure was found.')
        else:
            count=quantity if quantity is not None else 1
            if unit=='ml':
                if 'powder' in words(food.name):
                    serving=choose_measure(fid,item['name'],'serving')
                    grams=(serving['grams']/serving['amount'] if serving else 20)*count/250
                    assumptions.append('Prepared protein drink approximated as one reference powder serving per 250 ml water; concentration and additions are unknown.')
                else:
                    grams=count*(food.density or 1)
                    assumptions.append('Liquid weight uses publisher density where available; otherwise 1 g/ml is an editable approximation.')
            else:
                grams=count*(30 if unit=='piece' else 100)
                assumptions.append('No compatible household measure: assume 30 g per piece or 100 g per serving; this editable fallback is not a measured standard.')
            if 0<grams<=3000:details['estimated_grams']=round(grams,3)
        details['estimate_basis']=' '.join(assumptions)[-240:] or details.get('estimate_basis','Automatic editable portion estimate.')
    if assumptions:
        details['reference_basis']=' '.join(assumptions)[:240]
    return item,assumptions


def estimate_composition(item):
    """Bounded ingredient-equivalent fallback for identifiable mixed dishes."""
    from fitplate.meal_estimation import INGREDIENTS
    if item.get('preparation')=='Raw':return None
    aliases={'chicken':('chicken','鸡肉','雞肉','鸡胸','雞胸'),'beef':('beef','牛肉'),'pork':('pork','猪肉','豬肉'),
             'shrimp':('shrimp','prawn','虾仁','蝦仁'),'rice':('rice','米饭','米飯'),'tofu':('tofu','豆腐'),
             'egg':('egg','鸡蛋','雞蛋'),'mushroom':('mushroom','蘑菇'),'spinach':('spinach','菠菜'),
             'broccoli':('broccoli','西兰花','西蘭花'),'potato':('potato','土豆','马铃薯','馬鈴薯')}
    name=item['name'].lower();tokens=words(name)
    known=[key for key,terms in aliases.items() if key in INGREDIENTS and any((t in tokens if t.isascii() else t in name) for t in terms)]
    if len(known)<2:return None
    portions={k:(.45 if k in ('rice','potato') else .35 if k in ('chicken','beef','pork','shrimp','tofu','egg') else .2) for k in known}
    if item.get('preparation')=='Fried':portions['oil']=.04
    total=sum(portions.values());result=deepcopy(item)
    d=result.setdefault('details',{})
    d['ai_components']=[dict(food_id=INGREDIENTS[k],fraction=v/total) for k,v in portions.items()]
    note='Automatic ingredient-equivalent scenario; proportions are editable assumptions, not the actual recipe. Sources identify nutrient values, not measured dish composition.'
    d['reference_basis']=note
    if not item.get('confirmed_grams') and not (item.get('unit')=='g' and item.get('quantity') is not None) and not d.get('estimated_grams'):
        d['estimated_grams']=min(3000,(item.get('quantity') or 1)*250)
        d['estimate_basis']='Assume 250 g per mixed-dish serving; editable portion assumption.'
    return result,[note]


def prepare_auto_estimates(meal,indices=None):
    """Resolve eligible items locally. Unknown identities stay unresolved, never zero."""
    result=deepcopy(meal);provenance={}
    allowed=set(range(len(result.get('items',[])))) if indices is None else set(indices)
    for i,item in enumerate(result.get('items',[])):
        if i not in allowed:continue
        updated,assumptions=estimate_item(item,bool(meal.get('estimate_reviewed')))
        result['items'][i]=updated
        if updated!=item:provenance[i]=assumptions or ['Automatic compatible source portion estimate.']
    return result,provenance
