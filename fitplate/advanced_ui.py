"""Optional recipe, uncertainty and image tools kept outside the main conversation."""
from copy import deepcopy
import hashlib
import numpy as np
from fitplate.ui import st
from fitplate.nutrition import DEFAULT_DB
from fitplate.reference_search import reference_candidates
from fitplate.model_client import ServiceError


def cooking_editor(item, index, revision):
    saved=item.get('details',{}).get('cooking',{})
    enabled=st.checkbox(f'Calculate from weighed ingredients {index+1}',value=bool(saved),key=f'cook_on_{revision}_{index}')
    if not enabled:
        return None
    st.caption('Enter the complete batch, including oil. Ingredient grams must match the raw/cooked state in the selected source. The main Portion field is the cooked amount eaten in grams. Update draft after changing the ingredient count.')
    finished=st.number_input(f'Finished batch weight (g) {index+1}',min_value=1.0,max_value=100000.0,value=float(saved.get('finished_weight_g',500)),key=f'finished_{revision}_{index}')
    existing=saved.get('ingredients',[])
    count=st.number_input(f'Ingredient count {index+1}',min_value=1,max_value=8,value=max(1,min(len(existing),8)),key=f'cook_n_{revision}_{index}')
    rows=[]
    for j in range(count):
        old=existing[j] if j<len(existing) else {}
        previous=DEFAULT_DB.by_id.get(old.get('food_id'))
        query=st.text_input(f'Ingredient search {index+1}.{j+1}',value=previous.source_food_description if previous else 'Chicken breast',key=f'cook_query_{revision}_{index}_{j}')
        choices=reference_candidates(query,limit=8,dataset='USDA')
        ids=list(dict.fromkeys(([previous.food_id] if previous else [])+[r['food_id'] for r in choices]))
        if not ids:
            st.caption('No ingredient match. Change the search and Update draft.')
            continue
        fid=st.selectbox(f'Ingredient source {index+1}.{j+1}',ids,format_func=lambda x:DEFAULT_DB.by_id[x].name,key=f'cook_id_{revision}_{index}_{j}')
        grams=st.number_input(f'Ingredient weight (g) {index+1}.{j+1}',min_value=0.1,max_value=100000.0,value=float(old.get('grams',100)),key=f'cook_g_{revision}_{index}_{j}')
        edible=st.number_input(f'Edible fraction {index+1}.{j+1}',min_value=.001,max_value=1.0,value=float(old.get('edible_fraction',1)),key=f'cook_edible_{revision}_{index}_{j}')
        row=dict(food_id=fid,grams=grams,edible_fraction=edible)
        with st.expander(f'Optional retention evidence {index+1}.{j+1}'):
            st.caption('Leave at 1 unless you have applicable nutrient-specific evidence. A factor of 1 is an accounting assumption, not proof of no cooking loss. Do not apply retention again to cooked source values.')
            factors={key:st.number_input(f'{key.title()} retention {index+1}.{j+1}',min_value=0.0,max_value=1.0,value=float(old.get('retention',{}).get(key,1)),key=f'rf_{key}_{revision}_{index}_{j}') for key in ('energy','protein','carbs','fat')}
            source=st.text_input(f'Retention evidence URL {index+1}.{j+1}',value=old.get('retention_source',''),key=f'rf_url_{revision}_{index}_{j}')
            if any(value!=1 for value in factors.values()):
                row.update(retention=factors,retention_source=source)
        rows.append(row)
    return dict(finished_weight_g=finished,ingredients=rows)


def uncertainty_tools(draft):
    from fitplate.uncertainty import sample_meal
    with st.expander('Explore estimation uncertainty'):
        st.caption('Explore assumed portion, recipe and oil variation locally. Results describe the selected model assumptions and are not calibrated confidence intervals.')
        samples=st.selectbox('Scenario samples',[256,512,1024],key='sample_count')
        if st.button('Run sampling analysis',key='run_sampling'):
            try:
                draft['uncertainty_analysis']=sample_meal(draft,samples=samples)
                st.session_state.draft=draft
                st.rerun()
            except ValueError as error:
                st.error(str(error))


def photo_tools():
    from fitplate import image_analysis as images
    latest=next((m.get('image') for m in reversed(st.session_state.messages) if m.get('image')),None)
    if latest is None:
        return
    with st.expander('Photo regions & depth'):
        digest=hashlib.sha256(latest).hexdigest()
        if st.session_state.get('geometry_image')!=digest:
            st.session_state.geometry_image=digest
            st.session_state.geometry_analysis=None
            st.session_state.geometry_depth=None
        st.caption('Inspect visible food regions and local relative depth. Volume requires a near-overhead reference, its physical width, an assumed peak food height and bulk density. Hidden ingredients and absolute scale cannot be established from one photo.')
        if st.button('Decompose photo',key='decompose_photo'):
            try:
                with st.spinner('Identifying visible food regions...'):
                    st.session_state.geometry_analysis=images.decompose(latest)
            except ServiceError as error:
                st.error(str(error))
        analysis=st.session_state.get('geometry_analysis')
        if not analysis:
            return
        st.image(images.overlay(latest,analysis['foods']),caption=analysis['notes'])
        for food in analysis['foods']:
            st.caption(f"{food['name']} · {food['preparation']} · {food['visible_details']}")
        if st.button('Estimate relative depth locally',key='estimate_depth'):
            try:
                with st.spinner('Running the local depth model...'):
                    depth,provenance=images.estimate_depth(latest)
                    st.session_state.geometry_depth=(depth,provenance)
            except ServiceError as error:
                st.error(str(error))
        state=st.session_state.get('geometry_depth')
        if state is None:
            return
        depth,provenance=state
        st.image(((depth-depth.min())/np.ptp(depth)*255).astype('uint8'),caption='Relative inverse depth: brighter is closer. No centimetres or grams are inferred here.')
        chosen=st.selectbox('Visible region',list(range(len(analysis['foods']))),format_func=lambda n:analysis['foods'][n]['name'])
        b=analysis['foods'][chosen]['bbox'];r=analysis.get('plate_bbox') or [0.,0.,1.,1.]
        fx=st.slider('Food horizontal range',0.,1.,(float(b[0]),float(b[2])))
        fy=st.slider('Food vertical range',0.,1.,(float(b[1]),float(b[3])))
        rx=st.slider('Reference horizontal range',0.,1.,(float(r[0]),float(r[2])))
        ry=st.slider('Reference vertical range',0.,1.,(float(r[1]),float(r[3])))
        width=st.number_input('Reference width (cm)',min_value=.1,max_value=100.,value=None)
        height=st.number_input('Assumed peak food height (cm)',min_value=.1,max_value=30.,value=None)
        density=st.number_input('Assumed bulk density (g/ml)',min_value=.01,max_value=3.,value=None)
        overhead=st.checkbox('The image is near-overhead and the reference lies on a flat plane')
        calibration_key=repr((chosen,fx,fy,rx,ry,width,height,density,overhead))
        if st.button('Calculate calibrated geometry scenario',key='calibrate_geometry'):
            try:
                result=images.calibrated_volume(depth,[fx[0],fy[0],fx[1],fy[1]],[rx[0],ry[0],rx[1],ry[1]],width,height,density,overhead)
                st.session_state.geometry_result={**result,'model':provenance,'food_name':analysis['foods'][chosen]['name'],'calibration_key':calibration_key}
            except ValueError as error:
                st.error(str(error))
        result=st.session_state.get('geometry_result')
        if result and result['model']['image_sha256']==digest and result.get('calibration_key')==calibration_key:
            st.write(f"Geometry scenario: approximately {result['volume_ml']:g} ml / {result['estimated_grams']:g} g")
            for warning in result['assumptions']:
                st.caption(warning)
            draft=st.session_state.draft
            if draft and draft.get('items'):
                target=st.selectbox('Apply to draft food',list(range(len(draft['items']))),format_func=lambda n:draft['items'][n]['name'])
                reviewed=st.checkbox('I reviewed the region, scale, height and density assumptions')
                if st.button('Apply geometry estimate to draft',key='apply_geometry'):
                    item=draft['items'][target]
                    if not reviewed:
                        st.error('Review the geometry assumptions first.')
                    elif item.get('confirmed_grams') or item.get('unit')=='g' and item.get('quantity') is not None:
                        st.error('A supplied gram weight takes precedence. Remove it explicitly before applying a geometry estimate.')
                    elif not 0<result['estimated_grams']<=3000:
                        st.error('The geometry estimate is outside the supported 1–3000 g range.')
                    else:
                        item.setdefault('details',{}).update(estimated_grams=result['estimated_grams'],estimate_basis='User-reviewed height-calibrated relative-depth scenario; scale, height and density remain assumptions.',image_geometry=deepcopy(result))
                        draft['estimate_reviewed']=False
                        st.session_state.draft_revision+=1
                        st.rerun()
