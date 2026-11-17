import pytest
from fitplate.model_client import load_config, ServiceError


def settings(**changes):
    values=dict(DASHSCOPE_API_KEY='private-example-value',MODEL_STUDIO_WORKSPACE_ID='ws-example',MODEL_STUDIO_REGION='cn-beijing')
    values.update(changes)
    return '\n'.join(f'{k} = "{v}"' for k,v in values.items())


def test_missing_file_identifies_the_active_copy(tmp_path):
    path=tmp_path/'secrets.toml'
    with pytest.raises(ServiceError) as error:
        load_config(path)
    assert 'missing for this copy' in str(error.value)
    assert str(path) in str(error.value)


@pytest.mark.parametrize('field,value',[('DASHSCOPE_API_KEY','YOUR_API_KEY'),('MODEL_STUDIO_WORKSPACE_ID','ws-example.cn-beijing.maas.aliyuncs.com'),('MODEL_STUDIO_REGION','unsupported')])
def test_invalid_field_identified_without_disclosing_values(tmp_path,field,value):
    path=tmp_path/'secrets.toml';path.write_text(settings(**{field:value}),encoding='utf-8')
    with pytest.raises(ServiceError) as error:
        load_config(path)
    assert field in str(error.value)
    assert 'private-example-value' not in str(error.value)
    assert value not in str(error.value) or value=='unsupported'


def test_invalid_toml_does_not_echo_the_secret_line(tmp_path):
    path=tmp_path/'secrets.toml';path.write_text('DASHSCOPE_API_KEY = "private-unclosed-value',encoding='utf-8')
    with pytest.raises(ServiceError) as error:
        load_config(path)
    assert 'TOML syntax' in str(error.value)
    assert 'private-unclosed-value' not in str(error.value)


def test_utf8_bom_and_whitespace_are_supported(tmp_path):
    path=tmp_path/'secrets.toml';path.write_text(settings(MODEL_STUDIO_REGION=' cn-beijing '),encoding='utf-8-sig')
    config=load_config(path)
    assert config.region=='cn-beijing' and config.workspace=='ws-example'
    assert 'private-example-value' not in repr(config)
