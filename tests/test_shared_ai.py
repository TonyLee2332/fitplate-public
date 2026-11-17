import json
from pathlib import Path

import pytest

from fitplate import model_client
from fitplate.model_client import ServiceError, load_config


def values():
    return dict(DASHSCOPE_API_KEY='admin-test-secret',MODEL_STUDIO_WORKSPACE_ID='ws-test',MODEL_STUDIO_REGION='cn-beijing')


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch,tmp_path):
    for name in (*model_client.CONFIG_NAMES,'FITPLATE_CONFIG_FILE'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setattr(model_client,'ROOT',tmp_path/'project')
    monkeypatch.setattr(model_client,'shared_config_path',lambda:tmp_path/'shared.toml')


def write_config(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(f'{k}="{v}"' for k,v in values().items()),encoding='utf-8')


def test_environment_needs_no_project_secret_file(monkeypatch):
    for k,v in values().items():monkeypatch.setenv(k,v)
    config=load_config()
    assert config.workspace=='ws-test' and config.api_key==values()['DASHSCOPE_API_KEY']
    assert config.api_key not in repr(config)


def test_partial_environment_does_not_fall_back_to_another_account(monkeypatch,tmp_path):
    write_config(tmp_path/'shared.toml')
    monkeypatch.setenv('MODEL_STUDIO_REGION','cn-beijing')
    with pytest.raises(ServiceError,match='DASHSCOPE_API_KEY'):load_config()


def test_shared_administrator_file_is_discovered(tmp_path):
    write_config(tmp_path/'shared.toml')
    assert load_config().workspace=='ws-test'


def test_explicit_path_is_independent_of_environment(monkeypatch,tmp_path):
    monkeypatch.setenv('DASHSCOPE_API_KEY','unrelated-secret')
    path=tmp_path/'explicit.toml';write_config(path)
    assert load_config(path).api_key=='admin-test-secret'


def test_custom_server_config_file(monkeypatch,tmp_path):
    path=tmp_path/'server.toml';write_config(path)
    monkeypatch.setenv('FITPLATE_CONFIG_FILE',str(path))
    assert load_config().workspace=='ws-test'


def test_missing_server_file_does_not_use_another_credential(monkeypatch,tmp_path):
    write_config(tmp_path/'shared.toml')
    monkeypatch.setenv('FITPLATE_CONFIG_FILE',str(tmp_path/'missing.toml'))
    with pytest.raises(ServiceError,match='administrator'):load_config()


def test_missing_service_does_not_ask_the_member_to_supply_a_key():
    with pytest.raises(ServiceError) as error:load_config()
    assert 'administrator' in str(error.value)
    assert 'secrets.toml' not in str(error.value)


def test_local_config_still_works(tmp_path):
    write_config(tmp_path/'project/.streamlit/secrets.toml')
    assert load_config().workspace=='ws-test'
