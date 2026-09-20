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

    class ValidationError(Exception):
        def __init__(self, attribute=None, msg=None, message=None, **kwargs):
            super().__init__(msg or message or '')

    class PluginError(Exception):
        def __init__(self, message=None, **kwargs):
            super().__init__(message or '')

    common.exceptions.ValidationError = ValidationError
    common.exceptions.PluginError = PluginError
    common.const = types.SimpleNamespace(
        Tag=types.SimpleNamespace(
            POD_AUTO_TAG='wecube-pod-auto-tag',
            POD_AFFINITY_TAG='wecube-pod-affinity-tag',
            SERVICE_ID_TAG='wecube-service-correlation-id',
            SERVICE_ROLE_TAG='wecube-service-role',
            WORKLOAD_NAME_TAG='wecube-workload-name',
        ),
        CmdbCI=types.SimpleNamespace(
            SERVICE='k8s_service',
            NAMESPACE='k8s_namespace',
            WORKLOAD='k8s_workload',
            POD='pod',
        ),
        CmdbAttr=types.SimpleNamespace(
            SERVICE_NAMESPACE='k8s_namespace',
            SERVICE_WORKLOAD='k8s_workload',
            SERVICE_UNIT='unit',
            APP_INSTANCE='app_instance',
            HOST_RESOURCE='host_resource',
        ),
    )
    db = types.ModuleType('wecubek8s.db')
    db.resource = types.ModuleType('wecubek8s.db.resource')
    apps = types.ModuleType('wecubek8s.apps')
    plugin = types.ModuleType('wecubek8s.apps.plugin')
    sys.modules.setdefault('wecubek8s', wecubek8s)
    sys.modules.setdefault('wecubek8s.common', common)
    sys.modules.setdefault('wecubek8s.common.k8s', common.k8s)
    sys.modules.setdefault('wecubek8s.common.exceptions', common.exceptions)
    sys.modules.setdefault('wecubek8s.common.const', common.const)
    sys.modules.setdefault('wecubek8s.db', db)
    sys.modules.setdefault('wecubek8s.db.resource', db.resource)
    sys.modules.setdefault('wecubek8s.apps', apps)
    sys.modules.setdefault('wecubek8s.apps.plugin', plugin)

    utils_path = Path(__file__).resolve().parents[1] / 'wecubek8s/apps/plugin/utils.py'
    spec = importlib.util.spec_from_file_location('wecubek8s.apps.plugin.utils', utils_path)
    plugin_utils = importlib.util.module_from_spec(spec)
    sys.modules['wecubek8s.apps.plugin.utils'] = plugin_utils
    plugin.utils = plugin_utils
    spec.loader.exec_module(plugin_utils)


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


def test_deployment_reuses_statefulset_failure_checks():
    pod = _pod(
        'sample-app-instance-abcde',
        'Failed',
        reason='Evicted',
        message='The node was low on resource: ephemeral-storage.',
    )

    has_error, error_message = plugin_api.Deployment()._check_pod_failures(
        FakeK8sClient([pod]), 'sample-app-instance', 'default'
    )

    assert has_error is False
    assert error_message is None


def test_deployment_rollout_progress_requires_available_and_observed_generation():
    resource = types.SimpleNamespace(
        metadata=types.SimpleNamespace(generation=3),
        status=types.SimpleNamespace(
            ready_replicas=2,
            updated_replicas=2,
            available_replicas=2,
            observed_generation=3,
        ),
    )

    ready, updated, complete, extra = plugin_api.Deployment()._rollout_progress(resource, 2)

    assert ready == 2
    assert updated == 2
    assert complete is True
    assert 'available=2/2' in extra


def test_deployment_stuck_hash_named_pod_is_deleted_via_list():
    pod = _pod(
        'myapp-7d9f4c8b5d-xk2n9',
        'Pending',
        container_statuses=[
            _waiting_container('app', 'ImagePullBackOff', message='Back-off pulling image')
        ],
        image='registry.example/app:old-tag',
    )
    client = FakeK8sClient([pod])

    deleted = plugin_api.Deployment()._delete_stuck_pods_blocking_rollout(
        client, 'myapp', 'default', 1
    )

    assert deleted == ['myapp-7d9f4c8b5d-xk2n9']
    assert client.deleted == ['myapp-7d9f4c8b5d-xk2n9']


class FakeServiceK8sClient:
    def __init__(self, existing=None):
        self.services = dict(existing or {})
        self.created_bodies = []
        self.deleted = []

    def get_service(self, name, namespace):
        return self.services.get(name)

    def create_service(self, namespace, body):
        name = body['metadata']['name']
        svc = types.SimpleNamespace(
            metadata=types.SimpleNamespace(
                name=name,
                uid='uid-%s' % name,
                resource_version='1',
                labels=dict(body['metadata'].get('labels') or {}),
            ),
            spec=types.SimpleNamespace(
                cluster_ip='10.96.%s.1' % (body['spec']['ports'][0]['port'] % 250),
                ports=body['spec']['ports'],
                selector=body['spec'].get('selector'),
            ),
        )
        self.services[name] = svc
        self.created_bodies.append(body)
        return svc

    def update_service(self, name, namespace, body):
        return self.create_service(namespace, body)

    def list_service(self, namespace, label_selector=None):
        items = []
        for svc in self.services.values():
            labels = getattr(svc.metadata, 'labels', {}) or {}
            if label_selector:
                matched = True
                for part in label_selector.split(','):
                    key, value = part.split('=', 1)
                    if labels.get(key) != value:
                        matched = False
                        break
                if not matched:
                    continue
            items.append(svc)
        return types.SimpleNamespace(items=items)

    def delete_service(self, name, namespace):
        self.deleted.append(name)
        self.services.pop(name, None)


class FakeCmdbClient:
    def __init__(self):
        self.created = []
        self.updated = []

    def query(self, package, entity, query_data):
        attr = query_data['criteria']['attrName']
        cond = query_data['criteria']['condition']
        if entity == 'k8s_namespace':
            return {'data': [{'guid': 'ns-guid', 'code': cond}]}
        if entity == 'k8s_workload':
            return {'data': [{'guid': cond, 'unit': 'unit-guid'}]}
        if entity == 'k8s_service':
            return {'data': []}
        return {'data': []}

    def create(self, package, entity, data):
        self.created.append((entity, data))
        return {'data': data}

    def update(self, package, entity, data):
        self.updated.append((entity, data))
        return {'data': data}


def test_image_port_comma_splits_into_service_ports():
    ports = plugin_api.api_utils.resolve_workload_service_ports({
        'image_port': '8080,9090'
    })
    assert [p['port'] for p in ports] == [8080, 9090]
    assert all(p['protocol'] == 'TCP' for p in ports)


def test_ensure_port_services_creates_one_clusterip_per_port():
    client = FakeServiceK8sClient()
    data = {
        'name': 'repayment',
        'namespace': 'adm-loan',
        'correlation_id': 'k8s_workload_1',
        'image_port': '8080,9090',
    }
    results = plugin_api.Deployment()._ensure_port_services(
        client, data, 'repayment', {'id': 'cluster-1'}
    )

    names = sorted(r['name'] for r in results)
    assert names == ['repayment-8080', 'repayment-9090']
    assert all(len(body['spec']['ports']) == 1 for body in client.created_bodies)
    assert {body['spec']['ports'][0]['port'] for body in client.created_bodies} == {8080, 9090}
    assert all(body['spec']['type'] == 'ClusterIP' for body in client.created_bodies)
    assert all(body['spec']['selector']['wecube-pod-auto-tag'] == 'repayment'
               for body in client.created_bodies)


def test_ensure_port_services_deletes_legacy_lb_but_keeps_sts_headless():
    headless = types.SimpleNamespace(
        metadata=types.SimpleNamespace(name='repayment', uid='uid-headless',
                                       resource_version='1', labels={}),
        spec=types.SimpleNamespace(cluster_ip='None', ports=[]),
    )
    legacy_lb = types.SimpleNamespace(
        metadata=types.SimpleNamespace(name='repayment-lb', uid='uid-lb',
                                       resource_version='1', labels={}),
        spec=types.SimpleNamespace(cluster_ip='10.96.1.1', ports=[]),
    )
    client = FakeServiceK8sClient({'repayment': headless, 'repayment-lb': legacy_lb})
    data = {
        'name': 'repayment',
        'namespace': 'adm-loan',
        'correlation_id': 'k8s_workload_1',
        'image_port': '8080',
    }

    plugin_api.StatefulSet()._ensure_port_services(
        client, data, 'repayment', {'id': 'cluster-1'}, keep_names=['repayment']
    )

    assert 'repayment-lb' in client.deleted
    assert 'repayment' not in client.deleted
    assert 'repayment-8080' in client.services


def test_sync_services_to_cmdb_writes_one_row_per_port_not_ingress():
    fake_cmdb = FakeCmdbClient()
    api = plugin_api.Deployment()
    api._cmdb_entity_client = lambda: fake_cmdb
    service_list = [
        {
            'name': 'repayment-8080',
            'port': 8080,
            'cluster_ip': '10.96.8.1',
            'asset_id': 'cluster-1_uid-8080',
            'service_type': 'ClusterIP',
            'cluster_ip_mode': 'AUTO',
        },
        {
            'name': 'repayment-9090',
            'port': 9090,
            'cluster_ip': '10.96.9.1',
            'asset_id': 'cluster-1_uid-9090',
            'service_type': 'ClusterIP',
            'cluster_ip_mode': 'AUTO',
        },
    ]
    api._sync_services_to_cmdb(
        service_list,
        {'namespace': 'adm-loan'},
        'k8s_workload_1',
    )

    assert len(fake_cmdb.created) == 1
    entity, rows = fake_cmdb.created[0]
    assert entity == 'k8s_service'
    assert [row['code'] for row in rows] == ['repayment-8080', 'repayment-9090']
    assert [row['port'] for row in rows] == ['8080', '9090']
    for row in rows:
        assert row['service_type'] == 'ClusterIP'
        assert row['cluster_ip_mode'] == 'AUTO'
        assert row['k8s_namespace'] == 'ns-guid'
        assert row['k8s_workload'] == 'k8s_workload_1'
        assert row['unit'] == 'unit-guid'
        assert 'ingress' not in row
    assert not any(entity == 'k8s_ingress' for entity, _ in fake_cmdb.created)
