"""Validated coaching profiles and read-only tools chosen by the conversation agent."""
from copy import deepcopy
from datetime import timedelta
import math

from fitplate.domain import today
from fitplate.nutrition.service import daily_summary

GOALS=('Not set','Build muscle','Lose fat','Maintain weight','Improve fitness')
EXPERIENCE=('Not set','Beginner','Intermediate','Experienced')
TRAINING=('Not set','Strength training','Cardio','Mixed training','Other activity')
ACTIVITY=('Not set','Mostly sitting','Lightly active','Active','Very active')
SEX=('Not provided','Female','Male')
HEALTH=('Not shared','None reported','Professional guidance needed')
DEFAULT_PROFILE=dict(age=None,height_cm=None,weight_kg=None,goal='Not set',training_days=None,
                     experience='Not set',training_type='Not set',activity='Not set',
                     sex='Not provided',health='Not shared',share_with_ai=False)
SOURCES={
    'protein':{'title':'ISSN: protein and exercise (2017)','url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC5477153/'},
    'energy':{'title':'Mifflin et al.: resting energy expenditure (1990)','url':'https://pubmed.ncbi.nlm.nih.gov/2305711/'},
    'training':{'title':'CDC: Adult Activity Overview','url':'https://www.cdc.gov/physical-activity-basics/guidelines/adults.html'},
    'scope':{'title':'NIDDK: Body Weight Planner scope','url':'https://www.niddk.nih.gov/bwp'},
}
TOOL_LABELS={'get_coaching_profile':'Body & training profile','summarize_intake':'Saved intake summary',
             'estimate_needs':'Nutrition reference estimates','reference_guidance':'Nutrition & training references',
             'search_foods':'Food reference search','weekly_summary':'Weekly nutrition summary'}
TOOL_SCHEMAS=[
    {'name':'weekly_summary','arguments':{'mode':'calendar_week or rolling_7','anchor_date':'YYYY-MM-DD, not in the future'},'purpose':'Read weekly saved-record trends, calculation coverage, nutrient-specific available-day averages and current targets. Unknown or partially logged days are not full-day intake. No write actions.'},
    {'name':'get_coaching_profile','arguments':{},'purpose':'Read the saved body/training profile only if sharing was enabled; otherwise return missing fields and local-only status.'},
    {'name':'summarize_intake','arguments':{'days':'integer 1 to 7'},'purpose':'Read nutrition snapshots and targets. Incomplete logs are not full-day intake; never diagnose a deficiency.'},
    {'name':'estimate_needs','arguments':{},'purpose':'Calculate reference protein range and optional maintenance-energy scenario from a complete shared adult profile. Does not set targets.'},
    {'name':'reference_guidance','arguments':{'topic':'nutrition or training'},'purpose':'Retrieve curated evidence and its applicability for practical nutrition/training suggestions.'},
    {'name':'search_foods','arguments':{'query':'English food name, 1 to 100 characters'},'purpose':'Retrieve up to 5 source food entries with nutrients per 100 g, not assumed portions. Check allergies in conversation.'},
]


def function_tools():
    properties={
        'weekly_summary':{'mode':{'type':'string','enum':['calendar_week','rolling_7']},'anchor_date':{'type':'string','description':'Review date YYYY-MM-DD, no later than today'}},
        'summarize_intake':{'days':{'type':'integer','minimum':1,'maximum':7}},
        'reference_guidance':{'topic':{'type':'string','enum':['nutrition','training']}},
        'search_foods':{'query':{'type':'string','minLength':1,'maxLength':100}},
    }
    return [dict(type='function',function=dict(name=t['name'],description=t['purpose'],parameters=dict(
                type='object',properties=properties.get(t['name'],{}),required=list(properties.get(t['name'],{})),additionalProperties=False))) for t in TOOL_SCHEMAS]


def validate_profile(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT_PROFILE):raise ValueError('Invalid body and training profile.')
    result={**DEFAULT_PROFILE,**value}
    for key,low,high,integer in [('age',18,100,True),('height_cm',80,250,False),('weight_kg',25,350,False),('training_days',0,7,True)]:
        number=result[key]
        if number is None:continue
        if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not low<=number<=high or integer and number!=int(number):
            raise ValueError('Check age, height, weight and training frequency; use the displayed units and ranges.')
        result[key]=int(number) if integer else float(number)
    for key,choices in [('goal',GOALS),('experience',EXPERIENCE),('training_type',TRAINING),('activity',ACTIVITY),('sex',SEX),('health',HEALTH)]:
        if result[key] not in choices:raise ValueError('Choose a valid body and training option.')
    if type(result['share_with_ai']) is not bool:raise ValueError('Choose whether to share this profile with AI.')
    return result


def missing_fields(profile):
    fields=('age','height_cm','weight_kg','goal','training_days','experience','training_type','activity','health')
    return [key for key in fields if profile.get(key) in (None,'Not set','Not shared')]


def profile_context(body):
    body=validate_profile(body or {})
    if not body['share_with_ai']:
        return dict(sharing_enabled=False,status='Profile is local only. Ask the user to enable sharing in Body & training profile if they want personalized coaching. Never infer stored body measurements.')
    return dict(sharing_enabled=True,profile={k:v for k,v in body.items() if k!='share_with_ai'},missing_fields=missing_fields(body))


def estimate_needs(body):
    body=validate_profile(body or {})
    if not body['share_with_ai']:return dict(status='not_shared',message='Body profile sharing is off. General guidance only.')
    missing=missing_fields(body)
    if missing:return dict(status='needs_information',missing_fields=missing)
    bmi=body['weight_kg']/(body['height_cm']/100)**2
    if body['health']!='None reported' or bmi<18.5 or bmi>=40:
        return dict(status='professional_review',message='Do not generate calorie or protein targets from this profile. Offer general balanced-eating guidance and suggest qualified individual review; no fat-loss prescription.',sources=[SOURCES['scope']])
    result=dict(status='reference_only',goal=body['goal'],protein_g_per_day=None,resting_energy_kcal=None,
                maintenance_energy_kcal=None,sources=[],assumptions=[
                    'Adult, no relevant health, pregnancy/breastfeeding, eating-disorder or injury restrictions reported. This is not a clinical clearance.',
                    'These are starting reference estimates, not measured needs, a prescribed diet, or saved targets. Review progress and individual tolerance.'])
    if body['training_days']>0:
        result['protein_g_per_day']=[round(body['weight_kg']*1.4),round(body['weight_kg']*2.0)]
        result['sources'].append(SOURCES['protein'])
    if body['sex']!='Not provided':
        resting=10*body['weight_kg']+6.25*body['height_cm']-5*body['age']+(5 if body['sex']=='Male' else -161)
        factor={'Mostly sitting':1.2,'Lightly active':1.4,'Active':1.6,'Very active':1.8}[body['activity']]
        result.update(resting_energy_kcal=round(resting),maintenance_energy_kcal=round(resting*factor))
        result['assumptions'].append(f'Mifflin-St Jeor resting estimate multiplied by {factor}; this activity multiplier is a FitPlate scenario assumption, not a measured value or an output of the cited equation. Activity should include usual training; do not add exercise calories again.')
        result['sources'].append(SOURCES['energy'])
    else:result['assumptions'].append('Sex for the energy equation was not provided. Do not infer it or invent a calorie estimate; protein references remain available.')
    result['assumptions'].append('Do not prescribe an energy deficit from this estimate. For fat loss discuss gradual habits and an individually reviewed plan, especially with health concerns.')
    return result


def intake_context(meals,settings,days):
    if type(days) is not int or not 1<=days<=7:raise ValueError('Use 1 to 7 days for the intake summary.')
    records=[]
    for offset in range(days):
        day=(today()-timedelta(days=offset)).isoformat()
        summary=daily_summary(meals or [],day)
        foods=[i['name'] for meal in meals or [] if meal.get('date')==day for i in meal.get('items',[])][:30]
        records.append(dict(date=day,**summary,foods=foods))
    return dict(days=records,targets={key:(settings or {}).get(key) for key in ('energy','protein','carbs','fat')},
                interpretation='Only saved snapshots are counted. A day with no records is unknown, not zero intake. Even complete saved meals do not prove the entire day was logged. Compare against user-set targets provisionally; do not infer nutritional deficiency or adherence from missing logs.')


def execute_tool(name,arguments,body,meals,settings):
    if name not in TOOL_LABELS or not isinstance(arguments,dict):raise ValueError('Choose an available read-only tool.')
    expected={'get_coaching_profile':set(),'estimate_needs':set(),'summarize_intake':{'days'},'reference_guidance':{'topic'},'search_foods':{'query'},'weekly_summary':{'mode','anchor_date'}}[name]
    if set(arguments)!=expected:raise ValueError('Use exactly the declared tool arguments.')
    if name=='weekly_summary':
        from fitplate.weekly import weekly_summary
        return weekly_summary(meals or [],settings,**arguments)
    if name=='get_coaching_profile':return profile_context(body)
    if name=='estimate_needs':return estimate_needs(body)
    if name=='summarize_intake':return intake_context(meals,settings,arguments['days'])
    if name=='reference_guidance':
        topic=arguments['topic']
        if topic not in ('nutrition','training'):raise ValueError('Choose nutrition or training guidance.')
        if topic=='nutrition':return dict(source=SOURCES['protein'],guidance='For healthy exercising adults, 1.4–2.0 g protein/kg/day is a general reference, not universal advice. Favor food variety and balanced meals. Do not apply this range to minors, pregnancy/breastfeeding, relevant medical conditions or unreviewed profiles. Use estimate_needs for any personalized numbers.')
        return dict(source=SOURCES['training'],guidance='For general adult health, build gradually toward 150 min moderate aerobic activity per week (or 75 vigorous) plus muscle-strengthening on at least 2 days. Some activity is better than none. This is not a hypertrophy-specific plan or a starting dose for everyone. Adapt suggestions to experience, available days, recovery and limitations. Do not advise training through pain, maximal lifts, rehabilitation or treatment.')
    query=arguments['query']
    if not isinstance(query,str) or not query.strip() or len(query)>100:raise ValueError('Use a short food search query.')
    from fitplate.reference_search import reference_candidates
    from fitplate.nutrition import DEFAULT_DB
    rows=[]
    for hit in reference_candidates(query.strip(),limit=5):
        food=DEFAULT_DB.by_id[hit['food_id']]
        rows.append(dict(food_id=food.food_id,name=food.name,basis='per 100 g edible food',energy_kcal=food.kcal,
                         protein_g=food.protein,carbs_g=food.carb,fat_g=food.fat,source=food.source,source_url=food.source_ref))
    return dict(foods=rows,interpretation='Candidate foods, not confirmed user intake. Match cooking state and ingredients. Do not promise allergen absence from a nutrient record.')
