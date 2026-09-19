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
        self._pods = {pod.metadata.name: pod for pod in pods}
        self.deleted = []

    def list_pod(self, namespace, label_selector=None):
        return types.SimpleNamespace(items=list(self._pods.values()))

    def get_pod(self, name, namespace):
        return self._pods.get(name)

    def delete_pod(self, name, namespace):
        self.deleted.append(name)
        self._pods.pop(name, None)


def _pod(name, phase, reason=None, message=None, container_statuses=None,
         image=None, deletion_timestamp=None, ready=None, init_package_url=None):
    containers = []
    if image:
        containers.append(types.SimpleNamespace(image=image))
    init_containers = []
    if init_package_url:
        init_containers.append(types.SimpleNamespace(
            name='package-downloader',
            env=[types.SimpleNamespace(name='PACKAGE_URL', value=init_package_url)],
        ))
    conditions = []
    if ready is True:
        conditions = [types.SimpleNamespace(type='Ready', status='True')]
    elif ready is False:
        conditions = [types.SimpleNamespace(type='Ready', status='False')]
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(name=name, deletion_timestamp=deletion_timestamp),
        spec=types.SimpleNamespace(containers=containers, init_containers=init_containers),
        status=types.SimpleNamespace(
            phase=phase,
            reason=reason,
            message=message,
            conditions=conditions,
            container_statuses=container_statuses or [],
            init_container_statuses=[],
        ),
    )


def _waiting_container(name, reason, message='', restart_count=0):
    return types.SimpleNamespace(
        name=name,
        restart_count=restart_count,
        state=types.SimpleNamespace(
            waiting=types.SimpleNamespace(reason=reason, message=message),
            running=None,
            terminated=None,
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


def _running_container(name, ready=False, restart_count=0):
    return types.SimpleNamespace(
        name=name,
        ready=ready,
        restart_count=restart_count,
        state=types.SimpleNamespace(
            waiting=None,
            running=types.SimpleNamespace(started_at='2026-09-19T12:00:00Z'),
            terminated=None,
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


def test_image_pull_backoff_pod_is_deleted_to_unblock_rollout():
    pod = _pod(
        'onboarding-0',
        'Pending',
        container_statuses=[
            _waiting_container(
                'ials-onboarding',
                'ImagePullBackOff',
                message='Back-off pulling image "old-tag"',
            )
        ],
        image='registry.example/app:old-tag',
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'onboarding', 'adm-loan', 1
    )

    assert deleted == ['onboarding-0']
    assert client.deleted == ['onboarding-0']


def test_crashloop_pod_is_still_deleted_to_unblock_rollout():
    pod = _pod(
        'repayment-h5-0',
        'Running',
        container_statuses=[
            _waiting_container('ials-repaymenth5', 'CrashLoopBackOff', restart_count=5)
        ],
        image='registry.example/app:same-tag',
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'repayment-h5', 'adm-loan', 1
    )

    assert deleted == ['repayment-h5-0']


def test_running_pod_is_not_deleted_during_rollout_check():
    pod = _pod('onboarding-0', 'Running', image='registry.example/app:new-tag')
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'onboarding', 'adm-loan', 1
    )

    assert deleted == []
    assert client.deleted == []


def test_not_ready_old_image_is_deleted_to_unblock_rollout():
    pod = _pod(
        'gateway-sf-0',
        'Running',
        container_statuses=[_running_container('ials-gatewaysf', ready=False, restart_count=320)],
        image='registry.example/app:old-tag',
        ready=False,
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'gateway-sf', 'adm-loan', 1,
        desired_images={'registry.example/app:new-tag'},
    )

    assert deleted == ['gateway-sf-0']
    assert client.deleted == ['gateway-sf-0']


def test_not_ready_new_image_is_not_deleted():
    pod = _pod(
        'gateway-sf-0',
        'Running',
        container_statuses=[_running_container('ials-gatewaysf', ready=False)],
        image='registry.example/app:new-tag',
        ready=False,
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'gateway-sf', 'adm-loan', 1,
        desired_images={'registry.example/app:new-tag'},
    )

    assert deleted == []
    assert client.deleted == []


def test_ready_old_image_is_not_deleted():
    pod = _pod(
        'onboarding-0',
        'Running',
        container_statuses=[_running_container('ials-onboarding', ready=True)],
        image='registry.example/app:old-tag',
        ready=True,
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'onboarding', 'adm-loan', 1,
        desired_images={'registry.example/app:new-tag'},
    )

    assert deleted == []
    assert client.deleted == []


def test_not_ready_old_package_url_is_deleted_to_unblock_rollout():
    pod = _pod(
        'gateway-sf-0',
        'Running',
        container_statuses=[_running_container('ials-gatewaysf', ready=False, restart_count=10)],
        image='registry.example/app:same-tag',
        ready=False,
        init_package_url='http://minio/old-conf.tar.gz',
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'gateway-sf', 'adm-loan', 1,
        desired_images={'registry.example/app:same-tag'},
        desired_package_urls={'http://minio/new-conf.tar.gz'},
    )

    assert deleted == ['gateway-sf-0']
    assert client.deleted == ['gateway-sf-0']


def test_stale_image_pull_error_is_not_fatal_for_new_apply():
    pod = _pod(
        'onboarding-0',
        'Pending',
        container_statuses=[
            _waiting_container(
                'ials-onboarding',
                'ImagePullBackOff',
                message='Back-off pulling image "old-tag"',
            )
        ],
        image='registry.example/app:old-tag',
    )

    has_error, error_message = plugin_api.StatefulSet()._check_pod_failures(
        FakeK8sClient([pod]),
        'onboarding',
        'adm-loan',
        desired_images={'registry.example/app:new-tag'},
    )

    assert has_error is False
    assert error_message is None


def test_current_image_pull_error_is_still_fatal():
    pod = _pod(
        'onboarding-0',
        'Pending',
        container_statuses=[
            _waiting_container(
                'ials-onboarding',
                'ImagePullBackOff',
                message='Back-off pulling image "new-tag"',
            )
        ],
        image='registry.example/app:new-tag',
    )

    has_error, error_message = plugin_api.StatefulSet()._check_pod_failures(
        FakeK8sClient([pod]),
        'onboarding',
        'adm-loan',
        desired_images={'registry.example/app:new-tag'},
    )

    assert has_error is True
    assert 'ImagePullBackOff' in error_message
    assert 'new-tag' in error_message


def test_terminating_pod_is_not_fatal_and_not_deleted():
    pod = _pod(
        'onboarding-0',
        'Pending',
        container_statuses=[
            _waiting_container('ials-onboarding', 'ImagePullBackOff')
        ],
        image='registry.example/app:old-tag',
        deletion_timestamp='2026-09-18T08:00:00Z',
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.StatefulSet()._delete_stuck_pods_blocking_rollout(
        client, 'onboarding', 'adm-loan', 1
    )
    has_error, error_message = plugin_api.StatefulSet()._check_pod_failures(
        client, 'onboarding', 'adm-loan'
    )

    assert deleted == []
    assert has_error is False
    assert error_message is None
