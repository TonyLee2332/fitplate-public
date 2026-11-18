import base64
import io
import subprocess
import wave
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
from imageio_ffmpeg import get_ffmpeg_exe
from fitplate.audio_upload import normalize_mobile_audio
from fitplate.voice_input import decode_recording, LABELS
from fitplate.i18n import tr
from fitplate import agent


@pytest.mark.parametrize('extension,codec',[('m4a','aac'),('webm','libopus'),('ogg','libopus'),('flac','flac')])
def test_mobile_container_normalizes_to_pcm(tmp_path,extension,codec):
    source=tmp_path/('voice.'+extension)
    subprocess.run([get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','sine=frequency=440:duration=1','-c:a',codec,str(source)],check=True)
    raw,name=normalize_mobile_audio(source.read_bytes(),source.name)
    assert name=='recording.wav'
    with wave.open(io.BytesIO(raw)) as result:
        assert result.getframerate()==16000 and result.getnchannels()==1 and result.getsampwidth()==2


def test_invalid_audio_and_overlong_recording_rejected(tmp_path):
    with pytest.raises(ValueError,match='could not be decoded'):
        normalize_mobile_audio(b'not audio','voice.m4a')
    source=tmp_path/'long.m4a'
    subprocess.run([get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','62','-c:a','aac',str(source)],check=True)
    with pytest.raises(ValueError,match='60 seconds'):
        normalize_mobile_audio(source.read_bytes(),source.name)


def test_recorder_payload_and_labels():
    value=dict(id='test-event',name='recording.m4a',base64=base64.b64encode(b'test').decode(),note='My meal')
    assert decode_recording(value)==dict(name='recording.m4a',data=b'test',text='My meal',source='Voice')
    for bad in [None,[],{},dict(value,base64='???'),dict(value,name='test.exe'),dict(value,note='x'*4001)]:
        with pytest.raises(ValueError):decode_recording(bad)
    for lang in ['zh-Hans','zh-Hant']:
        for label in LABELS.values():assert tr(label,lang)!=label


@pytest.mark.parametrize('extension',['m4a','webm','ogg','mp4','caf'])
def test_mobile_attachment_routes_to_voice_not_photo(monkeypatch,extension):
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
    asr=Mock(return_value='Two eggs for breakfast.')
    monkeypatch.setattr(agent,'transcribe',asr)
    app.chat_input[0].upload('voice.'+extension,b'test audio','audio/mp4').run()
    assert not app.exception and asr.call_count==1
    assert 'Two eggs' in str(app.chat_input[0].proto)
    app.run();assert asr.call_count==1
