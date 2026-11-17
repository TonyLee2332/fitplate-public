"""Session-only multi-meal workspace and transparent draft nutrition previews."""
from copy import deepcopy
import json
from fitplate.meal_estimation import assess_meal


def combine_drafts(current,pending,incoming):
    result=[];seen=set()
    for draft in ([current] if current else [])+list(pending or [])+list(incoming or []):
        signature=json.dumps({k:draft.get(k) for k in ('date','meal_type','items','note')},sort_keys=True)
        if signature not in seen:result.append(deepcopy(draft));seen.add(signature)
    return result


def analyze_drafts(drafts):
    rows=[];definitions=set()
    for draft in drafts:
        result=assess_meal(draft)
        definitions.update((i.get('source') or {}).get('carb_definition','Unknown') for i in result['items'] if not i.get('needs_confirmation'))
        rows.append(dict(id=draft['id'],date=draft['date'],meal_type=draft['meal_type'],
                         totals=result['totals'],calculated_foods=result['computed_count'],foods=result['total_count'],
                         complete=result['completeness']=='complete',pending=result['pending_items'],
                         estimate=result.get('requires_estimate_review',False),warnings=result['warnings']))
    all_complete=bool(rows) and all(r['complete'] for r in rows)
    totals={k:round(sum(r['totals'][k] for r in rows),1) if all_complete and all(r['totals'][k] is not None for r in rows) else None for k in ('energy','protein','carbs','fat')}
    if len(definitions)>1:totals['carbs']=None
    if len({r['date'] for r in rows})>1:totals=dict.fromkeys(totals)
    return dict(meals=rows,complete=all_complete,combined_totals=totals,
                interpretation='Pending drafts only, not saved intake or proof of a complete day. Unknown foods/portions are not zero. Do not invent a full total when combined_totals is null. Different source carbohydrate definitions may be incompatible; compare carbohydrate totals only within one definition. Ask about the largest unresolved portions before making a numeric conclusion.')


def review_goals(settings):
    targets={k:(settings or {}).get(k) for k in ('energy','protein','carbs','fat')}
    ready=all(isinstance(targets[k],(int,float)) and not isinstance(targets[k],bool) and targets[k]>0 for k in targets)
    macro_energy=round(4*targets['protein']+4*targets['carbs']+9*targets['fat'],1) if ready else None
    return dict(saved_targets=targets,macro_energy_scenario=macro_energy,
                mismatch_kcal=round(macro_energy-targets['energy'],1) if ready else None,
                interpretation='User-entered targets are not validated needs. The 4/4/9 energy calculation is an approximate consistency check, affected by carbohydrate/fibre definitions. Do not overwrite targets; use shared-profile estimate_needs and guidance tools to assess applicability. Ask about missing goals rather than assuming fat loss.')
