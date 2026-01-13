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
        statefulset_name = None  # StatefulSet 名称（用于 watcher 查询 annotation）
        if item.metadata.owner_references:
            for owner in item.metadata.owner_references:
                if owner.controller:
                    if owner.kind == 'ReplicaSet':
                        controll_by = owner.uid
                    elif owner.kind == 'StatefulSet':
                        statefulset_id = owner.uid
                        statefulset_name = owner.name  # 保存 StatefulSet 名称
                    # 可以继续添加其他控制器类型（如 DaemonSet、Job 等）
        
        # 从 annotations 中提取创建者的 token（用于 watcher 访问 CMDB）
        # 优先级1：从 Pod 自己的 annotations 中读取（直接通过 apply API 创建的 Pod）
        creator_token = None
        if item.metadata.annotations:
            creator_token = item.metadata.annotations.get('wecube.io/creator-token')
            if creator_token:
                LOG.debug('Extracted creator token from Pod annotations (prefix: %s...)', 
                         creator_token[:20])
        
        # 优先级2：如果 Pod 没有 creator_token，从父资源的 annotations 中继承
        # 这适用于"漂移"场景：Pod 通过 StatefulSet 扩缩容、重启等自动创建
        if not creator_token and item.metadata.owner_references:
            try:
                k8s_client = cls.cluster_client(cluster)
                for owner in item.metadata.owner_references:
                    if owner.controller:  # 只从控制器（controller）继承
                        owner_obj = None
                        if owner.kind == 'StatefulSet':
                            owner_obj = k8s_client.read_namespaced_stateful_set(
                                owner.name, item.metadata.namespace)
                        elif owner.kind == 'Deployment':
                            owner_obj = k8s_client.read_namespaced_deployment(
                                owner.name, item.metadata.namespace)
                        elif owner.kind == 'ReplicaSet':
                            owner_obj = k8s_client.read_namespaced_replica_set(
                                owner.name, item.metadata.namespace)
                        # 可以继续添加其他控制器类型
                        
                        if owner_obj and owner_obj.metadata.annotations:
                            creator_token = owner_obj.metadata.annotations.get('wecube.io/creator-token')
                            if creator_token:
                                LOG.info('Inherited creator token from %s %s (prefix: %s...)',
                                        owner.kind, owner.name, creator_token[:20])
                                break  # 找到 token 就停止
            except Exception as e:
                LOG.warning('Failed to inherit creator token from owner: %s', str(e))
        
        # 使用 cluster_id + pod_uid 作为全局唯一标识，防止重复集群配置导致的重复创建
        asset_id = f"{cluster['id']}_{item.metadata.uid}" if item.metadata.uid else None
        
        # 提取所有 annotations（用于 watcher 判断 Pod 创建来源等信息）
        annotations = dict(item.metadata.annotations) if item.metadata.annotations else {}
        
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
            'statefulset_name': statefulset_name,  # StatefulSet 名称（用于从 K8s 读取 annotation）
            'deployment_id': None,
            'correlation_id': correlation_id,
            'node_id': item.spec.node_name,
            'cluster_id': cluster["id"],
            'creator_token': creator_token,  # 新增：创建者的 token
            'annotations': annotations,  # 新增：完整的 annotations（用于判断创建来源等）
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

    def watch(self, cluster, event_stop, notify, start_resource_version=None):
        """监听 Pod 事件，带心跳保活和资源版本续传
        
        Args:
            cluster: 集群配置
            event_stop: 停止事件标志
            notify: 事件通知回调函数
            start_resource_version: 起始资源版本（用于重连时续传，None 表示从当前版本开始）
        
        Returns:
            最后一次收到的 resource_version，用于重连时续传
        """
        k8s_client = self.cluster_client(cluster)
        w = watch.Watch()
        cluster_name = cluster.get('name', cluster['id'])
        last_resource_version = start_resource_version
        
        LOG.info('Starting watch for cluster %s', cluster_name)
        
        try:
            # 如果没有提供起始版本，获取当前的 resource_version
            if start_resource_version is None:
                pod_list = k8s_client.core_client.list_pod_for_all_namespaces(limit=1)
                last_resource_version = pod_list.metadata.resource_version
                LOG.info('Starting watch from current resource_version: %s (skipping existing pods)', 
                        last_resource_version)
            else:
                LOG.info('Resuming watch from saved resource_version: %s', start_resource_version)
            
            # 事件计数器（用于统计和日志）
            event_count = 0
            
            # 设置超时为 2.5 分钟，主动在 API Server 超时前重连（避免 5 分钟超时）
            # 策略：定期重连（每 2.5 分钟），重连时自动从 last_resource_version 续传
            # timeout_seconds: API Server 端超时时间（150 秒 = 2.5 分钟）
            # _request_timeout: HTTP 客户端（urllib3）超时时间 (connect_timeout, read_timeout)
            #   - connect_timeout=10: 连接超时 10 秒
            #   - read_timeout=145: 读取超时 145 秒（略小于 timeout_seconds，客户端主动在服务器超时前结束）
            for event in w.stream(
                k8s_client.core_client.list_pod_for_all_namespaces,
                resource_version=last_resource_version,
                timeout_seconds=150,  # 2.5 分钟
                _request_timeout=(10, 145)  # 连接 10s，读取 145s（比 timeout_seconds 短 5 秒）
            ):
                event_type = event.get('type')
                pod_obj = event.get('object')
                
                if not pod_obj:
                    LOG.warning('Received watch event without object: %s', event)
                    continue
                
                # 更新最后的 resource_version（用于重连续传）
                if hasattr(pod_obj.metadata, 'resource_version') and pod_obj.metadata.resource_version:
                    last_resource_version = pod_obj.metadata.resource_version
                
                pod_name = pod_obj.metadata.name if pod_obj.metadata else 'unknown'
                pod_uid = pod_obj.metadata.uid if pod_obj.metadata else 'unknown'
                event_count += 1
                
                LOG.debug('Watch event #%d: type=%s, pod=%s, uid=%s, rv=%s', 
                         event_count, event_type, pod_name, pod_uid, last_resource_version)
                
                if event_type == 'ADDED':
                    LOG.info('Pod ADDED event detected: %s (uid: %s)', pod_name, pod_uid)
                    notify('POD.ADDED', cluster['id'], self.to_dict(cluster, pod_obj))
                elif event_type == 'DELETED':
                    LOG.info('Pod DELETED event detected: %s (uid: %s)', pod_name, pod_uid)
                    notify('POD.DELETED', cluster['id'], self.to_dict(cluster, pod_obj))
                elif event_type == 'MODIFIED':
                    LOG.debug('Pod MODIFIED event (not notifying): %s', pod_name)
                elif event_type == 'ERROR':
                    # 处理 ERROR 事件（通常表示资源版本过期或其他问题）
                    LOG.warning('Watch ERROR event for pod %s: %s', pod_name, pod_obj)
                    # 重置 resource_version，从当前版本重新开始
                    last_resource_version = None
                    raise Exception(f'Watch stream received ERROR event for pod {pod_name}')
                else:
                    LOG.warning('Unknown watch event type: %s for pod %s', event_type, pod_name)
                
                # 检查是否需要停止
                if event_stop.is_set():
                    LOG.info('Watch stop requested for cluster %s', cluster_name)
                    w.stop()
                    break
            
            # 正常结束（通常是超时重连）
            LOG.info('Watch stream ended for cluster %s (processed %d events)', cluster_name, event_count)
            return last_resource_version
            
        except Exception as e:
            LOG.error('Error in watch stream for cluster %s: %s', cluster_name, str(e))
            # 返回最后的 resource_version，供重连时使用
            raise
        finally:
            w.stop()
            LOG.info('Watch stopped for cluster %s (last rv: %s)', cluster_name, last_resource_version)
