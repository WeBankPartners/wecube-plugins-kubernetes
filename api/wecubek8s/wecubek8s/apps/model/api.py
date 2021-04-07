# coding=utf-8

from __future__ import absolute_import

import logging
import datetime
from urllib.parse import urlparse

from kubernetes import watch
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
        # all cached as default(3s)
        results = self.cached_all(clusters)
        if filters:
            # The following options of operator is required by wecube-platform: eq/neq/is/isnot/gt/lt/like/in
            # but kubernetes plugin supports for more: gte/lte/notin/regex/set/notset
            # set test false/0/''/[]/{}/None as false
            # you can also use regex to match the value
            results = [ret for ret in results if jsonfilter.match_all(filters, ret)]
        return results

    def clear_cache(self, clusters):
        cached_key = 'k8s.' + ','.join([cluster['id'] for cluster in sorted(clusters, key=lambda x: x['id'])
                                        ]) + '.' + self.__class__.__name__
        cache.delete(cached_key)

    def cached_all(self, clusters, expires=3):
        cached_key = 'k8s.' + ','.join([cluster['id'] for cluster in sorted(clusters, key=lambda x: x['id'])
                                        ]) + '.' + self.__class__.__name__
        cached_data = cache.get(cached_key, expires)
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
    @classmethod
    def to_dict(cls, cluster, item):
        parse_info = urlparse(item['api_server'])
        api_info = parse_info.netloc.rsplit(':', 1)
        api_host = ''
        api_port = 0
        if len(api_info) >= 2:
            api_host = api_info[0]
            api_port = int(api_info[1]) or (443 if api_info.scheme == 'https' else 80)
        result = {
            'id': item['id'],
            'name': item['name'],
            'displayName': item['name'],
            'correlation_id': item['correlation_id'],
            'api_server': item['api_server'],
            'api_host': api_host,
            'api_port': str(api_port),
            'token': item['token'],
            'metric_host': item['metric_host'],
            'metric_port': str(item['metric_port']),
        }
        return result

    def all(self, clusters):
        results = []
        for cluster in clusters:
            results.append(self.to_dict(cluster, cluster))
        return results


class Node(BaseEntity):
    @classmethod
    def to_dict(cls, cluster, item):
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
        result = {
            'id': item.metadata.uid,
            'name': item.metadata.name,
            'displayName': f'{cluster["name"]}-{item.metadata.name}',
            'ip_address': ip_address,
            'cluster_id': cluster["id"],
            'correlation_id': correlation_id,
        }
        return result

    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_node().items:
                results.append(self.to_dict(cluster, item))
        return results


class Deployment(BaseEntity):
    @classmethod
    def to_dict(cls, cluster, item):
        correlation_id = None
        if item.metadata.labels:
            for tag_key, tag_value in item.metadata.labels.items():
                if tag_key == const.Tag.DEPLOYMENT_ID_TAG:
                    correlation_id = tag_value
                    break
        result = {
            'id': item.metadata.uid,
            'name': item.metadata.name,
            'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
            'namespace': item.metadata.namespace,
            'cluster_id': cluster["id"],
            'correlation_id': correlation_id,
        }
        return result

    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_deployment().items:
                results.append(self.to_dict(cluster, item))
        return results


class ReplicaSet(BaseEntity):
    @classmethod
    def to_dict(cls, cluster, item):
        controll_by = None
        if item.metadata.owner_references:
            for owner in item.metadata.owner_references:
                if owner.controller and owner.kind == 'Deployment':
                    controll_by = owner.uid
                    break
        result = {
            'id': item.metadata.uid,
            'name': item.metadata.name,
            'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
            'namespace': item.metadata.namespace,
            'deployment_id': controll_by,
            'cluster_id': cluster["id"]
        }
        return result

    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_replica_set().items:
                results.append(self.to_dict(cluster, item))
        return results


class Service(BaseEntity):
    @classmethod
    def to_dict(cls, cluster, item):
        correlation_id = None
        if item.metadata.labels:
            for tag_key, tag_value in item.metadata.labels.items():
                if tag_key == const.Tag.SERVICE_ID_TAG:
                    correlation_id = tag_value
                    break
        result = {
            'id': item.metadata.uid,
            'name': item.metadata.name,
            'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
            'namespace': item.metadata.namespace,
            'cluster_id': cluster["id"],
            'ip_address': item.spec.cluster_ip,
            'correlation_id': correlation_id,
        }
        return result

    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_service().items:
                results.append(self.to_dict(cluster, item))
        return results


class Pod(BaseEntity):
    @classmethod
    def to_dict(cls, cluster, item):
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
        result = {
            'id': item.metadata.uid,
            'name': item.metadata.name,
            'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
            'namespace': item.metadata.namespace,
            'ip_address': item.status.pod_ip,
            'replicaset_id': controll_by,
            'deployment_id': None,
            'correlation_id': correlation_id,
            'node_id': item.spec.node_name,
            'cluster_id': cluster["id"],
        }
        # patch node_id
        node_mapping = {}
        nodes = Node().cached_all([cluster])
        for node in nodes:
            node_mapping.setdefault(node['cluster_id'], {}).setdefault(node['name'], node['id'])
        # patch deployment_id
        rs_mapping = {}
        rss = ReplicaSet().cached_all([cluster])
        for rs in rss:
            rs_mapping.setdefault(rs['cluster_id'], {}).setdefault(rs['id'], rs['deployment_id'])
        result['node_id'] = node_mapping.get(result['cluster_id'], {}).get(result['node_id'], None)
        result['deployment_id'] = rs_mapping.get(result['cluster_id'], {}).get(result['replicaset_id'], None)
        return result

    def all(self, clusters):
        results = []
        for cluster in clusters:
            k8s_client = self.cluster_client(cluster)
            for item in k8s_client.list_all_pod().items:
                results.append(self.to_dict(cluster, item))
        return results

    def watch(self, cluster, event_stop, notify):
        k8s_client = self.cluster_client(cluster)
        current_time = datetime.datetime.now(datetime.timezone.utc)
        w = watch.Watch()
        for event in w.stream(k8s_client.core_client.list_pod_for_all_namespaces):
            if event['type'] == 'ADDED':
                # new -> alert
                if event['object'].metadata.creation_timestamp >= current_time:
                    notify('POD.ADDED', cluster['id'], self.to_dict(cluster, event['object']))
            elif event['type'] == 'DELETED':
                # delete -> alert
                notify('POD.DELETED', cluster['id'], self.to_dict(cluster, event['object']))
            if event_stop.is_set():
                w.stop()
