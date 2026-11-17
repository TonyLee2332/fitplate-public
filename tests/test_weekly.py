from datetime import date
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import json
import pytest
from streamlit.testing.v1 import AppTest
from fitplate import weekly,agent
from fitplate.domain import fresh_draft,today
from fitplate.nutrition.service import fingerprint
from fitplate.storage import save_meal,delete_meal,list_meals,read_settings
from fitplate.i18n import tr

APP=str(Path(__file__).resolve().parents[1]/'app.py')
REAL_RESPOND=agent.respond


def record(day,energy=100,partial=False,definition='Total carbohydrate by difference'):
    m={**fresh_draft(),'date':day,'items':[dict(name='Test food')]+([dict(name='Unknown food')] if partial else [])}
    m['nutrition']=dict(input_fingerprint=fingerprint(m),completeness='partial' if partial else 'complete',computed_count=1,total_count=2 if partial else 1,
                        totals=dict(energy=energy,protein=10,carbs=20,fat=5),requires_estimate_review=False,
                        items=[dict(needs_confirmation=False,source=dict(carb_definition=definition))])
    return m


def test_calendar_week_bounds_and_exclusion_of_future_days(monkeypatch):
    monkeypatch.setattr(weekly,'today',lambda:date(2026,11,17))
    r=weekly.weekly_summary([],mode='calendar_week')
    assert (r['start'],r['end'],r['period_days'])==('2026-11-16','2026-11-17',2)
    previous=weekly.weekly_summary([],mode='calendar_week',anchor_date='2026-11-11')
    assert previous['start']=='2026-11-09' and previous['end']=='2026-11-15'
    with pytest.raises(ValueError):weekly.weekly_summary([],anchor_date='2026-11-18')


def test_rolling_averages_exclude_unknown_days_and_keep_partial_status(monkeypatch):
    monkeypatch.setattr(weekly,'today',lambda:date(2026,11,17))
    meals=[record('2026-11-11',100),record('2026-11-17',200,partial=True),record('2026-11-10',999)]
    before=deepcopy(meals)
    r=weekly.weekly_summary(meals,mode='rolling_7')
    assert r['logged_days']==2 and r['period_days']==7 and r['saved_meals']==2
    assert r['calculated_days']['energy']==2 and r['mean_recorded_subtotals']['energy']==150
    assert r['recorded_foods']==3 and r['calculated_foods']==2 and r['days_with_incomplete_meals']==1
    assert r['days'][1]['energy'] is None and r['days'][-1]['status']=='Partial calculation'
    assert meals==before


def test_zero_is_a_known_value_and_stale_snapshots_are_unknown(monkeypatch):
    monkeypatch.setattr(weekly,'today',lambda:date(2026,11,17))
    m=record('2026-11-17',0)
    r=weekly.weekly_summary([m],mode='rolling_7')
    assert r['mean_recorded_subtotals']['energy']==0 and r['calculated_days']['energy']==1
    m['items'][0]['name']='Edited food'
    r=weekly.weekly_summary([m],mode='rolling_7')
    assert r['mean_recorded_subtotals']['energy'] is None and r['days'][-1]['status']=='Not calculated'


def test_carbohydrate_definitions_disable_weekly_comparison(monkeypatch):
    monkeypatch.setattr(weekly,'today',lambda:date(2026,11,17))
    r=weekly.weekly_summary([record('2026-11-16'),record('2026-11-17',definition='Available carbohydrate')],mode='rolling_7')
    assert r['carbohydrates_comparable'] is False and r['mean_recorded_subtotals']['carbs'] is None
    assert r['mean_recorded_subtotals']['protein']==10


def test_saved_edit_and_delete_immediately_change_weekly_totals():
    m={**fresh_draft(),'estimate_reviewed':True,'items':[dict(name='Boiled egg',quantity=100,unit='g',preparation='Boiled')]}
    save_meal(m);a=weekly.weekly_summary(list_meals())['recorded_subtotals']['protein']
    m['items'][0]['quantity']=200;save_meal(m)
    assert weekly.weekly_summary(list_meals())['recorded_subtotals']['protein']==pytest.approx(a*2,abs=.1)
    delete_meal(m['id'])
    assert weekly.weekly_summary(list_meals())['recorded_subtotals']['protein'] is None


@pytest.mark.parametrize('lang',['en','zh-Hans','zh-Hant'])
def test_weekly_ui_and_ai_request_are_read_only(lang,monkeypatch):
    save_meal({**fresh_draft(),'estimate_reviewed':True,'items':[dict(name='Boiled egg',quantity=100,unit='g',preparation='Boiled')]})
    before=deepcopy(list_meals());targets=read_settings()
    app=AppTest.from_file(APP,default_timeout=30).run()
    next(s for s in app.selectbox if s.key=='language_choice').set_value(lang).run()
    next(b for b in app.button if b.label==tr('Goals & insights',lang)).click().run()
    assert not app.exception
    assert any(tr('Weekly summary',lang) in m.value for m in app.markdown)
    next(s for s in app.selectbox if s.key=='weekly_mode').set_value('rolling_7').run()
    next(s for s in app.selectbox if s.key=='weekly_nutrient').set_value('protein').run()
    assert not app.exception and len(app.get('vega_lite_chart'))==1
    model=Mock(return_value=dict(intent='chat',reply='Review recorded portions first.',draft=None))
    monkeypatch.setattr(agent,'respond',model)
    next(b for b in app.button if b.key=='weekly_ai_review').click().run()
    assert not app.exception and 'weekly_summary' in model.call_args.args[0]
    assert list_meals()==before and read_settings()==targets


def test_agent_can_select_weekly_tool_and_retain_available_day_denominator():
    client=Mock(usage=[])
    client.chat.side_effect=[json.dumps(dict(intent='tool',reply='',meal=None,tool=dict(name='weekly_summary',arguments=dict(mode='rolling_7',anchor_date=today().isoformat())))),json.dumps(dict(intent='chat',reply='There is one logged day. The recorded energy subtotal is 100 kcal; the other days are unknown.',meal=None))]
    result=REAL_RESPOND('Review my last seven days',meals=[record(today().isoformat())],client=client)
    assert result['tool_trace'][0]['tool']=='weekly_summary'
    assert 'calculated_days' in client.chat.call_args.args[0][-1]['content']
