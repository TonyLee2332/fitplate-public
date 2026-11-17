from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import Mock
import numpy as np
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from fitplate.domain import fresh_draft
from fitplate.meal_estimation import assess_meal, validate_details, questions_for
from fitplate.nutrition import DEFAULT_DB
from fitplate.storage import save_meal, list_meals
from fitplate.uncertainty import sample_meal
from fitplate.cooking import project_cooking
from fitplate.image_analysis import calibrated_volume,validate_decomposition,decompose
from fitplate.model_client import ServiceError

APP=str(Path(__file__).resolve().parents[1]/'app.py')


def meal():
    recipe=dict(finished_weight_g=120,ingredients=[dict(food_id=1171287,grams=100),dict(food_id=1168462,grams=50),dict(food_id=1171413,grams=10)])
    return {**fresh_draft(),'items':[dict(name='Egg and spinach',quantity=60,unit='g',preparation='Cooked',details=dict(cooking=recipe))]}


def test_fao_mass_balance_and_one_time_retention():
    m=meal();original=deepcopy(m);result=assess_meal(m)
    expected=sum(DEFAULT_DB.by_id[r['food_id']].protein*r['grams']/100 for r in m['items'][0]['details']['cooking']['ingredients'])/2
    assert result['computed_count']==1 and not result['estimation_errors']
    assert result['totals']['protein']==pytest.approx(expected,abs=.1)
    assert result['items'][0]['quantity']==60
    assert result['items'][0]['cooking_source']['yield_factor']==.75
    assert m==original
    r=m['items'][0]['details']['cooking']['ingredients'][0]
    r.update(retention=dict(protein=.5),retention_source='https://example.org/user-supplied-evidence')
    revised=assess_meal(m)
    assert revised['totals']['protein']==pytest.approx(expected-DEFAULT_DB.by_id[1171287].protein*.25,abs=.1)
    assert revised['items'][0]['components'][0]['recipe_retention']['protein']==.5


def test_cooking_finished_weight_changes_density_not_batch_nutrients():
    m=meal();low=assess_meal(m)['totals']['energy']
    m['items'][0]['details']['cooking']['finished_weight_g']=240
    assert assess_meal(m)['totals']['energy']==pytest.approx(low/2,abs=.1)


@pytest.mark.parametrize('problem',['raw_portion','over_portion','no_source','double_retention','negative','unknown_food'])
def test_invalid_cooking_is_not_silently_calculated(problem):
    m=meal();i=m['items'][0];r=i['details']['cooking']
    if problem=='raw_portion':i['preparation']='Raw'
    if problem=='over_portion':i['quantity']=121
    if problem=='negative':r['finished_weight_g']=-1
    if problem=='unknown_food':r['ingredients'][0]['food_id']=99999999
    if problem=='no_source':r['ingredients'][0]['retention']={'protein':.5}
    if problem=='double_retention':r['ingredients'][0].update(food_id=1173424,retention={'protein':.5},retention_source='https://example.org/reference')
    result=assess_meal(m)
    assert result['estimation_errors'] and result['totals']['energy'] is None


def test_cooking_snapshot_and_sampling_save_and_stale_invalidation():
    m=meal();m['uncertainty_analysis']=sample_meal(m);m['estimate_reviewed']=True
    save_meal(m);saved=list_meals()[0]
    assert saved['nutrition']['items'][0]['cooking_source']
    assert saved['nutrition']['uncertainty_analysis']['seed']==42
    m['items'][0]['quantity']=30
    assert 'uncertainty_analysis' not in assess_meal(m)
    assert questions_for(m)==[]


def test_sampling_is_reproducible_and_uncertainty_is_not_applied_to_weighed_fao_batch():
    m=meal();a=sample_meal(m);b=sample_meal(m)
    assert a==b and a['drivers']==[]
    assert a['statistics']['energy']['p05']==a['statistics']['energy']['p95']
    uncertain={**fresh_draft(),'items':[dict(name='Chicken breast',quantity=None,unit='g',preparation='Cooked',details=dict(estimated_grams=180,estimate_basis='Visual assumption.'))]}
    original=deepcopy(uncertain)
    a=sample_meal(uncertain,256,42);b=sample_meal(uncertain,256,99)
    assert a['statistics']['energy']['p05']<a['statistics']['energy']['p95']
    assert a['statistics']!=b['statistics'] and a['drivers']
    assert uncertain==original


def test_sampling_rejects_partial_meals():
    m={**fresh_draft(),'items':[dict(name='xyzunknown',quantity=100,unit='g',preparation='Raw')]}
    with pytest.raises(ValueError,match='Resolve'):
        sample_meal(m)


def test_missing_cooked_portion_returns_validation_message():
    from fitplate.domain import validate_draft
    m=meal();m['items'][0]['quantity']=None;m['estimate_reviewed']=True
    assert 'Cooked edible portion' in validate_draft(m)


def test_geometry_synthetic_volume_and_no_unscaled_weight():
    depth=np.zeros((100,100));depth[25:75,25:75]=2
    r=calibrated_volume(depth,[.25,.25,.75,.75],[0,0,1,1],20,3,.6,True)
    assert r['volume_ml']==300 and r['estimated_grams']==180
    with pytest.raises(ValueError,match='near-overhead'):
        calibrated_volume(depth,[.25,.25,.75,.75],[0,0,1,1],20,3,.6,False)
    with pytest.raises(ValueError):
        calibrated_volume(depth,[.25,.25,.75,.75],[0,0,1,1],None,3,.6,True)
    with pytest.raises(ValueError):
        calibrated_volume(np.ones((100,100)),[.25,.25,.75,.75],[0,0,1,1],20,3,.6,True)


@pytest.mark.parametrize('bad',[[-.1,0,.5,.5],[.5,.5,.2,.7],[0,0,1,float('nan')]])
def test_invalid_image_bounds_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_decomposition(dict(foods=[dict(name='Egg',bbox=bad,preparation='Unknown',visible_details='')],plate_bbox=None,notes=''))


def click(app,label):
    next(b for b in app.button if b.label==label).click().run()
    assert not app.exception


def test_ui_cooking_sampling_and_save():
    app=AppTest.from_file(APP,default_timeout=30).run()
    app.session_state['draft']=meal();app.session_state['draft_revision']+=1;app.run()
    assert not app.exception
    click(app,'Run sampling analysis')
    assert app.session_state['draft']['uncertainty_analysis']['statistics']
    next(c for c in app.checkbox if c.label=='I reviewed the estimated portions and recipe assumptions').check()
    click(app,'Save meal')
    assert list_meals()[0]['nutrition']['items'][0]['estimate_kind']=='FAO recipe calculation'


def test_photo_regions_depth_calibration_apply_is_explicit(monkeypatch):
    from fitplate import image_analysis as images
    buffer=io.BytesIO();Image.new('RGB',(100,100),'white').save(buffer,'PNG');data=buffer.getvalue()
    analysis=dict(foods=[dict(name='Chicken breast',bbox=[.25,.25,.75,.75],preparation='Unknown',visible_details='Visible region.')],plate_bbox=[0,0,1,1],notes='Assumptions require review.')
    analyse=Mock(return_value=analysis);monkeypatch.setattr(images,'decompose',analyse)
    depth=np.zeros((100,100));depth[25:75,25:75]=2
    infer=Mock(return_value=(depth,dict(image_sha256=hashlib.sha256(data).hexdigest(),model='test depth')));monkeypatch.setattr(images,'estimate_depth',infer)
    app=AppTest.from_file(APP,default_timeout=30).run()
    app.session_state['messages']=[dict(role='user',text='My meal',image=data)]
    app.session_state['draft']={**fresh_draft(),'items':[dict(name='Chicken breast',quantity=None,unit='g',preparation='Cooked')]}
    app.session_state['draft_revision']+=1;app.run()
    assert analyse.call_count==infer.call_count==0
    click(app,'Decompose photo');click(app,'Estimate relative depth locally')
    for label,value in [('Reference width (cm)',20.),('Assumed peak food height (cm)',3.),('Assumed bulk density (g/ml)',.6)]:
        next(n for n in app.number_input if n.label==label).set_value(value)
    next(c for c in app.checkbox if c.label=='The image is near-overhead and the reference lies on a flat plane').check()
    click(app,'Calculate calibrated geometry scenario')
    next(c for c in app.checkbox if c.label=='I reviewed the region, scale, height and density assumptions').check()
    click(app,'Apply geometry estimate to draft')
    assert app.session_state['draft']['items'][0]['quantity'] is None
    assert app.session_state['draft']['items'][0]['details']['estimated_grams']==180
    app.run();assert analyse.call_count==infer.call_count==1
    assert list_meals()==[]
