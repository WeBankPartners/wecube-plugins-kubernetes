import sys
from datetime import datetime, timezone
from types import SimpleNamespace as Object
from unittest.mock import Mock

import pytest

from wecubek8s.apps.plugin import api, controller
from wecubek8s.common import exceptions, k8s, utils
from kubernetes.client.exceptions import ApiException


@pytest.mark.parametrize(('rolling', 'last_ready_at', 'expected_elapsed', 'post_ready_change'), [
    (False, 45, 45, None),
    (False, None, 45, None),
    (True, 80, 80, None),
    (True, None, 80, None),
    (True, 80, 80, 'pod-replaced'),
    (True, 80, 80, 'rollout-superseded'),
    (True, 80, 80, 'old-crash-loop'),
])
def test_apply_waits_for_all_target_pods_before_sync(
    rolling, last_ready_at, expected_elapsed, post_ready_change, monkeypatch,
):
    now = 0

    def sleep(seconds):
        nonlocal now
        now += seconds

    def stamp(seconds):
        return datetime.fromtimestamp(1000 + seconds, timezone.utc)

    name = 'sample-app'
    loadbalancer_ensured = False
    clock = Object(monotonic=lambda: now, time=lambda: 1000 + now, sleep=sleep)
    old_generation = 1
    generation = 2 if rolling else 1
    spec = Object(volume_claim_templates=None, selector=None, service_name=name,
                  pod_management_policy=None, ordinals=None)

    def workload(gen, observed, ready=False):
        return Object(metadata=Object(name=name, uid='workload', generation=gen, resource_version='9'),
                      spec=spec, status=Object(observed_generation=observed, replicas=2,
                                               ready_replicas=2 if ready else 1,
                                               current_revision='new' if ready or not rolling else 'old',
                                               update_revision='new', updated_replicas=2 if ready else 1))

    def make_pod(ordinal, version, created, ready, deletion=None, grace=None):
        return Object(metadata=Object(name=f'{name}-{ordinal}', uid=f'{version}-{ordinal}',
                                     resource_version=f'{version}-resource-version',
                                     labels={'controller-revision-hash': version},
                                     owner_references=[Object(uid='workload', controller=True)],
                                     creation_timestamp=stamp(created),
                                     deletion_timestamp=stamp(deletion) if deletion is not None else None,
                                     deletion_grace_period_seconds=grace),
                      spec=Object(termination_grace_period_seconds=grace),
                      status=Object(phase='Failed' if deletion and now >= 30 else 'Running',
                                    init_container_statuses=[], container_statuses=[], host_ip='node-address',
                                    conditions=[Object(type='Ready', status='True')] if ready else []))

    def list_pods(namespace, **kwargs):
        last_ready = last_ready_at is not None and now >= last_ready_at
        if rolling and now < 30:
            pods = [make_pod(0, 'old', -20, True), make_pod(1, 'old', -20, False, 30, 30)]
        elif rolling and now <= 35:
            pods = [make_pod(0, 'old', -20, False, 150, 120), make_pod(1, 'new', 30, True)]
        elif rolling:
            pods = [make_pod(0, 'new', 35, last_ready), make_pod(1, 'new', 30, True)]
        elif now < 20:
            pods = []
        else:
            pods = [make_pod(0, 'new', 20, True), make_pod(1, 'new', 20, last_ready)]
        if post_ready_change == 'pod-replaced' and loadbalancer_ensured:
            pods[0].metadata.uid = 'newer-uid'
        if post_ready_change == 'old-crash-loop' and not sent:
            pods[0].status.container_statuses = [Object(state=Object(waiting=Object(reason='CrashLoopBackOff')))]
        return Object(items=pods)

    client = Mock()
    existing = workload(old_generation, old_generation) if rolling else None
    sent = False

    def write(*args):
        nonlocal sent
        sent = True
        manifest = args[-1]
        pod_spec = manifest['spec']['template']['spec']
        assert pod_spec['terminationGracePeriodSeconds'] == 180
        assert pod_spec['containers'][0]['startupProbe']['failureThreshold'] == 48
        assert pod_spec['containers'][0]['imagePullPolicy'] == 'IfNotPresent'
        return workload(generation, generation)

    def get_statefulset(*args, **kwargs):
        if not sent:
            return existing
        if post_ready_change == 'rollout-superseded' and loadbalancer_ensured:
            return workload(generation + 1, generation + 1)
        return workload(generation, generation, last_ready_at is not None and now >= last_ready_at)

    client.get_statefulset.side_effect = get_statefulset
    client.create_statefulset.side_effect = write
    client.replace_statefulset.side_effect = write
    client.list_pod.side_effect = list_pods
    client.get_pod.return_value = None
    client.get_service.return_value = None
    client.get_pod_log.return_value = None
    cluster = {'name': 'sample-cluster', 'id': 'cluster-id',
               'api_server': 'https://cluster.example.invalid', 'token': ''}
    monkeypatch.setattr(api.db_resource, 'Cluster', lambda: Object(list=lambda query: [cluster]))
    monkeypatch.setattr(api.k8s, 'Client', lambda auth: client)
    monkeypatch.setattr(api, 'time', clock)
    monkeypatch.setattr(api, 'CONF', Object(pod_ready_timeout='45', pod_termination_grace_period_seconds='180'))
    monkeypatch.setattr(utils, 'get_token', lambda: None)
    monkeypatch.setitem(sys.modules, 'wecubek8s.server.watcher', Object(mark_expected_pods=Mock()))
    sync = Mock()
    monkeypatch.setattr(api.StatefulSet, '_sync_pods_to_cmdb', sync)

    def ensure_service(*args):
        nonlocal loadbalancer_ensured
        loadbalancer_ensured = True
        return 'sample-service'

    monkeypatch.setattr(api.StatefulSet, '_ensure_loadbalancer_service', ensure_service)

    handler = controller.StatefulSet()
    data = handler.validate_item_apply(0, {
        'cluster': 'sample-cluster', 'name': name, 'correlation_id': 'sample-instance',
        'image_name': 'sample-app:release', 'image_port': '8080', 'replicas': '2',
    })
    if last_ready_at is None:
        with pytest.raises(exceptions.PluginError, match='readiness budget of 45s exhausted'):
            handler.apply('request-id', 'sample-operator', 0, data)
        sync.assert_not_called()
    elif post_ready_change == 'rollout-superseded':
        with pytest.raises(exceptions.PluginError, match='rollout was superseded'):
            handler.apply('request-id', 'sample-operator', 0, data)
        sync.assert_not_called()
    else:
        output = handler.apply('request-id', 'sample-operator', 0, data)
        assert output['pods'] == 'sample-app-0;sample-app-1'
        first_id = 'cluster-id_newer-uid' if post_ready_change == 'pod-replaced' else 'cluster-id_new-0'
        assert [item['id'] for item in sync.call_args.args[2]] == [first_id, 'cluster-id_new-1']
    assert now == expected_elapsed
    assert client.create_statefulset.call_count == int(not rolling)
    assert client.replace_statefulset.call_count == int(rolling)
    if post_ready_change == 'old-crash-loop':
        client.delete_pod.assert_called_once()
        assert client.delete_pod.call_args.args[0] == 'sample-app-0'
        preconditions = client.delete_pod.call_args.kwargs['body'].preconditions
        assert (preconditions.uid, preconditions.resource_version) == ('old-0', 'old-resource-version')
    else:
        client.delete_pod.assert_not_called()


@pytest.mark.parametrize('timeout', [30, 240])
def test_cmdb_metadata_wait_is_bounded_and_does_not_check_readiness(timeout, monkeypatch):
    now = 0

    def sleep(seconds):
        nonlocal now
        now += seconds

    name = 'sample-app-0'
    pod = Object(metadata=Object(name=name, uid='pod-id', deletion_timestamp=None,
                                 owner_references=[Object(uid='workload', controller=True)]),
                 status=Object(host_ip=None))
    metadata = Object(name='sample-app', uid='workload')
    client = Object(list_pod=lambda *args, **kwargs: Object(items=[pod]))
    monkeypatch.setattr(api, 'time', Object(monotonic=lambda: now, sleep=sleep))

    records = api.StatefulSet()._collect_pod_metadata(
        client, 'default', metadata, [name], 'cluster-id', timeout,
    )

    assert now == timeout
    assert records == [{'name': name, 'id': 'cluster-id_pod-id', 'host_ip': ''}]


@pytest.mark.parametrize('read_failure_at', [None, 30])
def test_stuck_terminating_pod_cannot_extend_wait_past_its_grace(read_failure_at, monkeypatch):
    now = 0

    def sleep(seconds):
        nonlocal now
        now += seconds

    metadata = Object(name='sample-app', uid='workload', generation=2)
    pod = Object(metadata=Object(name='sample-app-0', uid='old-pod',
                                 owner_references=[Object(uid='workload', controller=True)],
                                 labels={'controller-revision-hash': 'old'},
                                 deletion_grace_period_seconds=120,
                                 deletion_timestamp=datetime.fromtimestamp(1120, timezone.utc)),
                 status=Object(phase='Failed'))
    status = Object(update_revision='new', current_revision='old', observed_generation=2, replicas=1)
    def list_pod(*args, **kwargs):
        if read_failure_at and 0 < now <= read_failure_at:
            raise exceptions.K8sCallError(cluster='sample-cluster', msg='temporary outage')
        return Object(items=[pod])

    client = Object(list_pod=list_pod,
                    get_statefulset=lambda *args, **kwargs: Object(metadata=metadata, status=status))
    monkeypatch.setattr(api, 'time', Object(monotonic=lambda: now, time=lambda: 1000 + now, sleep=sleep))

    with pytest.raises(exceptions.PluginError, match=r'150\.0s elapsed, 120\.0s old Pod shutdown excluded') as error:
        api.StatefulSet()._wait_for_rollout(client, 'default', metadata, 1, 30, True)

    assert 'still waiting for old Pod deletion: sample-app-0' in str(error.value)
    assert now == 150


@pytest.mark.parametrize('body', [None, '<html>Gateway timeout</html>', '{"message":"upstream timeout"}'])
def test_kubernetes_poll_preserves_sdk_error_with_any_response_body(body):
    error = ApiException(status=504, reason='Gateway Timeout')
    error.body = body
    client = k8s.Client(k8s.AuthToken('https://cluster.example.invalid', ''))
    client.app_client.read_namespaced_stateful_set = Mock(side_effect=error)
    client.core_client.list_namespaced_pod = Mock(side_effect=error)

    for operation in (lambda: client.get_statefulset('sample-app', 'default'),
                      lambda: client.list_pod('default')):
        with pytest.raises(exceptions.K8sCallError, match='[Tt]imeout') as wrapped:
            operation()
        assert wrapped.value.__cause__ is error


@pytest.mark.parametrize(('reason', 'fatal'), [('ImagePullBackOff', False), ('InvalidImageName', True)])
def test_cold_deployment_allows_retryable_init_image_pull(reason, fatal):
    pod = Object(metadata=Object(name='sample-app-0', deletion_timestamp=None),
                 status=Object(phase='Pending', container_statuses=[], init_container_statuses=[
                     Object(name='package-downloader', state=Object(waiting=Object(reason=reason, message=''))),
                 ]))

    failed, _ = api.StatefulSet()._check_pod_failures(None, 'sample-app', 'default', pods=[pod])

    assert failed is fatal
