import io
import json
from copy import deepcopy
from unittest.mock import Mock
import urllib.error
import wave

from PIL import Image
import pytest

from fitplate import agent, model_client
from fitplate.domain import fresh_draft, today
from fitplate.model_client import ModelClient, ModelConfig, ServiceError

REAL_RESPOND = agent.respond


def payload(quantity=150, name='Chicken breast'):
    return {'intent': 'meal', 'reply': 'Saved your meal!', 'meal': {
        'date': today().isoformat(), 'meal_type': 'Lunch',
        'items': [{'name': name, 'quantity': quantity, 'unit': 'g', 'preparation': 'Cooked'}], 'note': '',
    }}


def test_model_cannot_set_identity_or_claim_a_save():
    original = fresh_draft()
    original['input_source'] = 'Voice'
    result = agent.decode_result(json.dumps(payload()), original, 'Text')
    assert result['draft']['id'] == original['id']
    assert result['draft']['input_source'] == 'Voice'
    assert 'saved' not in result['reply'].lower()
    assert 'review' in result['reply'].lower()
    assert original['items'] == []


@pytest.mark.parametrize('quantity', [True, -1, 0, float('nan'), float('inf'), 100001, '150'])
def test_bad_quantities_are_rejected(quantity):
    with pytest.raises(ValueError):
        agent.decode_result(json.dumps(payload(quantity)), None, 'Text')


def test_photo_never_accepts_model_weight_estimates():
    result = agent.decode_result(json.dumps(payload(150)), None, 'Photo')
    assert result['draft']['items'][0]['quantity'] is None
    assert result['draft']['input_source'] == 'Photo'


def test_missing_quantity_is_preserved_and_nonenglish_is_rejected():
    assert agent.decode_result(json.dumps(payload(None)), None, 'Text')['draft']['items'][0]['quantity'] is None
    with pytest.raises(ValueError):
        agent.decode_result(json.dumps(payload(name='雞胸肉')), None, 'Text')


def test_invalid_format_has_exactly_one_correction_and_no_draft_mutation():
    client = Mock(usage=[])
    client.chat.side_effect = ['[]', json.dumps(payload())]
    draft = fresh_draft()
    snapshot = deepcopy(draft)
    result = REAL_RESPOND('150 g chicken', draft=draft, client=client)
    assert result['draft']['items'][0]['quantity'] == 150
    assert client.chat.call_count == 2
    assert draft == snapshot
    client.chat.side_effect = ['[]', '[]']
    client.chat.reset_mock()
    with pytest.raises(ServiceError):
        REAL_RESPOND('150 g chicken', draft=draft, client=client)
    assert client.chat.call_count == 2
    assert draft == snapshot


def test_credential_is_not_in_repr_and_config_rejects_untrusted_host(tmp_path):
    config = ModelConfig('secret-value', 'ws-example', 'cn-beijing')
    assert 'secret-value' not in repr(config)
    path = tmp_path / 'secrets.toml'
    path.write_text('DASHSCOPE_API_KEY="secret-value"\nMODEL_STUDIO_WORKSPACE_ID="evil.example/path"\nMODEL_STUDIO_REGION="cn-beijing"')
    with pytest.raises(ServiceError) as error:
        model_client.load_config(path)
    assert 'secret-value' not in str(error.value)


def test_http_error_is_safe_and_not_retried(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError('https://example', 403, 'secret-value', {}, io.BytesIO(b'secret-value'))
    opener = Mock(side_effect=fail)
    monkeypatch.setattr(model_client.urllib.request, 'urlopen', opener)
    with pytest.raises(ServiceError) as error:
        model_client.post_json(ModelConfig('secret-value', 'ws-example', 'cn-beijing'), '/test', {})
    assert 'secret-value' not in str(error.value)
    assert opener.call_count == 1


def test_image_is_validated_resized_and_metadata_removed():
    with pytest.raises(ServiceError):
        model_client.prepare_image(b'not an image')
    image = Image.new('RGB', (1500, 600), 'green')
    buf = io.BytesIO()
    image.save(buf, 'PNG')
    uri = model_client.prepare_image(buf.getvalue())
    import base64
    prepared = Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1])))
    assert prepared.width == 1280
    assert prepared.format == 'JPEG'
    assert not prepared.getexif()


def test_audio_uses_actual_sample_rate_and_returns_transcript(monkeypatch):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\0\0' * 24000)
    post = Mock(return_value={'output': {'text': 'Two eggs.'}, 'usage': {'input_tokens': 10}})
    monkeypatch.setattr(model_client, 'post_json', post)
    client = ModelClient(ModelConfig('secret-value', 'ws-example', 'cn-beijing'))
    assert client.transcribe(buf.getvalue(), 'note.wav') == 'Two eggs.'
    assert post.call_args.args[2]['parameters']['sample_rate'] == '24000'
    assert len(client.usage) == 1
    with pytest.raises(ServiceError):
        client.transcribe(b'bad', 'note.m4a')


def test_unified_photo_submission_preserves_caption_and_does_not_repeat(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    image = io.BytesIO()
    Image.new('RGB', (40, 40), 'red').save(image, 'PNG')
    image.name = 'test.png'
    respond = Mock(return_value={'intent': 'meal', 'reply': 'Review your draft.', 'draft': fresh_draft(), 'usage': []})
    monkeypatch.setattr(agent, 'respond', respond)
    assert respond.call_count == 0
    app.chat_input[0].upload('meal.png', image.getvalue(), 'image/png').set_value('My lunch, without sauce').run()
    assert not app.exception
    assert respond.call_count == 1
    assert respond.call_args.args[0] == 'My lunch, without sauce'
    assert respond.call_args.kwargs['image'] == image.getvalue()
    app.run()
    assert respond.call_count == 1


def test_unified_voice_prefills_review_before_meal_analysis(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    asr = Mock(return_value='Two eggs for breakfast.')
    respond = Mock(return_value={'intent': 'meal', 'reply': 'Review your draft.', 'draft': fresh_draft(), 'usage': []})
    monkeypatch.setattr(agent, 'transcribe', asr)
    monkeypatch.setattr(agent, 'respond', respond)
    app.chat_input[0].upload('meal.wav', b'test audio', 'audio/wav').set_value('After training.').run()
    assert not app.exception
    assert asr.call_count == 1
    assert respond.call_count == 0
    assert app.session_state['voice_ready'] is not None
    assert app.session_state['draft'] is None
    app.run()
    assert asr.call_count == 1
    app.chat_input[0].set_value('After training. Three eggs for breakfast.').run()
    assert not app.exception
    assert respond.call_args.args[0] == 'After training. Three eggs for breakfast.'
    assert respond.call_args.kwargs['source'] == 'Voice'
    assert app.session_state['voice_ready'] is None


def test_failed_attachment_is_kept_and_retried_only_on_click(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
    asr = Mock(side_effect=[ServiceError('Temporarily unavailable.'), 'Two eggs.'])
    monkeypatch.setattr(agent, 'transcribe', asr)
    app.chat_input[0].upload('meal.wav', b'test audio', 'audio/wav').run()
    assert not app.exception
    assert app.session_state['pending_media']['data'] == b'test audio'
    app.run()
    assert asr.call_count == 1
    next(button for button in app.button if button.label == 'Retry attachment').click().run()
    assert not app.exception
    assert asr.call_count == 2
    assert app.session_state['pending_media'] is None
    assert app.session_state['voice_ready'] is not None

