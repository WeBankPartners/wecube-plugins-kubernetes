# coding=utf-8

from __future__ import absolute_import

import datetime
import logging

from talos.common import cache
from talos.core import config
from talos.core.i18n import _
from talos.utils.scoped_globals import GLOBALS
from wecubek8s.common import expression
from wecubek8s.common import utils
from wecubek8s.common import exceptions
from wecubek8s.common import k8s

CONF = config.CONF
LOG = logging.getLogger(__name__)


def convert_tag(items):
    labels = {}
    for tag in items:
        labels[tag['name']] = tag['value']
    return labels


def convert_port(items):
    # TODO: convert ports
    return []


def convert_service_port(items):
    # TODO: convert ports
    return []


def convert_env(items):
    # TODO: convert envs
    return []


def convert_volume(items):
    # TODO: convert volumes
    return [], []


def convert_resource_limit(item):
    if item['cpu'] and item['memory']:
        return {
            'limits': {
                'cpu': item['cpu'],
                'memory': item['memory']
            },
            'requests': {
                'cpu': item['cpu'],
                'memory': item['memory']
            }
        }
    return {}


def convert_container(items, ports, envs, vols, resource_limit):
    def image_name_from_url(image_url):
        # TODO: parse image_url
        return image_url

    def image_from_url(image_url):
        # TODO: parse image_url
        return image_url

    containers = []
    container_template = {
        'name': '',
        'image': '',
        'ports': ports,
        'env': envs,
        'volumeMounts': vols,
        'resources': resource_limit
    }
    # TODO: image pull auth support
    for image in items:
        container = container_template.copy()
        container['name'] = image_name_from_url(image)
        container['image'] = image_from_url(image)
        containers.append(container)

    return containers


class Deployment:
    def to_resource(self, data):
        resource_name = data['name']
        resource_tags = convert_tag(data['tags'])
        replicas = len(data['instances'])
        pod_spec = data['instances'][0]
        pod_spec_tags = convert_tag(pod_spec['tags'])
        pod_spec_ports = convert_port(pod_spec['ports'])
        pod_spec_envs = convert_env(pod_spec['envs'])
        pod_spec_src_vols, pod_spec_mnt_vols = convert_volume(pod_spec['volumes'])
        pod_spec_limit = convert_resource_limit(pod_spec)
        containers = convert_container(data['images'], pod_spec_ports, pod_spec_envs, pod_spec_mnt_vols, pod_spec_limit)
        template = {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name
            },
            'spec': {
                'replicas': replicas,
                'selector': {
                    'matchLabels': pod_spec_tags
                },
                'template': {
                    'metadata': {
                        'labels': pod_spec_tags
                    },
                    'spec': {
                        'containers': containers,
                        'volumes': pod_spec_src_vols
                    }
                }
            }
        }
        return template

    def apply(self, data):
        k8s_auth = k8s.AuthToken(data['clusterUrl'], data['clusterToken'])
        k8s_client = k8s.Client(k8s_auth, version=data['apiVersion'])
        exists_resource = k8s_client.get_deployment(data['name'], data['namespace'])
        if exists_resource is None:
            exists_resource = k8s_client.create_deployment(data['namespace'], self.to_resource(data))
        else:
            exists_resource = k8s_client.update_deployment(data['name'], data['namespace'], self.to_resource(data))
        return exists_resource


class Service:
    def to_resource(self, data):
        resource_name = data['name']
        resource_tags = convert_tag(data['tags'])
        resource_type = data['type']
        resource_headless = 'clusterIP' in data and data['clusterIP'] is None
        resource_cluster_ip = data.get('clusterIP', None)
        resource_session = data.get('sessionAffinity', None)

        ports = convert_service_port(data['instances'])
        selectors = convert_tag(data['selectors'])
        template = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name
            },
            'spec': {
                'type': resource_type,
                'sessionAffinity': resource_session,
                'ports': ports,
                'selector': selectors
            }
        }
        if resource_headless:
            template['spec']['clusterIP'] = None
        elif resource_cluster_ip:
            # not headless & user specific cluster ip, use it
            template['spec']['clusterIP'] = resource_cluster_ip
        return template

    def apply(self, data):
        k8s_auth = k8s.AuthToken(data['clusterUrl'], data['clusterToken'])
        k8s_client = k8s.Client(k8s_auth, version=data['apiVersion'])
        exists_resource = k8s_client.get_service(data['name'], data['namespace'])
        if not exists_resource:
            exists_resource = k8s_client.create_service(data['namespace'], self.to_resource(data))
        else:
            exists_resource = k8s_client.update_service(data['name'], data['namespace'], self.to_resource(data))
        return exists_resource
