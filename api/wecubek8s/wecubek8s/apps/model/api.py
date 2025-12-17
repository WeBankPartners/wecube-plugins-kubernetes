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

    def _ensure_api_server_protocol(self, api_server):
        """确保 api_server 有正确的协议前缀"""
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            LOG.warning('api_server missing protocol prefix, auto-adding https://: %s', api_server)
            return 'https://' + api_server
        return api_server
    
    def cluster_client(self, cluster):
        api_server = self._ensure_api_server_protocol(cluster['api_server'])
        k8s_auth = k8s.AuthToken(api_server, cluster['token'])
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
        
        # 使用 cluster_id + uid 作为全局唯一标识
        asset_id = f"{cluster['id']}_{item.metadata.uid}" if item.metadata.uid else None
        
        result = {
            'id': item.metadata.uid,
            'asset_id': asset_id,
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
        statefulset_id = None
        if item.metadata.owner_references:
            for owner in item.metadata.owner_references:
                if owner.controller:
                    if owner.kind == 'ReplicaSet':
                        controll_by = owner.uid
                    elif owner.kind == 'StatefulSet':
                        statefulset_id = owner.uid
                    # 可以继续添加其他控制器类型（如 DaemonSet、Job 等）
        
        # 使用 cluster_id + pod_uid 作为全局唯一标识，防止重复集群配置导致的重复创建
        asset_id = f"{cluster['id']}_{item.metadata.uid}" if item.metadata.uid else None
        
        result = {
            'id': item.metadata.uid,
            'asset_id': asset_id,  # 全局唯一标识（cluster_id + pod_uid）
            'name': item.metadata.name,
            'displayName': f'{cluster["name"]}-{item.metadata.namespace}-{item.metadata.name}',
            'namespace': item.metadata.namespace,
            'ip_address': item.status.pod_ip,
            'host_ip': item.status.host_ip,
            'replicaset_id': controll_by,
            'statefulset_id': statefulset_id,
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
        w = watch.Watch()
        
        LOG.info('Starting watch for cluster %s', cluster.get('name', cluster['id']))
        
        try:
            # 获取当前的 resource_version，用于跳过现有的 Pod
            # 只监听从此刻开始的新增和删除事件，不处理已存在的 Pod
            pod_list = k8s_client.core_client.list_pod_for_all_namespaces(limit=1)
            resource_version = pod_list.metadata.resource_version
            LOG.info('Starting watch from resource_version: %s (skipping existing pods)', resource_version)
            
            for event in w.stream(
                k8s_client.core_client.list_pod_for_all_namespaces,
                resource_version=resource_version
            ):
                event_type = event.get('type')
                pod_obj = event.get('object')
                
                if not pod_obj:
                    LOG.warning('Received watch event without object: %s', event)
                    continue
                
                pod_name = pod_obj.metadata.name if pod_obj.metadata else 'unknown'
                pod_uid = pod_obj.metadata.uid if pod_obj.metadata else 'unknown'
                
                LOG.debug('Watch event: type=%s, pod=%s, uid=%s', event_type, pod_name, pod_uid)
                
                if event_type == 'ADDED':
                    # 触发 POD.ADDED 通知（移除时间过滤以避免丢失重连期间的事件）
                    # CMDB 同步函数内部会处理去重（通过 code 字段查询已存在的 Pod）
                    LOG.info('Pod ADDED event detected: %s (uid: %s)', pod_name, pod_uid)
                    notify('POD.ADDED', cluster['id'], self.to_dict(cluster, pod_obj))
                elif event_type == 'DELETED':
                    # 触发 POD.DELETED 通知
                    LOG.info('Pod DELETED event detected: %s (uid: %s)', pod_name, pod_uid)
                    notify('POD.DELETED', cluster['id'], self.to_dict(cluster, pod_obj))
                elif event_type == 'MODIFIED':
                    # MODIFIED 事件不触发通知，避免噪音
                    LOG.debug('Pod MODIFIED event (not notifying): %s', pod_name)
                else:
                    LOG.warning('Unknown watch event type: %s for pod %s', event_type, pod_name)
                
                if event_stop.is_set():
                    LOG.info('Watch stop requested for cluster %s', cluster.get('name', cluster['id']))
                    w.stop()
                    break
        except Exception as e:
            LOG.error('Error in watch stream for cluster %s: %s', cluster.get('name', cluster['id']), str(e))
            raise
        finally:
            w.stop()
            LOG.info('Watch stopped for cluster %s', cluster.get('name', cluster['id']))
