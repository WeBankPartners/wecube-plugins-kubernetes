# coding=utf-8

import importlib.util
import sys
import types
from pathlib import Path


def _install_import_stubs():
    talos = types.ModuleType('talos')
    talos_core = types.ModuleType('talos.core')
    talos_config = types.ModuleType('talos.core.config')
    talos_config.CONF = types.SimpleNamespace()
    talos_i18n = types.ModuleType('talos.core.i18n')
    talos_i18n._ = lambda value: value
    sys.modules.setdefault('talos', talos)
    sys.modules.setdefault('talos.core', talos_core)
    sys.modules.setdefault('talos.core.config', talos_config)
    sys.modules.setdefault('talos.core.i18n', talos_i18n)

    wecubek8s = types.ModuleType('wecubek8s')
    common = types.ModuleType('wecubek8s.common')
    common.k8s = types.ModuleType('wecubek8s.common.k8s')
    common.exceptions = types.ModuleType('wecubek8s.common.exceptions')
    common.const = types.SimpleNamespace(
        Tag=types.SimpleNamespace(POD_AUTO_TAG='pod_auto_tag')
    )
    db = types.ModuleType('wecubek8s.db')
    db.resource = types.ModuleType('wecubek8s.db.resource')
    apps = types.ModuleType('wecubek8s.apps')
    plugin = types.ModuleType('wecubek8s.apps.plugin')
    plugin_utils = types.ModuleType('wecubek8s.apps.plugin.utils')
    sys.modules.setdefault('wecubek8s', wecubek8s)
    sys.modules.setdefault('wecubek8s.common', common)
    sys.modules.setdefault('wecubek8s.common.k8s', common.k8s)
    sys.modules.setdefault('wecubek8s.common.exceptions', common.exceptions)
    sys.modules.setdefault('wecubek8s.common.const', common.const)
    sys.modules.setdefault('wecubek8s.db', db)
    sys.modules.setdefault('wecubek8s.db.resource', db.resource)
    sys.modules.setdefault('wecubek8s.apps', apps)
    sys.modules.setdefault('wecubek8s.apps.plugin', plugin)
    sys.modules.setdefault('wecubek8s.apps.plugin.utils', plugin_utils)


def _load_plugin_api():
    _install_import_stubs()
    api_path = (
        Path(__file__).resolve().parents[1]
        / 'wecubek8s/apps/plugin/api.py'
    )
    spec = importlib.util.spec_from_file_location('plugin_api_under_test', api_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin_api = _load_plugin_api()


class FakeK8sClient:
    def __init__(self, pods):
        self._pods = pods

    def list_pod(self, namespace, label_selector=None):
        return types.SimpleNamespace(items=self._pods)


def _pod(name, phase, reason=None, message=None, container_statuses=None):
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(name=name),
        status=types.SimpleNamespace(
            phase=phase,
            reason=reason,
            message=message,
            container_statuses=container_statuses or [],
            init_container_statuses=[],
        ),
    )


def _terminated_container(name, reason, exit_code, message=None, restart_count=0):
    return types.SimpleNamespace(
        name=name,
        restart_count=restart_count,
        state=types.SimpleNamespace(
            waiting=None,
            running=None,
            terminated=types.SimpleNamespace(
                reason=reason,
                exit_code=exit_code,
                message=message,
            ),
        ),
    )


def test_evicted_failed_pod_is_not_immediate_fatal_error():
    pod = _pod(
        'sample-app-instance-0',
        'Failed',
        reason='Evicted',
        message='The node was low on resource: ephemeral-storage.',
    )

    has_error, error_message = plugin_api.StatefulSet()._check_pod_failures(
        FakeK8sClient([pod]), 'sample-app-instance', 'default'
    )

    assert has_error is False
    assert error_message is None


def test_non_recoverable_failed_pod_error_contains_status_and_container_detail():
    pod = _pod(
        'sample-app-instance-0',
        'Failed',
        reason='Error',
        message='Pod failed',
        container_statuses=[
            _terminated_container(
                'app', reason='Error', exit_code=2, message='startup failed'
            )
        ],
    )

    has_error, error_message = plugin_api.StatefulSet()._check_pod_failures(
        FakeK8sClient([pod]), 'sample-app-instance', 'default'
    )

    assert has_error is True
    assert 'phase=Failed' in error_message
    assert 'reason=Error' in error_message
    assert 'message=Pod failed' in error_message
    assert 'app: terminated - Error (exit 2)' in error_message


def test_pod_ready_timeout_uses_system_parameter_default_when_request_missing():
    plugin_api.CONF.pod_ready_timeout = '600'

    timeout = plugin_api.StatefulSet()._get_pod_ready_timeout({})

    assert timeout == 600


def test_pod_ready_timeout_request_overrides_system_parameter():
    plugin_api.CONF.pod_ready_timeout = '600'

    timeout = plugin_api.StatefulSet()._get_pod_ready_timeout({
        'pod_ready_timeout': '120',
    })

    assert timeout == 120
