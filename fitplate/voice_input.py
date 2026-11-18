"""User-initiated, codec-aware recording with an upload fallback."""
import base64
import binascii
from pathlib import Path
import streamlit as st
from fitplate.i18n import tr

LABELS = {
 'record':'Record voice','stop':'Stop recording','upload':'Upload recording','use':'Use recording',
 'review':'Listen to the recording, then use it to transcribe.',
 'permission':'Allow microphone access in your browser to start recording.',
 'pending':'The microphone permission request is still waiting. Check the browser permission prompt, or upload a recording.',
 'unsupported':'Recording is unavailable in this browser. Open this HTTPS page in Safari or Chrome, or upload a recording.',
 'denied':'Microphone access was denied. Allow it in the browser site settings, or upload a recording.',
 'missing':'No microphone was found. Connect a microphone or upload a recording.',
 'failed':'Recording could not start. Close other recording apps, try Safari or Chrome, or upload a recording.',
 'invalid':'Choose a non-empty recording smaller than 10 MB and up to 60 seconds.',
 'recording':'Recording:','sending':'Sending recording for transcription...'
}
recorder=st.components.v2.component('fitplate_voice_recorder',js=(Path(__file__).resolve().parents[1]/'assets/voice_recorder.js').read_text(encoding='utf-8'))


def decode_recording(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('id'),str) or len(payload['id'])>128:
        raise ValueError('The recording payload is invalid. Please record again.')
    value=payload.get('base64');note=payload.get('note','')
    if not isinstance(value,str) or len(value)>14*1024*1024 or not isinstance(note,str) or len(note)>4000:
        raise ValueError('Choose a non-empty recording smaller than 10 MB and up to 60 seconds.')
    try:data=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise ValueError('The recording payload is invalid. Please record again.') from None
    if not data or len(data)>10*1024*1024:
        raise ValueError('Choose a non-empty recording smaller than 10 MB and up to 60 seconds.')
    from fitplate.audio_upload import AUDIO_SUFFIXES
    name=payload.get('name','')
    if not isinstance(name,str) or Path(name).suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError('The recording payload is invalid. Please record again.')
    return {'data':data,'name':Path(name).name,'text':note,'source':'Voice'}


def voice_input(process):
    result=recorder(data={key:tr(value) for key,value in LABELS.items()},key='voice_recorder',on_recording_change=lambda:None)
    payload=result.recording
    if not payload:
        return
    if not isinstance(payload,dict):
        st.session_state.ai_error='The recording payload is invalid. Please record again.'
        return
    if payload.get('id')==st.session_state.get('_voice_processed'):
        return
    try:
        media=decode_recording(payload)
        st.session_state['_voice_processed']=payload['id']
        st.session_state.pending_media=media
        if process(media):st.session_state.pending_media=None
    except ValueError as error:st.session_state.ai_error=str(error)
    st.rerun()
