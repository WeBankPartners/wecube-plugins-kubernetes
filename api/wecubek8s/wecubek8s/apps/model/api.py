# coding=utf-8

from __future__ import absolute_import

import logging

from talos.common import cache
from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import jsonfilter
from wecubek8s.common import k8s
from wecubek8s.common import const
from wecubek8s.db import resource as db_resource

CONF = config.CONF
LOG = logging.getLogger(__name__)


class BaseEntity:
    def list(self, filters=None):
        clusters = db_resource.Cluster().list()

        results = self.all(clusters)
        if filters:
            results = [ret for ret in results if jsonfilter.match_all(filters, ret)]
        return results

    def cached_all(self, clusters):
        cached_key = 'k8s.' + ','.join([cluster['id'] for cluster in sorted(clusters, key=lambda x: x['id'])
                                        ]) + '.' + self.__class__.__name__
        cached_data = cache.get(cached_key, 3)
        if not cache.validate(cached_data):
            cached_data = self.all(clusters)
            cache.set(cached_key, cached_data)
        return cached_data

    def all(self, clusters):
        return []

    def cluster_client(self, cluster):
        k8s_auth = k8s.AuthToken(cluster['api_server'], cluster['token'])
        k8s_client = k8s.Client(k8s_auth)
        return k8s_client


class Cluster(BaseEntity):
    def all(self, clusters):
        results = []
        for cluster in clusters:
            results.append({
                'id': cluster['id'],
                'name': cluster['name'],
                'displayName': cluster['name'],
                'correlation_id': cluster['correlation_id']
            })
        return results


class Node(BaseEntity):
    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_node().items:
                ip_address = None
                for address in item.status.addresses:
                    if address.type == 'InternalIP':
                        ip_address = address.address
                        break
                correlation_id = None
                if item.metadata.labels:
                    for tag_key, tag_value in item.metadata.labels.items():
                        if tag_key == const.Tag.NODE_ID_TAG:
                            correlation_id = tag_value
                            break
                results.append({
                    'id': item.metadata.uid,
                    'name': item.metadata.name,
                    'displayName': f'{cluster["name"]}-{item.metadata.name}',
                    'ip_address': ip_address,
                    'cluster_id': cluster["id"],
                    'correlation_id': correlation_id,
                })
        return results


class Deployment(BaseEntity):
    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_deployment().items:
                correlation_id = None
                if item.metadata.labels:
                    for tag_key, tag_value in item.metadata.labels.items():
                        if tag_key == const.Tag.DEPLOYMENT_ID_TAG:
                            correlation_id = tag_value
                            break
                results.append({
                    'id': item.metadata.uid,
                    'name': item.metadata.name,
                    'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
                    'namespace': item.metadata.namespace,
                    'cluster_id': cluster["id"],
                    'correlation_id': correlation_id,
                })
        return results


class ReplicaSet(BaseEntity):
    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_replica_set().items:
                controll_by = None
                if item.metadata.owner_references:
                    for owner in item.metadata.owner_references:
                        if owner.controller and owner.kind == 'Deployment':
                            controll_by = owner.uid
                            break
                results.append({
                    'id': item.metadata.uid,
                    'name': item.metadata.name,
                    'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
                    'namespace': item.metadata.namespace,
                    'deployment_id': controll_by,
                    'cluster_id': cluster["id"]
                })
        return results


class Service(BaseEntity):
    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_service().items:
                correlation_id = None
                if item.metadata.labels:
                    for tag_key, tag_value in item.metadata.labels.items():
                        if tag_key == const.Tag.SERVICE_ID_TAG:
                            correlation_id = tag_value
                            break
                results.append({
                    'id': item.metadata.uid,
                    'name': item.metadata.name,
                    'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
                    'namespace': item.metadata.namespace,
                    'cluster_id': cluster["id"],
                    'correlation_id': correlation_id,
                })
        return results


class Pod(BaseEntity):
    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_pod().items:
                correlation_id = None
                if item.metadata.labels:
                    for tag_key, tag_value in item.metadata.labels.items():
                        if tag_key == const.Tag.POD_ID_TAG:
                            correlation_id = tag_value
                            break
                controll_by = None
                if item.metadata.owner_references:
                    for owner in item.metadata.owner_references:
                        if owner.controller and owner.kind == 'ReplicaSet':
                            controll_by = owner.uid
                            break
                results.append({
                    'id': item.metadata.uid,
                    'name': item.metadata.name,
                    'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
                    'namespace': item.metadata.namespace,
                    'deployment_id': controll_by,
                    'correlation_id': correlation_id,
                    'node_id': item.spec.node_name,
                    'cluster_id': cluster["id"],
                })
        # patch node_id
        node_mapping = {}
        if results:
            nodes = Node().cached_all(clusters)
            for node in nodes:
                node_mapping.setdefault(node['cluster_id'], {}).setdefault(node['name'], node['id'])
        # patch deployment_id
        rs_mapping = {}
        if results:
            rss = ReplicaSet().cached_all(clusters)
            for rs in rss:
                rs_mapping.setdefault(rs['cluster_id'], {}).setdefault(rs['id'], rs['deployment_id'])
        for pod in results:
            pod['node_id'] = node_mapping.get(pod['cluster_id'], {}).get(pod['node_id'], None)
            pod['deployment_id'] = rs_mapping.get(pod['cluster_id'], {}).get(pod['deployment_id'], None)
        return results
