from pathlib import Path
from types import SimpleNamespace

import pytest
from talos.core import config

from wecubek8s.apps.plugin import api, controller
from wecubek8s.common import utils
from wecubek8s.server import base  # Registers the config interceptors.


@pytest.fixture(params=['Deployment', 'StatefulSet', 'DaemonSet'])
def workload(request):
    return getattr(controller, request.param)(), getattr(api, request.param)()


@pytest.fixture
def deploy_input():
    return {
        'cluster': 'sample-cluster',
        'correlation_id': 'sample-instance',
        'name': 'sample-app',
        'image_name': 'sample-app:latest',
    }


@pytest.mark.parametrize(('system_config', 'expected'), [
    ({}, 120),
    ({'pod_termination_grace_period_seconds': ' '}, 120),
    ({'pod_termination_grace_period_seconds': '180'}, 180),
    ({'pod_termination_grace_period_seconds': '0'}, 0),
    ({'pod_termination_grace_period_seconds': '1000000'}, 1000000),
    ({'pod_termination_grace_period_seconds': '1000001'}, 120),
    ({'pod_termination_grace_period_seconds': '-1'}, 120),
    ({'pod_termination_grace_period_seconds': '1.5'}, 120),
    ({'pod_termination_grace_period_seconds': 'invalid'}, 120),
    ({'pod_termination_grace_period_seconds': str(2 ** 63)}, 120),
])
def test_pod_template_uses_system_grace_period(
    workload, deploy_input, system_config, expected, monkeypatch
):
    monkeypatch.setattr(api, 'CONF', SimpleNamespace(**system_config))
    monkeypatch.setattr(utils, 'get_token', lambda: None)
    handler, resource_builder = workload
    clean_input = handler.validate_item_apply(0, deploy_input)

    resource = resource_builder.to_resource(None, clean_input, {})

    actual = resource['spec']['template']['spec'].get('terminationGracePeriodSeconds')
    assert type(actual) is int
    assert actual == expected


def test_apply_has_no_per_workload_grace_period_override(workload, deploy_input):
    handler, _ = workload
    deploy_input['terminationGracePeriodSeconds'] = '45'

    assert 'terminationGracePeriodSeconds' not in handler.validate_item_apply(0, deploy_input)


@pytest.mark.parametrize(('env_value', 'expected'), [
    ('', 120),
    ('180', 180),
])
def test_grace_period_loads_from_environment(env_value, expected, monkeypatch):
    conf = config.Config(None)
    monkeypatch.setattr(config, 'CONF', conf)
    monkeypatch.setattr(api, 'CONF', conf)
    monkeypatch.setenv('POD_TERMINATION_GRACE_PERIOD_SECONDS', env_value)

    base.config.setup(str(Path(__file__).resolve().parents[1] / 'etc/wecubek8s.conf'))

    assert api._pod_termination_grace_period_seconds() == expected
