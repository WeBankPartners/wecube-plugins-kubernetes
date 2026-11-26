# coding=utf-8

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


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
    api_path = (
        Path(__file__).resolve().parents[1]
        / 'wecubek8s/apps/plugin/api.py'
    )
    spec = importlib.util.spec_from_file_location('plugin_api_under_test', api_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules):
        _install_import_stubs()
        spec.loader.exec_module(module)
    module.CONF = types.SimpleNamespace()
    return module


plugin_api = _load_plugin_api()


class FakeK8sClient:
    def __init__(self, pods):
        self._pods = pods

    def list_pod(self, namespace, label_selector=None):
        return types.SimpleNamespace(items=self._pods)


def _pod(name, phase, reason=None, message=None, container_statuses=None,
         deletion_timestamp=None, conditions=None):
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(name=name, deletion_timestamp=deletion_timestamp),
        status=types.SimpleNamespace(
            phase=phase,
            reason=reason,
            message=message,
            container_statuses=container_statuses or [],
            init_container_statuses=[],
            conditions=conditions or [],
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


def test_terminating_pod_killed_during_rollout_does_not_fail_startup_check():
    old_pod = _pod(
        'sample-app-instance-0', 'Failed',
        deletion_timestamp='2026-11-26T00:00:00Z',
        container_statuses=[_terminated_container('app', 'Error', 137)],
    )
    new_pod = _pod('sample-app-instance-0', 'Running')
    workload = plugin_api.StatefulSet()

    for pod in (old_pod, new_pod):
        assert workload._check_pod_failures(
            FakeK8sClient([pod]), 'sample-app-instance', 'default',
        ) == (False, None)


def test_failed_pod_without_deletion_timestamp_is_fatal_even_with_exit_137():
    pod = _pod(
        'sample-app-instance-0', 'Failed',
        container_statuses=[_terminated_container('app', 'Error', 137)],
    )

    has_error, details = plugin_api.StatefulSet()._check_pod_failures(
        FakeK8sClient([pod]), 'sample-app-instance', 'default',
    )

    assert has_error
    assert 'exit 137' in details


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


@pytest.mark.parametrize(('startup_seconds', 'should_succeed'), [(25, True), (30, False)])
def test_statefulset_rollout_excludes_old_shutdown_from_shared_ready_budget(
    startup_seconds, should_succeed, monkeypatch,
):
    current_time = 0

    def sleep(seconds):
        nonlocal current_time
        current_time += seconds

    def rollout_pod(ordinal, version, ready=False, deletion=None, grace=120):
        pod = _pod(f'app-{ordinal}', 'Running', deletion_timestamp=deletion,
                   conditions=[types.SimpleNamespace(type='Ready', status='True')] if ready else [])
        pod.metadata.uid = f'{ordinal}-{version}'
        pod.metadata.labels = {'controller-revision-hash': version}
        pod.metadata.owner_references = [types.SimpleNamespace(controller=True, uid='workload')]
        pod.metadata.creation_timestamp = datetime.fromtimestamp(1000 + current_time, timezone.utc)
        pod.metadata.deletion_grace_period_seconds = grace if deletion else None
        pod.spec = types.SimpleNamespace(termination_grace_period_seconds=grace)
        return pod

    def list_pods(namespace, **kwargs):
        if current_time < 15:
            deadline = datetime.fromtimestamp(1120, timezone.utc)
            items = [rollout_pod(0, 'old', deletion=deadline), rollout_pod(1, 'old', ready=True)]
        elif current_time < 25:
            items = [rollout_pod(0, 'new'), rollout_pod(1, 'old', ready=True)]
        elif current_time < 35:
            deadline = datetime.fromtimestamp(1055, timezone.utc)
            items = [rollout_pod(0, 'new', ready=True), rollout_pod(1, 'old', deletion=deadline, grace=30)]
        else:
            items = [rollout_pod(0, 'new', ready=True), rollout_pod(1, 'new', ready=current_time >= 35 + startup_seconds)]
        return types.SimpleNamespace(items=items)

    def get_statefulset(name, namespace, **kwargs):
        ready = current_time >= 35 + startup_seconds
        status = types.SimpleNamespace(observed_generation=2, current_revision='new' if ready else 'old',
                                       update_revision='new', ready_replicas=2 if ready else 1,
                                       updated_replicas=2 if current_time >= 35 else 1, replicas=2)
        return types.SimpleNamespace(metadata=metadata, status=status)

    metadata = types.SimpleNamespace(name='app', uid='workload', generation=2)
    clock = types.SimpleNamespace(monotonic=lambda: current_time, time=lambda: 1000 + current_time, sleep=sleep)
    client = types.SimpleNamespace(list_pod=list_pods, get_statefulset=get_statefulset)
    class PluginError(RuntimeError):
        def __init__(self, message):
            super().__init__(message)

    monkeypatch.setattr(plugin_api, 'time', clock)
    monkeypatch.setattr(plugin_api.exceptions, 'PluginError', PluginError, raising=False)
    workload = plugin_api.StatefulSet()
    monkeypatch.setattr(workload, '_get_pod_logs_summary', lambda *args: '')

    if should_succeed:
        pods = workload._wait_for_rollout(client, 'default', metadata, 2, 35, True)
        assert [pod.metadata.uid for pod in pods] == ['0-new', '1-new']
    else:
        with pytest.raises(RuntimeError, match='35s'):
            workload._wait_for_rollout(client, 'default', metadata, 2, 35, True)
    assert current_time == 60
