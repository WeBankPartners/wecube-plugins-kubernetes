# coding=utf-8

from copy import deepcopy
import posixpath
import re

from talos.core import config
from talos.core.i18n import _

from wecubek8s.apps.plugin import utils
from wecubek8s.common import exceptions


CONF = config.CONF
DISCOVERY_LABEL = 'wecube.io/log-monitor'
WORKLOAD_ID_ANNOTATION = 'wecube.io/log-monitor-workload-id'
# Workload metadata records which log path to keep when apply replaces the Pod template.
LOG_PATH_ANNOTATION = 'wecube.io/log-monitor-log-path'
CONTAINER_NAME = 'log-exporter'
PORT_NAME = 'log-metrics'
PORT = 9100
SHARED_VOLUME_NAME = 'wecube-log-shared'
CACHE_VOLUME_NAME = 'wecube-log-rule-cache'
CACHE_PATH = '/app/monitor/data'
ENV_REFERENCE = re.compile(r'\$\$|\$\(([^)]+)\)')


def parse_enabled(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if not value:
            return None
        if value in ('true', 'false'):
            return value == 'true'
    raise exceptions.ValidationError(attribute='enable_log_sidecar', msg=_('expected true or false'))


def apply_state(data, existing):
    """Return None for the legacy template path, or the desired sidecar state."""
    requested = parse_enabled(data.get('enable_log_sidecar'))
    if DISCOVERY_LABEL in utils.convert_tag(data.get('pod_tags')):
        raise exceptions.ValidationError(attribute='pod_tags', msg=_('reserved label: %s') % DISCOVERY_LABEL)
    for annotations in data.get('annotations') or []:
        if isinstance(annotations, dict) and annotations.keys() & {WORKLOAD_ID_ANNOTATION, LOG_PATH_ANNOTATION}:
            raise exceptions.ValidationError(attribute='annotations', msg=_('reserved log monitor annotation'))

    if existing is None or LOG_PATH_ANNOTATION not in (existing.metadata.annotations or {}):
        return True if requested else None
    labels = existing.spec.template.metadata.labels or {}
    enabled = labels.get(DISCOVERY_LABEL) == 'enabled'
    return enabled if requested is None else requested


def _normalize(path):
    return '/' + posixpath.normpath(path).lstrip('/')


def resolve_log_data(data, enabled, existing):
    if enabled is None:
        return data
    path = (data.get('log_path') or '').strip()
    attribute = 'log_path'
    if not path and enabled:
        deployment_path = (data.get('deployment_path') or '').strip()
        if deployment_path:
            path = posixpath.join(deployment_path, 'logs')
            attribute = 'deployment_path'
    if not path and not enabled and existing is not None:
        path = (existing.metadata.annotations or {}).get(LOG_PATH_ANNOTATION)
    path = path or '/logs'
    normalized = _normalize(path)
    if not path.startswith('/') or '..' in path.split('/') or '\0' in path or normalized == '/':
        raise exceptions.ValidationError(attribute=attribute, msg=_('expected an absolute log directory below /'))
    return dict(data, log_path=normalized)


def _has_registry(image):
    first, separator, _ = image.partition('/')
    return bool(separator) and ('.' in first or ':' in first or first.lower() == 'localhost')


def _resolve_image(cluster_info):
    attribute = 'KUBERNETES_LOG_SIDECAR_IMAGE'
    image = (getattr(CONF, 'log_sidecar_image', '') or '').strip()
    if not image or '://' in image or any(char.isspace() for char in image):
        raise exceptions.ValidationError(attribute=attribute, msg=_('configure a valid log exporter image reference'))
    if not _has_registry(image):
        registry = (cluster_info.get('private_registry') or '').strip().rstrip('/')
        if not registry:
            raise exceptions.ValidationError(
                attribute=attribute,
                msg=_('relative log exporter image requires private_registry on the target cluster'))
        image = registry + '/' + image
    if (not _has_registry(image) or not all(image.split('/')) or '://' in image
            or any(char.isspace() for char in image)):
        raise exceptions.ValidationError(attribute=attribute, msg=_('invalid log exporter image or private_registry'))
    return image


def _under(path, parent):
    return path == parent or path.startswith(parent.rstrip('/') + '/')


def _log_mount(mounts, path):
    covering = []
    nested = []
    for mount in mounts:
        mount_path = _normalize(mount['mountPath'])
        if _under(path, mount_path):
            covering.append(mount)
        elif _under(mount_path, path):
            nested.append(mount)
    if nested:
        return None, nested
    if not covering:
        return None, []
    covering.sort(key=lambda mount: len(_normalize(mount['mountPath'])), reverse=True)
    best_path = _normalize(covering[0]['mountPath'])
    duplicates = [mount for mount in covering if _normalize(mount['mountPath']) == best_path]
    if len(duplicates) > 1:
        return None, duplicates
    return covering[0], []


def _mount_conflict(path, mounts):
    sources = ', '.join('%s at %s' % (mount['name'], mount['mountPath']) for mount in mounts)
    return exceptions.ValidationError(
        attribute='log_path', msg=_('cannot share log directory %(path)s with mount(s): %(sources)s') % {
            'path': path, 'sources': sources,
        })


def _append_volume(volumes, claim_names, volume):
    name = volume['name']
    if name in claim_names or any(existing['name'] == name for existing in volumes):
        raise exceptions.ValidationError(attribute='volumes', msg=_('log volume name already in use: %s') % name)
    volumes.append(volume)


def _is_legacy_host_path(volume):
    return volume['name'] == 'instance-logs' and volume.get('hostPath', {}).get('type') == 'DirectoryOrCreate'


def _keep_legacy_host_path(mounts, volumes, claim_names, previous_mounts, previous_volumes):
    if not utils.host_path_enabled():
        return
    volume = next((item for item in previous_volumes if _is_legacy_host_path(item)), None)
    if not volume or volume['name'] in claim_names or any(item['name'] == volume['name'] for item in volumes):
        return
    mount = next((item for item in previous_mounts if item['name'] == volume['name']), None)
    if mount is None:
        return
    replacement, conflicts = _log_mount(mounts, _normalize(mount['mountPath']))
    if not replacement and not conflicts:
        volumes.append(deepcopy(volume))
        mounts.append({**mount, 'readOnly': mount.get('readOnly', False)})


def _restore_mount(path, previous_mounts, previous_volumes, volumes, claim_names, enabled):
    mount, conflicts = _log_mount(previous_mounts, path)
    if enabled and conflicts:
        raise _mount_conflict(path, conflicts)
    if not mount:
        return None
    name = mount['name']
    mount = {**mount, 'readOnly': mount.get('readOnly', False)}
    if name in claim_names:
        return mount

    previous_volume = next((volume for volume in previous_volumes if volume['name'] == name), None)
    if not previous_volume or (_is_legacy_host_path(previous_volume) and not utils.host_path_enabled()):
        return None
    if previous_volume not in volumes:
        _append_volume(volumes, claim_names, deepcopy(previous_volume))
    return mount


def _exporter_mount(path, mount):
    shared = {'name': mount['name'], 'mountPath': path, 'readOnly': True}
    relative = posixpath.relpath(path, _normalize(mount['mountPath']))
    if mount.get('subPathExpr'):
        expression = mount['subPathExpr']
        # The suffix is a literal directory, even when it contains a dollar sign.
        shared['subPathExpr'] = expression if relative == '.' else posixpath.join(expression, relative.replace('$', '$$'))
    elif mount.get('subPath') or relative != '.':
        pieces = [part for part in (mount.get('subPath'), relative if relative != '.' else None) if part]
        shared['subPath'] = posixpath.join(*pieces)
    return shared


def _referenced_env(app, expression):
    # Kubelet resolves subPathExpr from this container's env, in declaration order.
    references = set(ENV_REFERENCE.findall(expression or ''))
    selected = []
    for entry in reversed(app.get('env', [])):
        if entry['name'] in references:
            selected.append(deepcopy(entry))
            references.update(ENV_REFERENCE.findall(entry.get('value') or ''))
    return list(reversed(selected))


def configure(k8s_client, template, data, enabled, existing, cluster_info):
    if enabled is None:
        return
    pod = template['spec']['template']
    pod_spec = pod['spec']
    containers = pod_spec['containers']
    app = containers[0]
    mounts = app['volumeMounts']
    volumes = pod_spec['volumes']
    claim_names = {claim['metadata']['name'] for claim in template['spec'].get('volumeClaimTemplates', [])}
    path = data['log_path']
    previous_mounts = []
    previous_volumes = []
    if existing is not None:
        from kubernetes import client

        previous_pod = client.ApiClient().sanitize_for_serialization(existing.spec.template.spec)
        previous_app = next((item for item in previous_pod.get('containers', []) if item['name'] != CONTAINER_NAME), {})
        previous_mounts = previous_app.get('volumeMounts', [])
        previous_volumes = previous_pod.get('volumes', [])
        _keep_legacy_host_path(mounts, volumes, claim_names, previous_mounts, previous_volumes)

    mount, conflicts = _log_mount(mounts, path)
    if enabled and conflicts:
        raise _mount_conflict(path, conflicts)
    if not mount and not conflicts:
        mount = _restore_mount(path, previous_mounts, previous_volumes, volumes, claim_names, enabled)
        if not mount and enabled:
            _append_volume(volumes, claim_names, {'name': SHARED_VOLUME_NAME, 'emptyDir': {}})
            mount = {'name': SHARED_VOLUME_NAME, 'mountPath': path, 'readOnly': False}
        if mount:
            mounts.append(mount)

    if enabled or mount or conflicts:
        template['metadata']['annotations'][LOG_PATH_ANNOTATION] = path
    if not enabled:
        return

    sources = [volume for volume in volumes if volume['name'] == mount['name']]
    if mount['name'] in claim_names:
        sources.append({'persistentVolumeClaim': {}})
    if len(sources) != 1 or mount.get('readOnly') or (mount.get('subPath') and mount.get('subPathExpr')):
        raise _mount_conflict(path, [mount])
    source = sources[0]
    for key, spec in source.items():
        if key in ('configMap', 'secret', 'projected', 'downwardAPI', 'image') or (
                isinstance(spec, dict) and spec.get('readOnly')):
            raise _mount_conflict(path, [mount])
    if _under(path, CACHE_PATH) or _under(CACHE_PATH, path):
        raise exceptions.ValidationError(attribute='log_path', msg=_('log directory overlaps the exporter rule cache'))

    for container in containers + pod_spec.get('initContainers', []):
        if container['name'] == CONTAINER_NAME:
            raise exceptions.ValidationError(attribute='image_name', msg=_('container name already in use: %s') % CONTAINER_NAME)
        for port in container.get('ports', []):
            if port.get('name') == PORT_NAME or (
                    port.get('containerPort') == PORT and (port.get('protocol') or 'TCP').upper() == 'TCP'):
                raise exceptions.ValidationError(attribute='image_port', msg=_('port already in use: 9100/TCP or log-metrics'))

    image = _resolve_image(cluster_info)
    _append_volume(volumes, claim_names, {'name': CACHE_VOLUME_NAME, 'emptyDir': {}})
    shared = _exporter_mount(path, mount)
    sidecar = {
        'name': CONTAINER_NAME,
        'image': image,
        'ports': [{'name': PORT_NAME, 'containerPort': PORT, 'protocol': 'TCP'}],
        'securityContext': {
            'runAsNonRoot': True,
            'runAsUser': 65534,
            'runAsGroup': 65534,
            'allowPrivilegeEscalation': False,
            'capabilities': {'drop': ['ALL']},
            'seccompProfile': {'type': 'RuntimeDefault'},
        },
        'volumeMounts': [shared, {'name': CACHE_VOLUME_NAME, 'mountPath': CACHE_PATH}],
    }
    env = _referenced_env(app, shared.get('subPathExpr'))
    if env:
        sidecar['env'] = env
    pull_secret = (getattr(CONF, 'log_sidecar_image_pull_secret', '') or '').strip()
    secrets = pod_spec.get('imagePullSecrets', [])
    if pull_secret and not any(item['name'] == pull_secret for item in secrets):
        namespace = data['namespace']
        secret = k8s_client.get_secret(pull_secret, namespace)
        if not secret or secret.type not in ('kubernetes.io/dockerconfigjson', 'kubernetes.io/dockercfg'):
            raise exceptions.ValidationError(
                attribute='KUBERNETES_LOG_SIDECAR_IMAGE_PULL_SECRET',
                msg=_('registry Secret %(name)s is missing or invalid in namespace %(namespace)s') % {
                    'name': pull_secret, 'namespace': namespace,
                })
        pod_spec['imagePullSecrets'] = [*secrets, {'name': pull_secret}]
    containers.append(sidecar)
    pod['metadata']['labels'] = {**pod['metadata']['labels'], DISCOVERY_LABEL: 'enabled'}
    pod['metadata']['annotations'][WORKLOAD_ID_ANNOTATION] = data['correlation_id']
