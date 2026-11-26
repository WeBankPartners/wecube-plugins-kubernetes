from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from talos.core import config

from wecubek8s.apps.plugin import api, controller
from wecubek8s.common import utils, wecube
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


def test_application_images_use_node_cache(workload, deploy_input, monkeypatch):
    monkeypatch.setattr(utils, 'get_token', lambda: None)
    handler, builder = workload
    item = handler.validate_item_apply(0, deploy_input)
    pod_spec = builder.to_resource(None, item, {})['spec']['template']['spec']

    assert pod_spec['containers'][0]['imagePullPolicy'] == 'IfNotPresent'


@pytest.mark.parametrize('workload_type', ['Deployment', 'StatefulSet'])
def test_package_init_image_uses_node_cache(workload_type, deploy_input, monkeypatch):
    monkeypatch.setattr(utils, 'get_token', lambda: None)
    item = getattr(controller, workload_type)().validate_item_apply(
        0, dict(deploy_input, packageUrl='https://packages.example.invalid/sample.tar.gz'),
    )
    pod_spec = getattr(api, workload_type)().to_resource(None, item, {'private_registry': ''})['spec']['template']['spec']

    assert pod_spec['initContainers'][0]['imagePullPolicy'] == 'IfNotPresent'


def test_package_deploy_job_image_uses_node_cache(monkeypatch):
    monkeypatch.setattr(api, 'CONF', SimpleNamespace(wecube=SimpleNamespace(base_url='')))
    wecube_client = Mock()
    wecube_client.login_subsystem.return_value = ''
    monkeypatch.setattr(wecube, 'WeCubeClient', lambda *args: wecube_client)
    data = {'namespace': 'default', 'pvc_name': 'sample-pvc', 'correlation_id': 'sample-instance',
            'package_url': 'https://packages.example.invalid/sample.tar.gz'}
    job, _ = api.PackageDeploy().to_resource(data, None, {})
    pod_spec = job['spec']['template']['spec']

    assert pod_spec['containers'][0]['imagePullPolicy'] == 'IfNotPresent'


@pytest.mark.parametrize('workload_type', ['Deployment', 'StatefulSet'])
def test_startup_probe_is_independent_of_rollout_budget(workload_type, deploy_input, monkeypatch):
    monkeypatch.setattr(api, 'CONF', SimpleNamespace(pod_ready_timeout='600'))
    monkeypatch.setattr(utils, 'get_token', lambda: None)
    handler = getattr(controller, workload_type)()
    item = handler.validate_item_apply(0, dict(deploy_input, image_port='8080'))
    pod_spec = getattr(api, workload_type)().to_resource(None, item, {})['spec']['template']['spec']
    container = pod_spec['containers'][0]

    for name, failures in [('startupProbe', 48), ('livenessProbe', 6), ('readinessProbe', 3)]:
        probe = container[name]
        assert probe['tcpSocket'] == {'port': 8080}
        assert probe['periodSeconds'] == 10
        assert probe['timeoutSeconds'] == 5
        assert probe['failureThreshold'] == failures
        assert 'initialDelaySeconds' not in probe


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
