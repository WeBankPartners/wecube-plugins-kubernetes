# coding=utf-8
from __future__ import absolute_import
import logging
import os
import time
import signal
import threading
from threading import Event
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from talos.core import config
from talos.core import utils

# 初始化配置和数据库（必须在使用 CONF 和数据库之前）
# 使用 talos.server.base.initialize_server 确保数据库池正确初始化
from talos.server import base as talos_base
print("[WATCHER] Initializing server components...", flush=True)
try:
    # 调用 talos 的初始化逻辑（虽然不使用返回的 application 对象）
    # 这会正确初始化配置、数据库池等核心组件
    _ = talos_base.initialize_server(
        'wecubek8s',
        os.environ.get('WECUBEK8S_CONF', '/etc/wecubek8s/wecubek8s.conf'),
        conf_dir=os.environ.get('WECUBEK8S_CONF_DIR', '/etc/wecubek8s/wecubek8s.conf.d')
    )
    print("[WATCHER] Server components initialized successfully", flush=True)
except Exception as e:
    print(f"[WATCHER] Server initialization warning: {e}", flush=True)
    import traceback
    traceback.print_exc()
    # 如果 initialize_server 失败，至少尝试初始化配置
    config.setup(os.environ.get('WECUBEK8S_CONF', '/etc/wecubek8s/wecubek8s.conf'),
                 dir_path=os.environ.get('WECUBEK8S_CONF_DIR', '/etc/wecubek8s/wecubek8s.conf.d'))

# 预热数据库连接（与 wsgi_server.py 保持一致）
# 这一步非常关键：避免在多线程环境下首次创建连接导致的线程安全问题
print("[WATCHER] Warming up database connection...", flush=True)
try:
    from talos.db import crud
    # 创建一个测试查询触发连接池初始化
    test_engine = crud.get_engine()
    conn = test_engine.connect()
    conn.close()
    print("[WATCHER] Database connection warm-up completed successfully", flush=True)
except Exception as e:
    # 预热失败记录日志，但不影响启动（让后续代码尝试连接）
    print(f"[WATCHER] Database connection warm-up failed (will retry later): {e}", flush=True)
    import traceback
    traceback.print_exc()

from wecubek8s.apps.model import api
from wecubek8s.common import wecube
from wecubek8s.server import base as wecubek8s_base

LOG = logging.getLogger(__name__)
CONF = config.CONF

# WeCube 客户端缓存（避免重复创建和登录）
_wecube_client = None
_wecube_client_lock = threading.Lock()
_wecube_client_last_login = 0
_wecube_client_token_ttl = 3600  # Token 有效期 1 小时

# CMDB 客户端缓存（避免重复创建）
_cmdb_client = None
_cmdb_client_lock = threading.Lock()


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


def get_cmdb_client():
    """获取 CMDB 客户端（复用客户端）"""
    global _cmdb_client
    
    with _cmdb_client_lock:
        if _cmdb_client is None:
            try:
                from wecubek8s.common import wecmdb
                
                cmdb_server = CONF.wecube.base_url
                if not cmdb_server:
                    LOG.warning('CMDB base_url not configured')
                    return None
                
                LOG.info('Creating CMDB client for server: %s', cmdb_server)
                _cmdb_client = wecmdb.EntityClient(cmdb_server)
            except Exception as e:
                LOG.error('Failed to create CMDB client: %s', str(e))
                return None
        
        return _cmdb_client


def query_host_resource_guid(cmdb_client, pod_host_ip):
    """查询 host_resource 的 GUID（根据 IP 地址）"""
    if not cmdb_client or not pod_host_ip:
        return None
    
    try:
        query_data = {
            "criteria": {
                "attrName": "ip_address",
                "op": "eq",
                "condition": pod_host_ip
            }
        }
        
        LOG.debug('Querying host_resource from CMDB for IP: %s', pod_host_ip)
        response = cmdb_client.query('wecmdb', 'host_resource', query_data)
        
        if response and response.get('data') and len(response['data']) > 0:
            host_resource_guid = response['data'][0].get('guid')
            if host_resource_guid:
                LOG.info('Found host_resource GUID: %s for IP: %s', host_resource_guid, pod_host_ip)
                return host_resource_guid
            else:
                LOG.warning('host_resource record found but no guid field for IP: %s', pod_host_ip)
        else:
            LOG.warning('No host_resource found in CMDB for IP: %s', pod_host_ip)
    except Exception as e:
        LOG.error('Failed to query host_resource from CMDB for IP %s: %s', pod_host_ip, str(e))
    
    return None


def sync_pod_to_cmdb_on_added(pod_data):
    """Pod 新增时同步到 CMDB
    
    Returns:
        str: CMDB 中 Pod 记录的 GUID，失败时返回 None
    """
    cmdb_client = get_cmdb_client()
    if not cmdb_client:
        LOG.warning('CMDB client not available, skipping pod add sync')
        return None
    
    try:
        pod_name = pod_data.get('name')
        pod_id = pod_data.get('id')  # K8s Pod UID
        pod_host_ip = pod_data.get('host_ip')
        app_instance_id = pod_data.get('statefulset_id') or pod_data.get('deployment_id')
        
        if not pod_name or not pod_id:
            LOG.warning('Pod name or ID missing, skipping CMDB sync: %s', pod_data)
            return None
        
        LOG.info('Syncing POD.ADDED to CMDB: pod=%s, id=%s, host_ip=%s', 
                 pod_name, pod_id, pod_host_ip or 'N/A')
        
        # 1. 查询 CMDB 中是否已存在该 Pod（通过 code 字段查询）
        query_data = {
            "criteria": {
                "attrName": "code",
                "op": "eq",
                "condition": pod_name
            }
        }
        
        cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
        
        # 2. 如果存在则更新，不存在则创建
        if cmdb_response and cmdb_response.get('data') and len(cmdb_response['data']) > 0:
            # Pod 已存在，更新 asset_id 和 host_resource
            existing_pod = cmdb_response['data'][0]
            pod_guid = existing_pod.get('guid')
            
            if not pod_guid:
                LOG.warning('CMDB pod record has no guid, cannot update: %s', pod_name)
                return None
            
            update_data = {
                'guid': pod_guid,
                'asset_id': pod_id
            }
            
            # 查询并关联 host_resource
            if pod_host_ip:
                host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                if host_resource_guid:
                    update_data['host_resource'] = host_resource_guid
                    LOG.info('Updating pod %s with host_resource GUID: %s (IP: %s)', 
                            pod_name, host_resource_guid, pod_host_ip)
            
            update_response = cmdb_client.update('wecmdb', 'pod', [update_data])
            LOG.info('Successfully updated pod in CMDB: %s (asset_id: %s, guid: %s)', 
                    pod_name, pod_id, pod_guid)
            return pod_guid
        else:
            # Pod 不存在，创建新记录
            create_data = {
                'code': pod_name,
                'asset_id': pod_id
            }
            
            # 关联 app_instance（StatefulSet/Deployment）
            if app_instance_id:
                create_data['app_instance'] = app_instance_id
                LOG.info('Creating pod %s with app_instance: %s', pod_name, app_instance_id)
            
            # 查询并关联 host_resource
            if pod_host_ip:
                host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                if host_resource_guid:
                    create_data['host_resource'] = host_resource_guid
                    LOG.info('Creating pod %s with host_resource GUID: %s (IP: %s)', 
                            pod_name, host_resource_guid, pod_host_ip)
            
            create_response = cmdb_client.create('wecmdb', 'pod', [create_data])
            
            # 从创建响应中获取 GUID
            pod_guid = None
            if create_response and create_response.get('data') and len(create_response['data']) > 0:
                pod_guid = create_response['data'][0].get('guid')
            
            if pod_guid:
                LOG.info('Successfully created pod in CMDB: %s (asset_id: %s, guid: %s)', 
                        pod_name, pod_id, pod_guid)
                return pod_guid
            else:
                LOG.warning('Pod created in CMDB but no GUID returned: %s', pod_name)
                return None
    
    except Exception as e:
        LOG.error('Failed to sync POD.ADDED to CMDB for pod %s: %s', 
                 pod_data.get('name', 'unknown'), str(e))
        LOG.exception(e)
        return None


def sync_pod_to_cmdb_on_deleted(pod_data):
    """Pod 删除时同步到 CMDB（更新状态或删除记录）"""
    cmdb_client = get_cmdb_client()
    if not cmdb_client:
        LOG.warning('CMDB client not available, skipping pod delete sync')
        return
    
    try:
        pod_name = pod_data.get('name')
        pod_id = pod_data.get('id')  # K8s Pod UID
        
        if not pod_name:
            LOG.warning('Pod name missing, skipping CMDB sync: %s', pod_data)
            return
        
        LOG.info('Syncing POD.DELETED to CMDB: pod=%s, id=%s', pod_name, pod_id)
        
        # 查询 CMDB 中的 Pod 记录（通过 code 字段查询）
        query_data = {
            "criteria": {
                "attrName": "code",
                "op": "eq",
                "condition": pod_name
            }
        }
        
        cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
        
        if cmdb_response and cmdb_response.get('data') and len(cmdb_response['data']) > 0:
            existing_pod = cmdb_response['data'][0]
            pod_guid = existing_pod.get('guid')
            existing_asset_id = existing_pod.get('asset_id')
            
            if not pod_guid:
                LOG.warning('CMDB pod record has no guid, cannot update: %s', pod_name)
                return
            
            # 只有当 asset_id 匹配时才更新（避免误删新建的 Pod）
            if existing_asset_id != pod_id:
                LOG.warning('Pod %s asset_id mismatch (CMDB: %s, K8s: %s), skipping delete sync', 
                           pod_name, existing_asset_id, pod_id)
                return
            
            # 直接删除 CMDB 中的 Pod 记录
            cmdb_client.delete('wecmdb', 'pod', [pod_guid])
            LOG.info('Successfully deleted pod from CMDB: %s (guid: %s)', pod_name, pod_guid)
        else:
            LOG.warning('Pod %s not found in CMDB, no action needed for deletion', pod_name)
    
    except Exception as e:
        LOG.error('Failed to sync POD.DELETED to CMDB for pod %s: %s', 
                 pod_data.get('name', 'unknown'), str(e))
        LOG.exception(e)


def notify_pod(event, cluster_id, data):
    """通知 WeCube 编排引擎 Pod 事件（先同步 CMDB，再发送通知）"""
    LOG.info('=' * 80)
    LOG.info('notify_pod started - event: %s, cluster: %s', event, cluster_id)
    LOG.info('Pod details - name: %s, namespace: %s, id: %s', 
             data.get('name', 'N/A'), data.get('namespace', 'N/A'), data.get('id', 'N/A'))
    LOG.info('Full pod data: %s', data)
    
    try:
        # ===== 第一步：同步 CMDB（在通知之前） =====
        LOG.info('-' * 40)
        LOG.info('Step 1: Start CMDB synchronization')
        
        pod_cmdb_guid = None  # 用于存储 CMDB 中 Pod 的 GUID
        
        if event == 'POD.ADDED':
            LOG.info('Event type: POD.ADDED - will create record in CMDB')
            LOG.info('Calling sync_pod_to_cmdb_on_added with pod_id: %s', data.get('id'))
            pod_cmdb_guid = sync_pod_to_cmdb_on_added(data)
            
            if pod_cmdb_guid:
                LOG.info('CMDB sync completed successfully for POD.ADDED - GUID: %s', pod_cmdb_guid)
            else:
                LOG.warning('CMDB sync completed but no GUID returned for POD.ADDED')
            
        elif event == 'POD.DELETED':
            LOG.info('Event type: POD.DELETED - will delete record from CMDB')
            LOG.info('Calling sync_pod_to_cmdb_on_deleted with pod_id: %s', data.get('id'))
            sync_pod_to_cmdb_on_deleted(data)
            LOG.info('CMDB sync completed successfully for POD.DELETED')
        else:
            LOG.warning('Unknown event type: %s, skipping CMDB sync', event)
        
        # ===== 第二步：发送 WeCube 通知 =====
        LOG.info('-' * 40)
        LOG.info('Step 2: Check if WeCube notification is needed')
        
        # 只在 POD.ADDED 时触发通知，POD.DELETED 时不触发
        if event == 'POD.DELETED':
            LOG.info('POD.DELETED event detected - skipping WeCube notification (CMDB-only mode)')
            LOG.info('notify_pod completed successfully - CMDB updated, no notification sent')
            LOG.info('=' * 80)
            return
        
        if event == 'POD.ADDED':
            LOG.info('POD.ADDED event detected - checking configuration')
            if not CONF.notify.pod_added:
                LOG.warning('No operation_key configured for POD.ADDED in config file')
                LOG.warning('Config path: notify.pod_added is empty or not set')
                LOG.info('Skipping WeCube notification due to missing configuration')
                LOG.info('=' * 80)
                return
            operation_key = CONF.notify.pod_added
            LOG.info('Operation key found in config: %s', operation_key)
        else:
            LOG.warning('Unknown event type: %s, cannot send notification', event)
            LOG.info('=' * 80)
            return
        
        LOG.info('Preparing to send notification to WeCube')
        LOG.info('WeCube endpoint: %s', CONF.wecube.server)
        LOG.info('Sub-system code: %s', CONF.wecube.sub_system_code)
        
        # 检查是否获取到了 CMDB GUID
        if not pod_cmdb_guid:
            LOG.error('Cannot send notification: CMDB GUID is required but not available')
            LOG.error('Pod name: %s, K8s ID: %s', data.get('name'), data.get('id'))
            LOG.info('=' * 80)
            return
        
        LOG.info('Using CMDB Pod GUID for notification: %s', pod_cmdb_guid)
        
        # 获取复用的客户端
        LOG.debug('Getting WeCube client (reusing existing or creating new)')
        client = get_wecube_client()
        LOG.debug('WeCube client obtained successfully')
        
        # 构建通知数据（使用 CMDB 中的 Pod GUID 而不是 K8s Pod ID）
        event_seq_no = utils.generate_prefix_uuid("kubernetes-pod-")
        notification_data = {
            "eventSeqNo": event_seq_no,
            "eventType": event,
            "sourceSubSystem": CONF.wecube.sub_system_code,
            "operationKey": operation_key,
            "operationData": pod_cmdb_guid,  # 使用 CMDB 中的 Pod GUID
            "operationUser": "plugin-kubernetes-watcher"
        }
        LOG.info('Notification payload: %s', notification_data)
        LOG.info('operationData is CMDB Pod GUID: %s (not K8s Pod ID: %s)', 
                pod_cmdb_guid, data.get('id'))
        
        try:
            url = client.build_url('/platform/v1/operation-events')
            LOG.info('Sending POST request to: %s', url)
            
            client.post(url, notification_data)
            
            LOG.info('✅ Successfully notified WeCube about %s event', event)
            LOG.info('Pod: %s (id: %s)', data.get('name', 'N/A'), data['id'])
            LOG.info('Event sequence number: %s', event_seq_no)
            
        except Exception as e:
            # Token 可能过期，重置客户端并重试一次
            LOG.warning('❌ First attempt failed: %s', str(e))
            LOG.warning('Error type: %s', type(e).__name__)
            LOG.warning('This might be due to token expiration, will retry with fresh login')
            
            global _wecube_client
            _wecube_client = None
            LOG.info('WeCube client cache cleared, obtaining new client')
            
            # 重试一次
            client = get_wecube_client()
            LOG.info('New WeCube client obtained, retrying notification')
            
            # 生成新的 eventSeqNo
            event_seq_no = utils.generate_prefix_uuid("kubernetes-pod-")
            notification_data["eventSeqNo"] = event_seq_no
            LOG.info('Retry with new event sequence number: %s', event_seq_no)
            
            url = client.build_url('/platform/v1/operation-events')
            LOG.info('Sending retry POST request to: %s', url)
            
            client.post(url, notification_data)
            
            LOG.info('✅ Successfully notified WeCube on retry')
            LOG.info('Pod: %s (id: %s)', data.get('name', 'N/A'), data['id'])
            LOG.info('Event sequence number: %s', event_seq_no)
        
        LOG.info('notify_pod completed successfully - CMDB updated and notification sent')
        LOG.info('=' * 80)
    
    except Exception as e:
        LOG.error('=' * 80)
        LOG.error('❌ FATAL ERROR in notify_pod')
        LOG.error('Event: %s, Cluster: %s', event, cluster_id)
        LOG.error('Pod name: %s, Pod ID: %s', data.get('name', 'N/A'), data.get('id', 'N/A'))
        LOG.error('Error type: %s', type(e).__name__)
        LOG.error('Error message: %s', str(e))
        LOG.exception(e)
        LOG.error('=' * 80)


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
