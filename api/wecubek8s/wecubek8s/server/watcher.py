# coding=utf-8
from __future__ import absolute_import
import logging
import time
import signal
import threading
from threading import Event
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from talos.core import config
from talos.core import utils

from wecubek8s.apps.model import api
from wecubek8s.common import wecube

LOG = logging.getLogger(__name__)
CONF = config.CONF

# WeCube 客户端缓存（避免重复创建和登录）
_wecube_client = None
_wecube_client_lock = threading.Lock()
_wecube_client_last_login = 0
_wecube_client_token_ttl = 3600  # Token 有效期 1 小时


def get_wecube_client():
    """获取 WeCube 客户端（复用客户端，避免重复登录）"""
    global _wecube_client, _wecube_client_last_login
    
    with _wecube_client_lock:
        current_time = time.time()
        # 如果客户端不存在或 token 可能已过期，重新创建
        if _wecube_client is None or (current_time - _wecube_client_last_login) > _wecube_client_token_ttl:
            LOG.info('Creating new WeCube client and logging in...')
            _wecube_client = wecube.WeCubeClient(CONF.wecube.base_url, None)
            _wecube_client.login_subsystem()
            _wecube_client_last_login = current_time
        return _wecube_client


def notify_pod(event, cluster_id, data):
    """通知 WeCube 编排引擎 Pod 事件"""
    LOG.info('event: %s from cluster: %s with data: %s', event, cluster_id, data)
    
    try:
        operation_key = None
        if event == 'POD.ADDED' and CONF.notify.pod_added:
            operation_key = CONF.notify.pod_added
        elif event == 'POD.DELETED' and CONF.notify.pod_deleted:
            operation_key = CONF.notify.pod_deleted
        
        if not operation_key:
            LOG.debug('No operation key configured for event: %s, skipping notification', event)
            return
        
        # 获取复用的客户端
        client = get_wecube_client()
        
        try:
            client.post(
                client.build_url('/platform/v1/operation-events'), {
                    "eventSeqNo": utils.generate_prefix_uuid("kubernetes-pod-"),
                    "eventType": event,
                    "sourceSubSystem": CONF.wecube.sub_system_code,
                    "operationKey": operation_key,
                    "operationData": data['id'],
                    "operationUser": "plugin-kubernetes-watcher"
                })
            LOG.info('Successfully notified WeCube about %s event for pod: %s', event, data.get('name', data['id']))
        except Exception as e:
            # Token 可能过期，重置客户端并重试一次
            LOG.warning('Failed to notify WeCube, token may be expired. Retrying with new login: %s', str(e))
            global _wecube_client
            _wecube_client = None
            
            # 重试一次
            client = get_wecube_client()
            client.post(
                client.build_url('/platform/v1/operation-events'), {
                    "eventSeqNo": utils.generate_prefix_uuid("kubernetes-pod-"),
                    "eventType": event,
                    "sourceSubSystem": CONF.wecube.sub_system_code,
                    "operationKey": operation_key,
                    "operationData": data['id'],
                    "operationUser": "plugin-kubernetes-watcher"
                })
            LOG.info('Successfully notified WeCube on retry for pod: %s', data.get('name', data['id']))
    
    except Exception as e:
        LOG.error('Failed to notify pod event: %s, pod: %s', event, data.get('name', data['id']))
        LOG.exception(e)


def watch_pod(cluster, event_stop):
    """监听单个集群的 Pod 事件（带指数退避重试）"""
    retry_delay = 0.5  # 初始延迟 0.5 秒
    max_retry_delay = 60  # 最大延迟 60 秒
    
    while not event_stop.is_set():
        try:
            api.Pod().watch(cluster, event_stop, notify_pod)
            retry_delay = 0.5  # 成功后重置延迟
        except Exception as e:
            LOG.error('Exception raised while watching pod from cluster %s', cluster.get('name', cluster['id']))
            LOG.exception(e)
            
            # 指数退避：0.5s -> 1s -> 2s -> 4s -> 8s -> ... -> 60s
            if not event_stop.is_set():
                LOG.info('Retrying in %s seconds...', retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)


def cluster_equal(cluster1, cluster2):
    """比较两个集群配置是否相同（只比较关键字段）"""
    # 只比较影响 watch 连接的关键字段
    key_fields = ['api_server', 'token']
    for field in key_fields:
        if cluster1.get(field) != cluster2.get(field):
            return False
    return True


def main():
    """Watcher 主循环（带优雅关闭和异常处理）"""
    LOG.info('Starting Kubernetes Pod Watcher')
    # 优化：减少最大线程数，避免系统线程耗尽
    # 每个集群一个watcher线程，通常不会超过20个集群
    pool = PoolExecutor(max_workers=20)
    cluster_mapping = {}  # 修正拼写：maping -> mapping
    shutdown_flag = Event()
    
    # 注册信号处理器（优雅关闭）
    def signal_handler(signum, frame):
        LOG.info('Received shutdown signal (%s), stopping watcher...', signum)
        shutdown_flag.set()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    LOG.info('Watcher started successfully. Press Ctrl+C to stop.')
    
    while not shutdown_flag.is_set():
        try:
            # 从数据库读取最新的集群列表
            latest_clusters = api.db_resource.Cluster().list()
            latest_cluster_mapping = dict(
                zip([cluster['id'] for cluster in latest_clusters], 
                    [cluster for cluster in latest_clusters]))
            
            watching_cluster_ids = set(cluster_mapping.keys())
            latest_cluster_ids = set(latest_cluster_mapping.keys())
            new_cluster_ids = latest_cluster_ids - watching_cluster_ids
            del_cluster_ids = watching_cluster_ids - latest_cluster_ids
            mod_cluster_ids = latest_cluster_ids & watching_cluster_ids
            
            # 处理新增的集群
            if new_cluster_ids:
                for cluster_id in new_cluster_ids:
                    cluster = latest_cluster_mapping[cluster_id]
                    LOG.info('Starting watch for new cluster: %s (%s)', 
                            cluster.get('name', cluster_id), cluster_id)
                    event_stop = Event()
                    pool.submit(watch_pod, cluster, event_stop)
                    cluster_mapping[cluster_id] = (cluster, event_stop)
            
            # 处理删除的集群
            if del_cluster_ids:
                for cluster_id in del_cluster_ids:
                    cluster, event_stop = cluster_mapping[cluster_id]
                    LOG.info('Stopping watch for deleted cluster: %s (%s)', 
                            cluster.get('name', cluster_id), cluster_id)
                    event_stop.set()
                    del cluster_mapping[cluster_id]
            
            # 处理修改的集群
            if mod_cluster_ids:
                for cluster_id in mod_cluster_ids:
                    cluster, event_stop = cluster_mapping[cluster_id]
                    latest_cluster = latest_cluster_mapping[cluster_id]
                    if not cluster_equal(latest_cluster, cluster):
                        LOG.info('Restarting watch for modified cluster: %s (%s)', 
                                cluster.get('name', cluster_id), cluster_id)
                        # 停止旧的监听
                        event_stop.set()
                        del cluster_mapping[cluster_id]
                        # 启动新的监听
                        event_stop = Event()
                        pool.submit(watch_pod, latest_cluster, event_stop)
                        cluster_mapping[cluster_id] = (latest_cluster, event_stop)
        
        except Exception as e:
            LOG.error('Error in watcher main loop: %s', str(e))
            LOG.exception(e)
            # 出错后等待 5 秒再重试，避免疯狂重试
            if not shutdown_flag.is_set():
                LOG.info('Retrying in 5 seconds...')
                time.sleep(5)
                continue
        
        # 正常情况下每秒检查一次
        time.sleep(1)
    
    # 优雅关闭
    LOG.info('Shutting down watcher...')
    LOG.info('Stopping all cluster watchers...')
    for cluster_id, (cluster, event_stop) in cluster_mapping.items():
        LOG.info('Stopping watch for cluster: %s', cluster.get('name', cluster_id))
        event_stop.set()
    
    LOG.info('Waiting for all threads to complete (timeout: 30s)...')
    pool.shutdown(wait=True)
    LOG.info('Watcher stopped successfully')


if __name__ == '__main__':
    main()
