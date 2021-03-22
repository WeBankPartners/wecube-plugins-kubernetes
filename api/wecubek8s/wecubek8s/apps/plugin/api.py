# coding=utf-8

from __future__ import absolute_import

import logging

from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import k8s
from wecubek8s.apps.plugin import utils as api_utils

CONF = config.CONF
LOG = logging.getLogger(__name__)


class Deployment:
    def to_resource(self, k8s_client, data):
        resource_name = data['name']
        resource_namespace = data['namespace']
        resource_tags = api_utils.convert_tag(data['tags'])
        replicas = len(data['instances'])
        pod_spec = data['instances'][0]
        pod_spec_tags = api_utils.convert_tag(pod_spec['tags'])
        pod_spec_ports = api_utils.convert_pod_ports(pod_spec['ports'])
        pod_spec_envs = api_utils.convert_env(pod_spec['envs'])
        pod_spec_src_vols, pod_spec_mnt_vols = api_utils.convert_volume(pod_spec['volumes'])
        pod_spec_limit = api_utils.convert_resource_limit(pod_spec)
        containers = api_utils.convert_container(data['images'], pod_spec_ports, pod_spec_envs, pod_spec_mnt_vols,
                                                 pod_spec_limit)
        registry_secrets = []
        if data.get('image_pull_username') and data.get('image_pull_password'):
            registry_secrets = api_utils.convert_registry_secret(k8s_client, data['images'], resource_namespace,
                                                                 data['image_pull_username'],
                                                                 data['image_pull_password'])
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
        # set imagePullSecrets if available
        if registry_secrets:
            template['spec']['template']['spec']['imagePullSecrets'] = registry_secrets
        return template

    def apply(self, data):
        k8s_auth = k8s.AuthToken(data['clusterUrl'], data['clusterToken'])
        k8s_client = k8s.Client(k8s_auth)
        exists_resource = k8s_client.get_deployment(data['name'], data['namespace'])
        if exists_resource is None:
            exists_resource = k8s_client.create_deployment(data['namespace'], self.to_resource(k8s_client, data))
        else:
            exists_resource = k8s_client.update_deployment(data['name'], data['namespace'],
                                                           self.to_resource(k8s_client, data))
        return exists_resource.to_dict()['spec']


class Service:
    def to_resource(self, k8s_client, data):
        resource_name = data['name']
        resource_tags = api_utils.convert_tag(data['tags'])
        resource_type = data['type']
        resource_headless = 'clusterIP' in data and data['clusterIP'] is None
        resource_cluster_ip = data.get('clusterIP', None)
        resource_session = data.get('sessionAffinity', None)

        ports = api_utils.convert_service_port(data['instances'])
        selectors = api_utils.convert_tag(data['selectors'])
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
        k8s_client = k8s.Client(k8s_auth)
        exists_resource = k8s_client.get_service(data['name'], data['namespace'])
        if not exists_resource:
            exists_resource = k8s_client.create_service(data['namespace'], self.to_resource(k8s_client, data))
        else:
            exists_resource = k8s_client.update_service(data['name'], data['namespace'],
                                                        self.to_resource(k8s_client, data))
        return exists_resource.to_dict()['spec']
