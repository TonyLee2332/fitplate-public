"""Read-only weekly summaries of saved nutrition snapshots; unknown days stay unknown."""
from datetime import date,timedelta
import math
from fitplate.domain import today
from fitplate.nutrition.service import daily_summary,snapshot

NUTRIENTS=('energy','protein','carbs','fat')


def weekly_summary(meals,settings=None,mode='calendar_week',anchor_date=None):
    anchor=date.fromisoformat(anchor_date) if anchor_date else today()
    if anchor>today():raise ValueError('Choose a review date no later than today.')
    if mode=='calendar_week':
        start=anchor-timedelta(days=anchor.weekday());end=min(start+timedelta(days=6),today())
    elif mode=='rolling_7':start,end=anchor-timedelta(days=6),anchor
    else:raise ValueError('Choose calendar week or last seven days.')
    rows=[];definitions=set();food_count=0
    for offset in range((end-start).days+1):
        day=(start+timedelta(days=offset)).isoformat()
        selected=[m for m in meals if m.get('date')==day]
        summary=daily_summary(selected,day)
        count=sum(len(m.get('items',[])) for m in selected);food_count+=count
        definitions.update(summary.get('carb_definitions',[]))
        status='No records' if not selected else 'Not calculated' if not summary['computed_items'] else 'Partial calculation' if summary['incomplete_meals'] else 'Recorded meals calculated'
        rows.append(dict(date=day,status=status,meal_count=len(selected),food_count=count,
                         calculated_foods=summary['computed_items'],incomplete_meals=summary['incomplete_meals'],
                         estimated_meals=summary.get('estimated_meals',0),**summary['totals']))
    comparable=len(definitions)<=1
    targets={k:(settings or {}).get(k) for k in NUTRIENTS}
    for key,value in targets.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:targets[key]=None
    averages={};known_days={};subtotals={}
    for key in NUTRIENTS:
        values=[r[key] for r in rows if r[key] is not None] if key!='carbs' or comparable else []
        known_days[key]=len(values)
        subtotals[key]=round(sum(values),1) if values else None
        averages[key]=round(sum(values)/len(values),1) if values else None
    return dict(start=start.isoformat(),end=end.isoformat(),mode=mode,days=rows,period_days=len(rows),
                logged_days=sum(r['meal_count']>0 for r in rows),saved_meals=sum(r['meal_count'] for r in rows),
                recorded_foods=food_count,calculated_foods=sum(r['calculated_foods'] for r in rows),
                days_with_incomplete_meals=sum(r['incomplete_meals']>0 for r in rows),
                calculated_days=known_days,recorded_subtotals=subtotals,mean_recorded_subtotals=averages,
                current_targets=targets,carbohydrates_comparable=comparable,
                interpretation='Saved records only. Unknown/no-record days are null, never zero. Means use only days with an available calculated subtotal, with a separate denominator per nutrient. Partial meal calculations remain partial. Even fully calculated saved meals do not prove a complete day. Comparisons use CURRENT targets, not historical targets. Do not call these averages actual daily intake, diagnose deficiency, or label adherence. Different carbohydrate definitions suppress weekly carbohydrate aggregation. No diet, record, or target is changed.')
