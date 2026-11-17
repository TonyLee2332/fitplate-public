"""Compact weekly review UI using saved snapshots only."""
import csv
import io
from fitplate.ui import st
from fitplate.i18n import tr
from fitplate.domain import today
from fitplate.weekly import weekly_summary

LABELS={'energy':'Energy','protein':'Protein','carbs':'Carbs','fat':'Fat'}


def weekly_review(meals,settings,on_review):
    st.markdown('#### '+tr('Weekly summary'))
    left,right=st.columns(2)
    with left:mode=st.selectbox('Review period',('calendar_week','rolling_7'),format_func=lambda x:tr('Calendar week' if x=='calendar_week' else 'Last 7 days'),key='weekly_mode')
    with right:anchor=st.date_input('Review date',value=today(),max_value=today(),key='weekly_date')
    result=weekly_summary(meals,settings,mode,anchor.isoformat())
    st.caption(f"{result['start']} — {result['end']}")
    cols=st.columns(4)
    for col,label,value in zip(cols,('Logged days','Saved meals','Foods calculated','Days with incomplete meals'),
                               (f"{result['logged_days']}/{result['period_days']}",str(result['saved_meals']),f"{result['calculated_foods']}/{result['recorded_foods']}",str(result['days_with_incomplete_meals']))):
        col.metric(label,value)
    st.caption('Calendar weeks run Monday to Sunday; the current week stops at today. No records means unknown intake, not zero.' if mode=='calendar_week' else 'The last 7 days include the review date and the six preceding days. No records means unknown intake, not zero.')
    st.caption('Fully calculated records do not confirm that every meal was logged. Figures below are recorded subtotals, not verified full-day intake.')
    if not result['saved_meals']:
        st.info('No saved meals in this period. Save a meal to begin your weekly review.')
        return
    nutrient=st.selectbox('Nutrient trend',tuple(LABELS),format_func=lambda k:tr(LABELS[k]),key='weekly_nutrient')
    unit=tr('kcal' if nutrient=='energy' else 'g')
    blocked=nutrient=='carbs' and not result['carbohydrates_comparable']
    if blocked:st.info('Carbohydrate definitions differ across sources. The weekly carbohydrate trend and average are unavailable.')
    else:
        values=[dict(day=r['date'],value=r[nutrient],status=tr(r['status']),partial=bool(r['incomplete_meals'])) for r in result['days']]
        target=result['current_targets'][nutrient]
        st.caption(tr('Recorded subtotal')+' · '+unit)
        x={'field':'day','type':'ordinal','title':None,'sort':[r['date'] for r in result['days']],
           'axis':{'labelAngle':0,'labelExpr':"slice(datum.label, 5, 7) + '/' + slice(datum.label, 8, 10)",'labelPadding':12,'tickSize':0,'domain':False},'scale':{'padding':.55}}
        y={'field':'value','type':'quantitative','title':None,'scale':{'zero':True,'nice':True},'axis':{'tickCount':4,'format':',.0f','labelPadding':10,'domain':False,'tickSize':0}}
        tooltip=[{'field':'day','title':tr('Date')},{'field':'value','title':tr('Recorded subtotal')+' ('+unit+')','format':',.1f'},{'field':'status','title':tr('Calculation status')}]
        layers=[{'mark':{'type':'bar','size':30,'cornerRadiusTopLeft':6,'cornerRadiusTopRight':6,'color':'#80a99b'},
                 'encoding':{'x':x,'y':y,'opacity':{'condition':{'test':'datum.partial','value':.65},'value':.95},'tooltip':tooltip}},
                {'mark':{'type':'text','dy':-12,'fontSize':12,'fontWeight':500,'color':'#4e645c'},
                 'encoding':{'x':x,'y':y,'text':{'field':'value','type':'quantitative','format':',.0f' if nutrient=='energy' else ',.1f'},'tooltip':tooltip}}]
        if target:
            layers.extend([{'data':{'values':[{}]},'mark':{'type':'rule','color':'#85a59d','strokeDash':[4,5],'strokeWidth':1,'opacity':.8},'encoding':{'y':{'datum':target}}},
                           {'data':{'values':[{}]},'mark':{'type':'text','align':'right','baseline':'bottom','dy':-7,'color':'#6c8d83','fontSize':11},
                            'encoding':{'x':{'value':'width'},'y':{'datum':target},'text':{'value':tr('Current target')+' · '+f'{target:,.0f}'}}}])
        if any(row['value'] is not None for row in values):
            st.vega_lite_chart({'data':{'values':values},'layer':layers,'height':190,'padding':{'left':0,'right':8,'top':28,'bottom':0},
                               'background':'transparent','config':{'view':{'stroke':None},'font':'Inter, Microsoft JhengHei, Microsoft YaHei, sans-serif',
                                'axis':{'labelColor':'#89938c','labelFontSize':11,'gridColor':'#dce3dd','gridOpacity':.65,'gridDash':[2,5]}}},width='stretch',theme=None)
        else:st.info('No calculated values are available for this nutrient in the selected period.')
        average=result['mean_recorded_subtotals'][nutrient]
        st.caption(f"Mean recorded subtotal: {'—' if average is None else str(average)+' '+unit} · {result['calculated_days'][nutrient]} day(s) with calculated values.")
        if target:st.caption(f'Current daily target: {target:g} {unit}. The dashed line uses your current target; historical targets are not stored.')
        else:st.caption('No current target is set for this nutrient.')
    with st.expander('Daily calculation details'):
        rows=[{tr('Date'):r['date'],tr('Calculation status'):tr(r['status']),tr('Saved meals'):r['meal_count'],
               tr('Foods calculated'):f"{r['calculated_foods']}/{r['food_count']}",
               **{tr(LABELS[k]):r[k] for k in LABELS}} for r in result['days']]
        st.dataframe(rows,hide_index=True,width='stretch')
        st.caption('Blank nutrient values are unknown. Zero appears only when a calculated subtotal is actually zero. Nutrients use kcal for energy and grams for protein, carbs and fat.')
    output=io.StringIO();fields=['date','status','meal_count','food_count','calculated_foods','incomplete_meals','estimated_meals',*LABELS]
    writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader();writer.writerows(result['days'])
    st.download_button('Export weekly details',output.getvalue().encode('utf-8-sig'),file_name=f"fitplate_week_{result['start']}_{result['end']}.csv",mime='text/csv',key='weekly_export')
    if st.button('Generate AI weekly review',icon=':material/chat_bubble_outline:',key='weekly_ai_review'):
        prompt=tr('Review my weekly saved nutrition records for {0} using {1}. Use the weekly_summary tool, explain record completeness, compare with current targets cautiously, and suggest one or two practical next steps. Do not infer training progress or deficiencies from missing records.').format(anchor.isoformat(),mode)
        on_review(prompt)
