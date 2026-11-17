"""Compact, explicit body-profile editing; no inferred or automatically saved measurements."""
from fitplate.ui import st
from fitplate.coaching import GOALS,EXPERIENCE,TRAINING,ACTIVITY,SEX,HEALTH,missing_fields
from fitplate.storage import read_body_profile,save_body_profile


def body_profile_editor():
    body=read_body_profile()
    expanded=st.session_state.pop('open_body_profile',False)
    with st.expander('Body & training profile',expanded=expanded):
        st.caption('For adults 18 and older. Add your current measurements and usual training; optional fields can stay blank. Your saved nutrition targets are separate.')
        with st.form('body_training_form'):
            left,right=st.columns(2)
            with left:
                age=st.number_input('Age (years)',min_value=18,max_value=100,value=body['age'],step=1,key='body_age')
                height=st.number_input('Height (cm)',min_value=80.0,max_value=250.0,value=body['height_cm'],step=0.5,key='body_height')
                weight=st.number_input('Weight (kg)',min_value=25.0,max_value=350.0,value=body['weight_kg'],step=0.1,key='body_weight')
                goal=st.selectbox('Main goal',GOALS,index=GOALS.index(body['goal']),key='body_goal')
                sex=st.selectbox('Sex for energy estimate (optional)',SEX,index=SEX.index(body['sex']),key='body_sex',help='The resting-energy equation uses male or female coefficients. Leave this unprovided if it is not suitable; AI can still offer other guidance.')
            with right:
                days=st.number_input('Training days per week',min_value=0,max_value=7,value=body['training_days'],step=1,key='body_days')
                training=st.selectbox('Usual training',TRAINING,index=TRAINING.index(body['training_type']),key='body_training')
                experience=st.selectbox('Training experience',EXPERIENCE,index=EXPERIENCE.index(body['experience']),key='body_experience')
                activity=st.selectbox('Usual activity including training',ACTIVITY,index=ACTIVITY.index(body['activity']),key='body_activity')
                health=st.selectbox('Health & training considerations',HEALTH,index=HEALTH.index(body['health']),key='body_health',help='Choose Professional guidance needed for a relevant medical condition, pregnancy/breastfeeding, eating-disorder concern or injury. You do not need to enter a diagnosis. Not shared keeps advice general.')
            share=st.checkbox('Allow AI to use my saved body & training profile',value=body['share_with_ai'],key='body_share')
            st.caption('When enabled, the assistant may send these measurements and training details to your configured Alibaba Cloud Model Studio service when you send a message. When disabled, the saved profile stays local; anything you type into chat is still sent when submitted.')
            if st.form_submit_button('Save body & training profile',type='primary',width='stretch'):
                try:
                    save_body_profile(dict(age=age,height_cm=height,weight_kg=weight,goal=goal,training_days=days,
                                           training_type=training,experience=experience,activity=activity,sex=sex,
                                           health=health,share_with_ai=share))
                    st.session_state.notice='Your body and training profile has been saved.'
                    st.rerun()
                except ValueError as error:st.error(str(error))
        missing=missing_fields(body)
        if missing:st.caption('Complete age, height, weight, goal, training frequency, experience, activity and health considerations for individualized reference estimates. You can continue logging meals without them.')
        elif not body['share_with_ai']:st.caption('Profile saved locally. AI sharing is off; chat can still provide general suggestions.')
        else:st.caption('Your profile is available for AI coaching. Advice does not change saved targets or meal records.')
