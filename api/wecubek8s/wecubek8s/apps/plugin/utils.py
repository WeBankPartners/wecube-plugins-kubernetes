# coding=utf-8

from __future__ import absolute_import

import logging
import re

from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import exceptions

CONF = config.CONF
LOG = logging.getLogger(__name__)


def escape_name(name):
    '''
    lowercase RFC 1123 name must consist of lower case alphanumeric characters, 
    '-' or '.', and must start and end with an alphanumeric character 
    (e.g. 'example.com', regex used for validation is '[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*')
    '''
    rule = r'[^.a-z0-9]'
    return re.sub(rule, '-', name.lower())


def convert_tag(items):
    labels = {}
    for tag in items:
        labels[tag['name']] = tag['value']
    return labels


def convert_pod_ports(item):
    # convert pod ports
    # eg. 12, 23:32, 45::UDP, 678:876:TCP
    rets = []
    parts = re.split(r',|;', item)
    for part in parts:
        if part.strip():
            part = part.strip()
            map_parts = part.split(':', 2)
            ret = {'containerPort': int(map_parts[0]), 'protocol': 'TCP'}
            if len(map_parts) >= 1:
                rets.append(ret)
            if len(map_parts) >= 2:
                if map_parts[1]:
                    ret['hostPort'] = int(map_parts[1])
            if len(map_parts) >= 3:
                ret['protocol'] = map_parts[2]
    return rets


def convert_service_port(items):
    # convert service port
    rets = []
    fields = ['name', 'protocol', 'port', 'targetPort', 'nodePort']
    for item in items:
        ret = {}
        for field in fields:
            if item.get(field):
                ret[field] = item[field]
                if field in ('port', 'targetPort', 'nodePort'):
                    ret[field] = int(ret[field])
        rets.append(ret)
    return rets


def convert_env(items):
    # convert envs
    rets = []
    for idx, item in enumerate(items):
        if item['valueRef'] is None and item['valueFrom'] != 'value':
            raise exceptions.ValidationError(attribute='envs[%s]' % (idx + 1),
                                             msg=_('valueRef is NULL, while valueFrom is %(value)s') %
                                             {'value': item['valueFrom']})
        if item['valueFrom'] == 'value':
            rets.append({'name': item['name'], 'value': item['value']})
        elif item['valueFrom'] == 'configMap':
            rets.append({
                'name': item['name'],
                'valueFrom': {
                    'configMapKeyRef': {
                        'name': item['valueRef']['name'],
                        'key': item['valueRef']['value']
                    }
                }
            })
        elif item['valueFrom'] == 'secretKey':
            rets.append({
                'name': item['name'],
                'valueFrom': {
                    'secretKeyRef': {
                        'name': item['valueRef']['name'],
                        'key': item['valueRef']['value']
                    }
                }
            })
        elif item['valueFrom'] == 'fieldRef':
            rets.append({'name': item['name'], 'valueFrom': {'fieldRef': {'fieldPath': item['valueRef']['name']}}})
    return rets


def convert_volume(items):
    # convert volumes
    volumes = []
    mounts = []
    for item in items:
        volume_name = item['name']
        volume_type = item['type']
        volume_type_spec = item.get('typeSpec', None) or {}
        volume_mount_path = item['mountPath']
        volume_read_only = item.get('readOnly', None) or False

        volume_type_spec_new = {}
        volumes.append({'name': volume_name, volume_type: volume_type_spec_new})
        if volume_type == 'configMap':
            volume_type_spec_new['name'] = volume_type_spec['name']
        elif volume_type == 'secret':
            volume_type_spec_new['secretName'] = volume_type_spec['name']
        elif volume_type == 'hostPath':
            volume_type_spec_new['path'] = volume_type_spec['path']
            volume_type_spec_new['type'] = volume_type_spec.get('type', None) or ''
        elif volume_type == 'emptyDir':
            volume_type_spec_new['medium'] = volume_type_spec.get('medium', '') or ''
            if 'sizeLimit' in volume_type_spec and volume_type_spec['sizeLimit']:
                volume_type_spec_new['sizeLimit'] = volume_type_spec['sizeLimit']
        elif volume_type == 'nfs':
            volume_type_spec_new['server'] = volume_type_spec['server']
            volume_type_spec_new['path'] = volume_type_spec['path']
            volume_type_spec_new['readOnly'] = volume_read_only
        elif volume_type == 'persistentVolumeClaim':
            volume_type_spec_new['claimName'] = volume_type_spec['name']
            volume_type_spec_new['readOnly'] = volume_read_only

        mounts.append({'name': volume_name, 'mountPath': volume_mount_path, 'readOnly': volume_read_only})
    return volumes, mounts


def convert_resource_limit(cpu, memory):
    ret = {'limits': {}, 'requests': {}}
    if cpu:
        ret['limits'].setdefault('cpu', cpu)
        ret['requests'].setdefault('cpu', cpu)
    if memory:
        ret['limits'].setdefault('memory', memory)
        ret['requests'].setdefault('memory', memory)
    return ret


def parse_image_url(image_url):
    '''parse image_url
    eg. 
    ccr.ccs.tencentyun.com:5555/webankpartners/platform-core:v2.9.0
    ccr.ccs.tencentyun.com:5555/platform-core:v2.9.0
    ccr.ccs.tencentyun.com:5555/webankpartners/platform-core
    ccr.ccs.tencentyun.com/webankpartners/platform-core:v2.9.0
    ccr.ccs.tencentyun.com/platform-core:v2.9.0
    ccr.ccs.tencentyun.com/platform-core
    webankpartners/platform-core:v2.9.0
    webankpartners/platform-core
    platform-core:v2.9.0
    platform-core
    minio/mc
    ccr.ccs.tencentyun.com:5555/a.b.c.namespace/d.e.f.name:tag1
    ccr.ccs.tencentyun.com:5555/a.b.c.namespace/d.e.f.name
    ccr.ccs.tencentyun.com/a.b.c.namespace/d.e.f.name:tag1
    ccr.ccs.tencentyun.com/a.b.c.namespace/d.e.f.name
    '''
    url_rule = r'^((?P<server>([a-zA-Z0-9]+(\.[-_a-zA-Z0-9]+)+?))(:(?P<port>\d+))?/)?((?P<namespace>([-_a-zA-Z0-9]+?))/)?(?P<image>([-_a-zA-Z0-9]+?))(:(?P<tag>[-_.a-zA-Z0-9]+))?$'
    # private url like: server/namespace/image[:tag]
    private_url_rule = r'^((?P<server>([a-zA-Z0-9]+(\.[-_a-zA-Z0-9]+)+?))(:(?P<port>\d+))?/)((?P<namespace>([-_.a-zA-Z0-9]+?))/)(?P<image>([-_.a-zA-Z0-9]+?))(:(?P<tag>[-_.a-zA-Z0-9]+))?$'
    ret = re.search(url_rule, image_url)
    if ret:
        server_with_port = None
        if ret['server']:
            if ret['port']:
                server_with_port = '%s:%s' % (ret['server'], ret['port'])
            else:
                server_with_port = ret['server']
        return server_with_port, ret['namespace'], ret['image'], ret['tag']
    else:
        ret = re.search(private_url_rule, image_url)
        if ret:
            server_with_port = None
            if ret['port']:
                server_with_port = '%s:%s' % (ret['server'], ret['port'])
            else:
                server_with_port = ret['server']
            return server_with_port, ret['namespace'], ret['image'], ret['tag']
    return None, None, None, None


def convert_container(images, envs, vols, resource_limit):
    containers = []
    container_template = {
        'name': '',
        'image': '',
        'imagePullPolicy': 'IfNotPresent',
        'ports': [],
        'env': envs,
        'volumeMounts': vols,
        'resources': resource_limit
    }
    for image_info in images:
        container = container_template.copy()
        registry_server, registry_namespace, image_name, image_tag = parse_image_url(image_info['name'].strip())
        container['name'] = image_name
        container['image'] = image_info['name'].strip()
        container['ports'] = convert_pod_ports(image_info.get('ports', ''))
        containers.append(container)

    return containers


def convert_registry_secret(k8s_client, images, namespace, username, password):
    rets = []
    for image_info in images:
        registry_server, registry_namespace, image_name, image_tag = parse_image_url(image_info['name'].strip())
        if registry_server:
            name = ''
            name = registry_server + '#' + username
            name = escape_name(name)
            k8s_client.ensure_registry_secret(name, namespace, registry_server, username, password)
            rets.append({'name': name})
    return rets


def convert_affinity(strategy, tag_key, tag_value):
    if strategy == 'anti-host-preferred':
        return {
            'podAntiAffinity': {
                'preferredDuringSchedulingIgnoredDuringExecution': [{
                    'weight': 100,
                    'podAffinityTerm': {
                        'labelSelector': {
                            'matchExpressions': [{
                                'key': tag_key,
                                'operator': 'In',
                                'values': [tag_value]
                            }]
                        },
                        'topologyKey': 'kubernetes.io/hostname'
                    }
                }]
            }
        }
    elif strategy == 'anti-host-required':
        return {
            'podAntiAffinity': {
                'requiredDuringSchedulingIgnoredDuringExecution': [{
                    'labelSelector': {
                        'matchExpressions': [{
                            'key': tag_key,
                            'operator': 'In',
                            'values': [tag_value]
                        }]
                    },
                    'topologyKey': 'kubernetes.io/hostname'
                }]
            }
        }
    return {}