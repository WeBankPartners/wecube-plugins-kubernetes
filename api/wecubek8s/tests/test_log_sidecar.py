from copy import deepcopy
import sys
from types import SimpleNamespace

import pytest

from test_statefulset_pod_failures import plugin_api


sidecar = plugin_api.log_sidecar
EXPORTER_IMAGE = 'registry.example.test/monitor/node-exporter:1.0'


class WorkloadClient:
    def __init__(self):
        self.workload = None
        self.services = []
        self.secrets = {}

    def ensure_namespace(self, namespace):
        pass

    def get_deployment(self, name, namespace):
        return self.workload

    get_statefulset = get_deployment

    def create_deployment(self, namespace, body):
        self.body = deepcopy(body)
        spec = self.body['spec']
        self.workload = SimpleNamespace(
            metadata=SimpleNamespace(uid='workload-uid', resource_version='3', name=body['metadata']['name'],
                                     annotations=body['metadata']['annotations']),
            spec=SimpleNamespace(
                template=SimpleNamespace(metadata=SimpleNamespace(**spec['template']['metadata']),
                                         spec=spec['template']['spec']),
                selector=SimpleNamespace(match_labels=spec['selector']['matchLabels']),
                service_name=spec.get('serviceName'), pod_management_policy='OrderedReady',
                volume_claim_templates=spec.get('volumeClaimTemplates'),
            ),
        )
        return self.workload

    create_statefulset = create_deployment

    def replace_deployment(self, name, namespace, body):
        assert body['metadata']['resourceVersion'] == self.workload.metadata.resource_version
        return self.create_deployment(namespace, body)

    replace_statefulset = replace_deployment

    def get_service(self, name, namespace):
        return None

    def create_service(self, namespace, body):
        self.services.append(deepcopy(body))

    def get_secret(self, name, namespace):
        return self.secrets.get((namespace, name))

    def ensure_registry_secret(self, name, namespace, registry, username, password):
        self.secrets[namespace, name] = SimpleNamespace(type='kubernetes.io/dockerconfigjson')


@pytest.fixture(params=[plugin_api.Deployment, plugin_api.StatefulSet])
def apply(request, monkeypatch):
    workload = request.param()
    client = WorkloadClient()
    cluster = {'api_server': 'https://cluster.example.test', 'token': 'test-token', 'private_registry': ''}
    monkeypatch.setattr(plugin_api.db_resource, 'Cluster',
                        lambda: SimpleNamespace(list=lambda filters: [cluster]), raising=False)
    monkeypatch.setattr(plugin_api.k8s, 'AuthToken', lambda *args: None, raising=False)
    monkeypatch.setattr(plugin_api.k8s, 'Client', lambda auth: client, raising=False)
    monkeypatch.setattr(plugin_api.k8s_utils, 'get_token', lambda: None)
    monkeypatch.setattr(plugin_api.CONF, 'log_sidecar_image', EXPORTER_IMAGE, raising=False)
    monkeypatch.setattr(plugin_api.CONF, 'log_sidecar_image_pull_secret', '', raising=False)
    monkeypatch.setattr(plugin_api.CONF, 'enable_host_path', 'false', raising=False)
    monkeypatch.setattr(workload, '_delete_stuck_pods_blocking_rollout', lambda *args, **kwargs: None)
    monkeypatch.setattr(workload, '_ensure_port_services', lambda *args, **kwargs: [])
    monkeypatch.setattr(workload, '_sync_services_to_cmdb', lambda *args: None)
    monkeypatch.setattr(workload, '_collect_sync_and_mark_pods', lambda *args, **kwargs: ([], ''))
    kubernetes = SimpleNamespace(client=SimpleNamespace(ApiClient=lambda: SimpleNamespace(
        sanitize_for_serialization=deepcopy)))
    monkeypatch.setitem(sys.modules, 'kubernetes', kubernetes)
    data = {
        'cluster': 'test', 'namespace': 'test', 'name': 'sample-app',
        'correlation_id': 'Deployment_ci.1', 'image_name': 'sample-app:1.0', 'image_port': '8080',
        'replicas': '1', 'affinity': '', 'wait_for_ready': 'false',
        'packageUrl': 'https://packages.example.test/config.tar.gz',
    }

    def apply_with(**parameters):
        workload.apply(dict(data, **parameters))
        return deepcopy(client.body['spec']['template'])

    return apply_with, client, workload


def test_sidecar_lifecycle_leaves_selector_and_package_unchanged(apply):
    apply_with, client, _ = apply
    original = apply_with()
    selector = deepcopy(client.body['spec']['selector'])
    assert [item['name'] for item in original['spec']['containers']] == ['sample-app']

    enabled = apply_with(enable_log_sidecar='true')
    assert enabled == apply_with() == apply_with(enable_log_sidecar=True)
    assert client.body['spec']['selector'] == selector
    for service in client.services:
        assert sidecar.DISCOVERY_LABEL not in service['spec']['selector']
        assert service['spec']['ports'][0]['port'] != 9100
    assert enabled['metadata']['labels'][sidecar.DISCOVERY_LABEL] == 'enabled'
    assert enabled['metadata']['annotations'][sidecar.WORKLOAD_ID_ANNOTATION] == 'Deployment_ci.1'
    assert enabled['spec']['initContainers'] == original['spec']['initContainers']
    app, exporter = enabled['spec']['containers']
    assert app['readinessProbe'] == original['spec']['containers'][0]['readinessProbe']
    assert exporter['image'] == EXPORTER_IMAGE
    assert exporter['ports'] == [{'name': 'log-metrics', 'containerPort': 9100, 'protocol': 'TCP'}]
    assert exporter['volumeMounts'][0] == {'name': sidecar.SHARED_VOLUME_NAME, 'mountPath': '/logs', 'readOnly': True}
    assert exporter['volumeMounts'][1] == {'name': sidecar.CACHE_VOLUME_NAME, 'mountPath': '/app/monitor/data'}
    assert {'name': sidecar.SHARED_VOLUME_NAME, 'emptyDir': {}} in enabled['spec']['volumes']
    assert len(enabled['spec']['volumes']) == 3

    disabled = apply_with(enable_log_sidecar=False)
    assert disabled == apply_with() == apply_with(enable_log_sidecar=False)
    assert disabled['metadata'] == original['metadata']
    assert disabled['spec']['containers'] == [app]
    assert len(disabled['spec']['volumes']) == 2
    assert {'name': sidecar.SHARED_VOLUME_NAME, 'emptyDir': {}} in disabled['spec']['volumes']


def test_reuses_writable_parent_mount_and_keeps_subpath_expression(apply, monkeypatch):
    apply_with, _, _ = apply
    monkeypatch.setattr(plugin_api.CONF, 'enable_host_path', 'true')
    volumes = [{'name': 'app-logs', 'type': 'persistentVolumeClaim', 'mountPath': '/data',
                'typeSpec': {'name': 'app-claim'}, 'subPathExpr': '$(POD_NAME)'}]
    pod = apply_with(enable_log_sidecar=True, volumes=volumes, log_path='/data/logs', deployment_path='/legacy')
    app, exporter = pod['spec']['containers']
    assert app['volumeMounts'][0]['subPathExpr'] == '$(POD_NAME)'
    assert exporter['volumeMounts'][0] == {'name': 'app-logs', 'mountPath': '/data/logs', 'readOnly': True,
                                           'subPathExpr': '$(POD_NAME)/logs'}
    assert [item['name'] for item in exporter['env']] == ['POD_NAME']
    assert not any('hostPath' in item for item in pod['spec']['volumes'])


def test_reuses_legacy_hostpath(apply, monkeypatch):
    apply_with, _, _ = apply
    monkeypatch.setattr(plugin_api.CONF, 'enable_host_path', 'true')
    apply_with(deployment_path='/legacy')
    pod = apply_with(enable_log_sidecar=True)
    assert {'name': 'instance-logs', 'hostPath': {'path': '/legacy/logs', 'type': 'DirectoryOrCreate'}} in pod['spec']['volumes']
    assert pod['spec']['containers'][1]['volumeMounts'][0]['name'] == 'instance-logs'
    assert pod == apply_with(enable_log_sidecar=True)


@pytest.mark.parametrize('apply', [plugin_api.StatefulSet], indirect=True)
def test_statefulset_applies_sidecar_after_pvc_reconciliation(apply):
    apply_with, client, _ = apply
    old_pvc = {'metadata': {'name': 'old-logs'}, 'spec': {}}
    new_pvc = {'metadata': {'name': 'new-logs'}, 'spec': {}}
    apply_with(volumeClaimTemplates=[old_pvc], volumeClaimMounts=[{'name': 'old-logs', 'mountPath': '/logs'}])
    pod = apply_with(enable_log_sidecar=True, volumeClaimTemplates=[new_pvc],
                     volumeClaimMounts=[{'name': 'new-logs', 'mountPath': '/logs'}])
    assert client.body['spec']['volumeClaimTemplates'] == [old_pvc]
    assert pod['spec']['containers'][1]['volumeMounts'][0]['name'] == 'old-logs'
    assert [m['name'] for m in pod['spec']['containers'][0]['volumeMounts']] == ['package-shared-volume', 'old-logs']


@pytest.mark.parametrize('parameters, message', [
    ({'image_port': '9100'}, '9100/TCP'),
    ({'image_name': 'log-exporter:1.0'}, 'container name already in use'),
    ({'volumes': [{'name': sidecar.CACHE_VOLUME_NAME, 'type': 'emptyDir', 'mountPath': '/other'}]},
     sidecar.CACHE_VOLUME_NAME),
    ({'volumes': [{'name': 'read-only', 'type': 'emptyDir', 'mountPath': '/logs', 'readOnly': True}]}, 'read-only'),
    ({'volumes': [{'name': 'nested', 'type': 'emptyDir', 'mountPath': '/logs/nested'}]}, 'nested'),
])
def test_invalid_sidecar_configuration_is_rejected_before_workload_write(apply, parameters, message):
    apply_with, client, _ = apply
    with pytest.raises(plugin_api.exceptions.ValidationError, match=message):
        apply_with(enable_log_sidecar=True, **parameters)
    assert client.workload is None
    assert not client.services


def test_private_sidecar_registry_secret(apply, monkeypatch):
    apply_with, client, _ = apply
    monkeypatch.setattr(plugin_api.CONF, 'log_sidecar_image_pull_secret', 'exporter-auth')
    with pytest.raises(plugin_api.exceptions.ValidationError, match='missing or invalid in namespace test'):
        apply_with(enable_log_sidecar=True)
    client.secrets['test', 'exporter-auth'] = SimpleNamespace(type='kubernetes.io/dockerconfigjson')
    first = apply_with(enable_log_sidecar=True)
    assert first['spec']['imagePullSecrets'] == [{'name': 'exporter-auth'}]
    assert first == apply_with(enable_log_sidecar=True)
    assert 'imagePullSecrets' not in apply_with(enable_log_sidecar=False)['spec']


def test_sidecar_preserves_existing_registry_secrets(apply, monkeypatch):
    apply_with, _, _ = apply
    cluster = plugin_api.db_resource.Cluster().list({})[0]
    cluster.update(image_pull_username='test-user', image_pull_password='test-password')
    image_name = 'registry.example.test/samples/sample-app:1.0'
    baseline = apply_with(image_name=image_name)['spec']['imagePullSecrets']
    monkeypatch.setattr(plugin_api.CONF, 'log_sidecar_image_pull_secret', baseline[0]['name'])
    enabled = apply_with(image_name=image_name, enable_log_sidecar=True)['spec']
    assert enabled['imagePullSecrets'] == baseline
    assert apply_with(image_name=image_name, enable_log_sidecar=False)['spec']['imagePullSecrets'] == baseline


@pytest.mark.parametrize('value, expected', [(False, False), (' False ', False), ('TRUE', True), ('', None), (None, None)])
def test_parse_enabled(value, expected):
    assert sidecar.parse_enabled(value) is expected


def test_parse_enabled_rejects_invalid_values():
    with pytest.raises(plugin_api.exceptions.ValidationError, match='expected true or false'):
        sidecar.parse_enabled('yes')
