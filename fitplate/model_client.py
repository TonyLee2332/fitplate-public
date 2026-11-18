"""Small server-side clients for Model Studio. Credentials never reach the UI."""

import base64
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import socket
import tomllib
import urllib.error
import urllib.request
import wave

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ServiceError(Exception):
    """An English, credential-free message safe to show to a user."""


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = field(repr=False)
    workspace: str
    region: str
    chat_model: str = 'qwen3.8-omni-flash'
    asr_model: str = 'qwen-audio-3.1-asr-flash'

    @property
    def host(self):
        return f'{self.workspace}.{self.region}.maas.aliyuncs.com'


CONFIG_NAMES = ('DASHSCOPE_API_KEY', 'MODEL_STUDIO_WORKSPACE_ID', 'MODEL_STUDIO_REGION')


def shared_config_path():
    base = Path(os.environ.get('APPDATA') or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'FitPlate' / 'secrets.toml'


def load_config(path=None):
    if path is None and any(name in os.environ for name in CONFIG_NAMES):
        return validate_config({name: os.environ.get(name) for name in CONFIG_NAMES}, 'administrator environment')
    if path is not None:
        config_path = Path(path)
    elif os.environ.get('FITPLATE_CONFIG_FILE'):
        config_path = Path(os.environ['FITPLATE_CONFIG_FILE'])
    else:
        local = ROOT / '.streamlit/secrets.toml'
        config_path = local if local.exists() else shared_config_path()
    try:
        values = tomllib.loads(config_path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        if path is None:
            raise ServiceError('The shared AI service is not configured by the administrator yet. Manual meal entry remains available.') from None
        raise ServiceError(f'AI settings are missing for this copy of FitPlate. Add your credentials to {config_path}.') from None
    except (OSError, UnicodeError):
        raise ServiceError(f'FitPlate could not read its AI settings. Check file access and UTF-8 encoding: {config_path}.') from None
    except tomllib.TOMLDecodeError:
        raise ServiceError(f'AI settings contain invalid TOML syntax. Correct {config_path}; keep values inside quotation marks.') from None
    return validate_config(values, str(config_path))


def validate_config(values, config_path):
    names = CONFIG_NAMES
    for name in names:
        value = values.get(name)
        if not isinstance(value,str) or not value.strip() or value.strip().startswith('YOUR_'):
            raise ServiceError(f'AI setting {name} is missing, invalid or still a placeholder. Update {config_path}.')
    key, workspace, region = (values[name].strip() for name in names)
    if not re.fullmatch(r'[A-Za-z0-9-]+', workspace):
        raise ServiceError(f'MODEL_STUDIO_WORKSPACE_ID must contain only the workspace ID, without a URL or domain. Update {config_path}.')
    if region not in ('cn-beijing', 'cn-hongkong', 'ap-southeast-1', 'us-east-1', 'eu-central-1', 'ap-northeast-1'):
        raise ServiceError(f'MODEL_STUDIO_REGION is unsupported. Use the region for your workspace, such as cn-beijing. Update {config_path}.')
    return ModelConfig(key, workspace, region)


def post_json(config, path, payload):
    from fitplate.usage_guard import request_slot
    with request_slot():
        return _post_json(config, path, payload)


def _post_json(config, path, payload):
    request = urllib.request.Request(
        f'https://{config.host}{path}', data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': f'Bearer {config.api_key}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ServiceError('The AI response was too large. Try a shorter meal description.')
        result = json.loads(data)
    except urllib.error.HTTPError as error:
        messages = {
            401: 'The AI credentials were not accepted. Check the API key and region.',
            403: 'The AI provider denied access. Check service activation, account status, and model permissions.',
            429: 'The AI service is busy or its quota has been reached. Please try again later.',
        }
        # Retain a bounded provider reason without exposing credentials or request content.
        provider_code = ''
        provider_message = ''
        try:
            failure = json.loads(error.read(8192))
            detail = failure.get('error', failure)
            if isinstance(detail, dict):
                provider_code = str(detail.get('code') or detail.get('type') or '')[:100]
                provider_message = str(detail.get('message') or '')[:300]
            for secret in (config.api_key, config.host):
                provider_code = provider_code.replace(secret, '[redacted]')
                provider_message = provider_message.replace(secret, '[redacted]')
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        problem = ServiceError(messages.get(error.code, f'The AI request failed (HTTP {error.code}). Your draft is unchanged; check the service configuration or enter the meal manually.'))
        problem.status_code = error.code
        problem.provider_code = provider_code
        problem.provider_message = provider_message
        raise problem from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise ServiceError('The AI service could not be reached. Your draft is unchanged. Please try again later.') from None
    except (ValueError, UnicodeError):
        raise ServiceError('The AI service returned an unreadable response. Your draft is unchanged.') from None
    if not isinstance(result, dict) or result.get('error') or result.get('code'):
        raise ServiceError('The AI service could not complete this request. Your draft is unchanged.')
    return result


def prepare_image(data):
    from fitplate.photo_upload import normalize_photo, PhotoError
    try:
        prepared = normalize_photo(data)
    except PhotoError as error:
        raise ServiceError(str(error)) from None
    return 'data:image/jpeg;base64,' + base64.b64encode(prepared).decode('ascii')


class ModelClient:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.usage = []

    def chat(self, messages):
        result = post_json(self.config, '/compatible-mode/v1/chat/completions', {
            'model': self.config.chat_model, 'messages': messages,
            'response_format': {'type': 'json_object'}, 'reasoning_effort': 'none',
            'max_tokens': 1800, 'stream': False,
        })
        self.usage.append({'model': self.config.chat_model, **result.get('usage', {})})
        try:
            choice = result['choices'][0]
            if choice.get('finish_reason') == 'length':
                raise ValueError()
            content = choice['message']['content']
            if not isinstance(content, str):
                raise ValueError()
            return content
        except (KeyError, IndexError, TypeError, ValueError):
            raise ServiceError('The AI reply was incomplete. Try a shorter meal description.') from None

    def chat_with_tools(self,messages,tools):
        result=post_json(self.config,'/compatible-mode/v1/chat/completions',{
            'model':self.config.chat_model,'messages':messages,'tools':tools,'tool_choice':'auto',
            'parallel_tool_calls':False,
            'reasoning_effort':'none','max_tokens':5000,'stream':False,
        })
        self.usage.append({'model':self.config.chat_model,**result.get('usage',{})})
        try:
            choice=result['choices'][0]
            if choice.get('finish_reason')=='length':raise ValueError()
            message=choice['message']
            calls=message.get('tool_calls',[])
            if calls:
                if not isinstance(calls,list) or len(calls)!=1:raise ValueError()
                call=calls[0]
                if call.get('type')!='function' or not isinstance(call.get('id'),str):raise ValueError()
                function=call['function']
                if not isinstance(function.get('name'),str) or not isinstance(function.get('arguments'),str):raise ValueError()
            elif not isinstance(message.get('content'),str):raise ValueError()
            return dict(role='assistant',content=message.get('content') or None,**({'tool_calls':calls} if calls else {}))
        except (KeyError,IndexError,TypeError,ValueError):
            raise ServiceError('The AI tool reply was incomplete. Your records are unchanged; try a shorter question.') from None

    def transcribe(self, data, filename):
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise ServiceError('Choose an audio file smaller than 10 MB.')
        from fitplate.audio_upload import normalize_mobile_audio
        try:
            data, filename = normalize_mobile_audio(data, filename)
        except ValueError as error:
            raise ServiceError(str(error)) from None
        extension = Path(filename).suffix.lower()
        if extension not in ('.wav', '.mp3'):
            raise ServiceError('Use a WAV or MP3 file, or record a meal note in the app.')
        parameters = {'format': extension[1:]}
        if extension == '.wav':
            try:
                with wave.open(io.BytesIO(data)) as audio:
                    rate = audio.getframerate()
                    duration = audio.getnframes() / rate
                    if audio.getnchannels() not in (1, 2) or not 0 < duration <= 60:
                        raise ValueError()
                parameters['sample_rate'] = str(rate)
            except (wave.Error, EOFError, ValueError, ZeroDivisionError):
                raise ServiceError('Use a valid WAV recording of up to 60 seconds.') from None
        else:
            from mutagen.mp3 import MP3
            try:
                duration = MP3(io.BytesIO(data)).info.length
                if not 0 < duration <= 60:
                    raise ValueError()
            except Exception:
                raise ServiceError('Use a valid MP3 recording of up to 60 seconds.') from None
        mime = 'audio/wav' if extension == '.wav' else 'audio/mpeg'
        uri = f'data:{mime};base64,' + base64.b64encode(data).decode('ascii')
        result = post_json(self.config, '/api/v1/services/aigc/multimodal-generation/generation', {
            'model': self.config.asr_model,
            'input': {'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': uri}}]}]},
            'parameters': parameters,
        })
        self.usage.append({'model': self.config.asr_model, **result.get('usage', {})})
        output = result.get('output', result)
        text = output.get('text') or output.get('sentence', {}).get('text') or ''
        if not isinstance(text, str) or not text.strip():
            raise ServiceError('No clear speech was detected. Try recording again or type your meal.')
        if len(text) > 4000:
            raise ServiceError('The transcript is too long. Use a shorter recording.')
        return text.strip()
