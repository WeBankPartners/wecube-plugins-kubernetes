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
import urllib3.exceptions

# ⚠️ 关键：必须在初始化配置之前导入，以便注册配置拦截器
from wecubek8s.server import base as wecubek8s_base

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

# 事件去重缓存（防止短时间内重复处理同一个事件）
# Key: (pod_uid, event_type), Value: timestamp
# 多 watcher 去重策略：
# 1. 进程内去重：使用此缓存，避免同一 watcher 重复处理（K8s watch 可能推送重复事件）
# 2. 跨进程去重：依赖 CMDB 的唯一性约束（code 字段）+ 幂等性操作
#    - 创建操作：CMDB code 唯一约束，只有一个 watcher 创建成功，其他失败后查询已存在记录
#    - 更新操作：幂等的，多个 watcher 同时更新同一记录不会产生副作用
# 3. 时间窗口：30秒内的重复事件会被当前 watcher 忽略（避免频繁 CMDB 操作）
_event_dedup_cache = {}
_event_dedup_lock = threading.Lock()
_event_dedup_window = 30  # 去重时间窗口：30秒（增加到30秒以应对多 watcher 场景）

# 预期 Pod 创建缓存（用于区分 API 主动创建 vs Pod 漂移/崩溃重启）
# Key: (cluster_id, namespace, pod_name), Value: {'timestamp': float, 'source': 'statefulset_apply'}
# 当通过 API 创建 StatefulSet 时，会将预期创建的 Pod 加入此缓存
# Watcher 收到 POD.ADDED 时，如果 Pod 在缓存中 → 跳过通知（用户主动创建）
#                         如果 Pod 不在缓存中 → 执行通知（Pod 漂移或崩溃重启）
_expected_pod_cache = {}
_expected_pod_lock = threading.Lock()
_expected_pod_window = 300  # 预期 Pod 缓存时间窗口：5分钟（StatefulSet 创建 Pod 可能较慢）

# 最近删除的 Pod 缓存（用于检测 Pod 漂移场景）
# Key: (namespace, pod_name), Value: {'timestamp': float, 'guid': str, 'old_asset_id': str, 'host_ip': str, 'cluster_id': str}
# 注意：不再使用 cluster_id 作为 key 的一部分，避免因 cluster_id 配置不一致导致缓存未命中
#       Pod name 在同一命名空间内是唯一的（K8s 保证），足以区分不同的 Pod
# 当 watcher 收到 POD.DELETED 事件并成功删除 CMDB 记录时，将 Pod 信息加入此缓存
# 当 watcher 收到 POD.ADDED 事件时，检查缓存：
#   - 如果同名 Pod 在缓存中（时间窗口内） → 这是 Pod 漂移场景，快速更新 CMDB 记录（无需等待）
#   - 如果同名 Pod 不在缓存中 → 这是新建场景，进入重试循环等待 apply API
# 时间窗口：60秒（足够长以覆盖大多数 Pod 漂移场景，StatefulSet 通常在 Pod 删除后几秒内重建）
_recently_deleted_pods = {}
_recently_deleted_pods_lock = threading.Lock()
_recently_deleted_pods_window = 40  # 最近删除 Pod 缓存时间窗口：60秒


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
    """获取 CMDB 客户端（复用客户端，使用 WeCube 登录后的 token）"""
    global _cmdb_client
    
    with _cmdb_client_lock:
        # 每次都重新创建，使用最新的 WeCube token
        # 因为 WeCube token 可能会更新（定期重新登录）
        try:
            from wecubek8s.common import wecmdb
            
            cmdb_server = CONF.wecube.base_url
            if not cmdb_server:
                LOG.warning('CMDB base_url not configured')
                return None
            
            # 获取 WeCube 客户端（会自动登录并刷新 token）
            wecube_client = get_wecube_client()
            if not wecube_client or not wecube_client.token:
                LOG.error('Failed to get WeCube token for CMDB authentication')
                return None
            
            LOG.info('Creating CMDB client for server: %s with WeCube system token (prefix: %s...)', 
                    cmdb_server, wecube_client.token[:20] if wecube_client.token else 'None')
            _cmdb_client = wecmdb.EntityClient(cmdb_server, wecube_client.token)
        except Exception as e:
            LOG.error('Failed to create CMDB client: %s', str(e))
            return None
        
        return _cmdb_client


def get_cmdb_client_with_fallback(pod_data, operation_name='CMDB operation'):
    """获取CMDB客户端（支持token失效时自动fallback到系统token）
    
    工作流程：
    1. 优先尝试使用creator_token（从Pod annotations读取）
    2. 验证token是否有效（发送测试查询）
    3. 如果token失效（401错误），自动fallback到系统token
    4. 系统token由watcher维护，会自动刷新，永不过期
    
    Args:
        pod_data: Pod数据字典（包含creator_token）
        operation_name: 操作名称（用于日志记录）
    
    Returns:
        tuple: (cmdb_client, token_source)
            - cmdb_client: CMDB客户端实例，失败时返回None
            - token_source: token来源标记 ('creator' 或 'system')
    """
    cmdb_server = CONF.wecube.base_url
    if not cmdb_server:
        LOG.warning('[%s] CMDB base_url not configured', operation_name)
        return None, None
    
    from wecubek8s.common import wecmdb
    
    # ===== 【测试模式】直接使用 system token，跳过 creator_token 逻辑 =====
    LOG.info('[%s] 🧪 TEST MODE: Skipping creator_token, using system token directly', operation_name)
    
    # ===== 步骤1：优先尝试使用creator_token（保持数据隔离）===== 【暂时注释】
    # creator_token = pod_data.get('creator_token')
    # if creator_token:
    #     LOG.info('[%s] Found creator token in Pod annotations (prefix: %s...)', 
    #             operation_name, creator_token[:20])
    #     LOG.info('[%s] Attempting to use creator token for CMDB access...', operation_name)
    #     
    #     try:
    #         # 创建使用creator_token的CMDB客户端
    #         cmdb_client = wecmdb.EntityClient(cmdb_server, creator_token)
    #         
    #         # ===== 步骤2：验证token是否有效（发送轻量级测试查询）=====
    #         # 使用一个不存在的GUID查询，只是为了测试认证是否通过
    #         # 这个查询会很快返回（不涉及实际数据），但能触发认证检查
    #         LOG.debug('[%s] Validating creator token...', operation_name)
    #         test_query = {
    #             "criteria": {
    #                 "attrName": "guid",
    #                 "op": "eq",
    #                 "condition": "test-token-validation-non-existent"
    #             }
    #         }
    #         
    #         try:
    #             cmdb_client.query('wecmdb', 'pod', test_query)
    #             # 查询成功（即使没有数据），说明token有效
    #             LOG.info('[%s] ✅ Creator token is VALID', operation_name)
    #             LOG.info('[%s] Using creator token for CMDB access (maintains data isolation)', 
    #                     operation_name)
    #             return cmdb_client, 'creator'
    #             
    #         except Exception as validation_err:
    #             # 检查是否是认证错误（401 Unauthorized）
    #             error_msg = str(validation_err).lower()
    #             
    #             if '401' in error_msg or 'unauthorized' in error_msg or 'unauthenticated' in error_msg:
    #                 # Token已失效
    #                 LOG.warning('[%s] ⚠️  Creator token is EXPIRED or INVALID (401)', operation_name)
    #                 LOG.warning('[%s] Error details: %s', operation_name, str(validation_err))
    #                 LOG.warning('[%s] This is expected for long-lived Pods (token TTL: 1-2 hours)', 
    #                            operation_name)
    #                 LOG.warning('[%s] Will fallback to system token...', operation_name)
    #                 # 继续到fallback逻辑
    #                 
    #             elif 'forbidden' in error_msg or '403' in error_msg:
    #                 # 权限不足（但token有效）
    #                 LOG.warning('[%s] ⚠️  Creator token is valid but has insufficient permissions (403)', 
    #                            operation_name)
    #                 LOG.warning('[%s] Error details: %s', operation_name, str(validation_err))
    #                 LOG.warning('[%s] Will fallback to system token...', operation_name)
    #                 # 继续到fallback逻辑
    #                 
    #             else:
    #                 # 其他错误（网络问题、CMDB不可用等）
    #                 LOG.warning('[%s] Token validation failed with non-auth error: %s', 
    #                            operation_name, str(validation_err))
    #                 LOG.warning('[%s] Will try to use this token anyway (may be network issue)', 
    #                            operation_name)
    #                 # 返回这个客户端，让调用者处理实际操作中的错误
    #                 return cmdb_client, 'creator'
    #                 
    #     except Exception as client_err:
    #         LOG.error('[%s] Failed to create CMDB client with creator token: %s', 
    #                  operation_name, str(client_err))
    #         LOG.error('[%s] Will fallback to system token...', operation_name)
    #         # 继续到fallback逻辑
    # else:
    #     LOG.info('[%s] No creator token found in Pod annotations', operation_name)
    #     LOG.info('[%s] Will use system token directly', operation_name)
    
    # ===== 步骤3：直接使用系统token（永不过期，自动刷新）=====
    LOG.info('[%s] Using SYSTEM token (WeCube subsystem token)', operation_name)
    LOG.info('[%s] System token has full permissions and auto-refreshes every hour', 
            operation_name)
    
    try:
        wecube_client = get_wecube_client()
        if not wecube_client or not wecube_client.token:
            LOG.error('[%s] ❌ Failed to get WeCube system token', operation_name)
            return None, None
        
        LOG.info('[%s] Creating CMDB client with system token (prefix: %s...)', 
                operation_name, wecube_client.token[:20])
        cmdb_client = wecmdb.EntityClient(cmdb_server, wecube_client.token)
        return cmdb_client, 'system'
        
    except Exception as e:
        LOG.error('[%s] ❌ Failed to create CMDB client with system token: %s', 
                 operation_name, str(e))
        LOG.exception(e)
        return None, None


def mark_expected_pods(cluster_id, namespace, pod_names, source='statefulset_apply'):
    """
    标记预期创建的 Pod（由 API 主动创建，不需要 watcher 通知）
    
    Args:
        cluster_id: 集群 ID
        namespace: 命名空间
        pod_names: Pod 名称列表 ['pod-0', 'pod-1', ...]
        source: 创建来源（默认 'statefulset_apply'）
    """
    with _expected_pod_lock:
        current_time = time.time()
        
        # 清理过期的缓存条目
        expired_keys = [k for k, v in _expected_pod_cache.items() 
                       if current_time - v['timestamp'] > _expected_pod_window]
        for k in expired_keys:
            del _expected_pod_cache[k]
        
        # 标记新的预期 Pod
        for pod_name in pod_names:
            key = (cluster_id, namespace, pod_name)
            _expected_pod_cache[key] = {
                'timestamp': current_time,
                'source': source
            }
        
        LOG.info('🏷️  Marked %d pods as expected from %s: cluster=%s, namespace=%s, pods=%s',
                len(pod_names), source, cluster_id, namespace, pod_names)
        LOG.info('Total expected pods in cache: %d', len(_expected_pod_cache))


def is_expected_pod(cluster_id, namespace, pod_name):
    """
    检查 Pod 是否是预期创建的（如果是，则不需要 watcher 通知）
    
    Returns:
        (bool, dict): (是否预期创建, 缓存信息)
    """
    with _expected_pod_lock:
        key = (cluster_id, namespace, pod_name)
        current_time = time.time()
        
        # 清理过期的缓存条目
        expired_keys = [k for k, v in _expected_pod_cache.items() 
                       if current_time - v['timestamp'] > _expected_pod_window]
        for k in expired_keys:
            del _expected_pod_cache[k]
        
        if key in _expected_pod_cache:
            info = _expected_pod_cache[key]
            time_since_mark = current_time - info['timestamp']
            
            # 返回后从缓存中移除（每个 Pod 只使用一次）
            del _expected_pod_cache[key]
            
            return True, {
                'source': info['source'],
                'time_since_mark': time_since_mark
            }
        
        return False, {}


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


def query_statefulset_app_instance(k8s_client, statefulset_name, namespace):
    """查询 StatefulSet 的 app_instance（用于 Pod 漂移时创建新 Pod 记录）
    
    从 K8s StatefulSet 的 annotations 中读取 app_instance（instanceId），
    而不是从 CMDB 查询（因为 StatefulSet 详情没有存到 CMDB）
    
    Args:
        k8s_client: K8s 客户端
        statefulset_name: StatefulSet 名称
        namespace: 命名空间
    
    Returns:
        str: app_instance 的 GUID（从 annotation 读取），失败时返回 None
    """
    if not k8s_client or not statefulset_name or not namespace:
        return None
    
    try:
        LOG.info('Reading StatefulSet from K8s: %s/%s', namespace, statefulset_name)
        statefulset = k8s_client.get_statefulset(statefulset_name, namespace)
        
        if statefulset and statefulset.metadata:
            annotations = statefulset.metadata.annotations or {}
            app_instance_guid = annotations.get('wecube.io/app-instance')
            
            if app_instance_guid:
                LOG.info('✅ Found app_instance from StatefulSet annotation: %s', app_instance_guid)
                return app_instance_guid
            else:
                LOG.warning('⚠️  StatefulSet found but no wecube.io/app-instance annotation: %s/%s', 
                           namespace, statefulset_name)
                LOG.warning('⚠️  This StatefulSet may have been created before the annotation feature was added')
        else:
            LOG.warning('⚠️  No StatefulSet found in K8s: %s/%s', namespace, statefulset_name)
    except Exception as e:
        LOG.error('❌ Failed to read StatefulSet from K8s: %s', str(e))
        LOG.exception(e)
    
    return None


def test_query_all_pods_from_cmdb(cmdb_client):
    """测试函数：查询 CMDB 中所有 Pod 数据（不加过滤条件）
    
    用途：验证 watcher 的 CMDB 客户端是否能正常访问数据
    """
    LOG.info('='*80)
    LOG.info('🧪 TEST: Querying ALL pods from CMDB (no filter)')
    LOG.info('='*80)
    
    if not cmdb_client:
        LOG.error('❌ TEST FAILED: CMDB client is None')
        return
    
    try:
        # 方法1：不带任何条件，查询所有 pod
        LOG.info('[TEST-Query-1] Attempting to query all pods without any filter...')
        try:
            # 空查询或者使用一个总是为真的条件
            all_pods_response = cmdb_client.query('wecmdb', 'pod', {})
            
            if all_pods_response:
                LOG.info('[TEST-Query-1] ✅ Query successful!')
                LOG.info('[TEST-Query-1] Response status: %s', all_pods_response.get('status', 'N/A'))
                LOG.info('[TEST-Query-1] Response message: %s', all_pods_response.get('message', 'N/A'))
                
                pods_data = all_pods_response.get('data', [])
                pod_count = len(pods_data) if pods_data else 0
                
                LOG.info('[TEST-Query-1] 📊 Total pods found: %d', pod_count)
                
                if pod_count > 0:
                    LOG.info('[TEST-Query-1] 📋 Listing all pods:')
                    for idx, pod in enumerate(pods_data, 1):
                        LOG.info('[TEST-Query-1]   [%d] guid=%s, code=%s, key_name=%s, asset_id=%s, state=%s, app_instance=%s',
                                idx,
                                pod.get('guid', 'N/A'),
                                pod.get('code', 'N/A'),
                                pod.get('key_name', 'N/A'),
                                pod.get('asset_id', 'N/A'),
                                pod.get('state', 'N/A'),
                                pod.get('app_instance', 'N/A'))
                else:
                    LOG.warning('[TEST-Query-1] ⚠️  No pods found in CMDB')
            else:
                LOG.error('[TEST-Query-1] ❌ Query returned None or empty response')
        except Exception as e1:
            LOG.error('[TEST-Query-1] ❌ Query failed with exception: %s', str(e1))
            LOG.exception(e1)
        
        # 方法2：使用 state 字段查询（查询所有 created 状态的 pod）
        LOG.info('')
        LOG.info('[TEST-Query-2] Attempting to query pods with state filter...')
        try:
            state_query = {
                "criteria": {
                    "attrName": "state",
                    "op": "eq",
                    "condition": "created_0"
                }
            }
            LOG.info('[TEST-Query-2] Query data: %s', state_query)
            
            state_pods_response = cmdb_client.query('wecmdb', 'pod', state_query)
            
            if state_pods_response:
                LOG.info('[TEST-Query-2] ✅ Query successful!')
                pods_data = state_pods_response.get('data', [])
                pod_count = len(pods_data) if pods_data else 0
                
                LOG.info('[TEST-Query-2] 📊 Pods in created_0 state: %d', pod_count)
                
                if pod_count > 0:
                    LOG.info('[TEST-Query-2] 📋 Listing pods in created_0 state:')
                    for idx, pod in enumerate(pods_data, 1):
                        LOG.info('[TEST-Query-2]   [%d] guid=%s, code=%s, key_name=%s, asset_id=%s, app_instance=%s',
                                idx,
                                pod.get('guid', 'N/A'),
                                pod.get('code', 'N/A'),
                                pod.get('key_name', 'N/A'),
                                pod.get('asset_id', 'N/A'),
                                pod.get('app_instance', 'N/A'))
                else:
                    LOG.warning('[TEST-Query-2] ⚠️  No pods in created_0 state')
            else:
                LOG.error('[TEST-Query-2] ❌ Query returned None')
        except Exception as e2:
            LOG.error('[TEST-Query-2] ❌ Query failed with exception: %s', str(e2))
            LOG.exception(e2)
        
        LOG.info('='*80)
        LOG.info('🧪 TEST COMPLETED')
        LOG.info('='*80)
    
    except Exception as e:
        LOG.error('❌ TEST FATAL ERROR: %s', str(e))
        LOG.exception(e)
        LOG.info('='*80)


def sync_pod_to_cmdb_on_added(pod_data):
    """Pod 新增时同步到 CMDB（仅更新模式 + 重试机制）
    
    核心原则：Watcher 只负责更新已存在的 CMDB 记录，不创建新记录
    
    工作流程：
    1. 从 Pod annotations 中获取创建者的 token（避免数据隔离问题）
    2. 使用该 token 创建 CMDB 客户端（与 API 使用相同的用户 token）
    3. 使用重试机制等待 apply API 完成 CMDB 预创建（避免时序竞态）
    4. 通过 pod name（code 字段）查询 CMDB
    5. 如果记录存在：
       - 更新 asset_id（填充 K8s UID）
       - 复用已有的 app_instance（不修改）
       - 更新 host_resource（如果节点变化）
    6. 如果记录不存在：
       - 记录日志后直接返回，不执行任何操作
       - 说明该 Pod 不是通过 apply API 创建的（如手动 kubectl create）
    
    Returns:
        tuple: (pod_guid, is_pod_drift)
            - pod_guid (str): CMDB 中 Pod 记录的 GUID，失败或不存在时返回 None
            - is_pod_drift (bool): 是否是 Pod 漂移场景（race condition fallback），需要发送通知
    """
    # ===== 步骤0：重试机制配置 =====
    # apply API 可能正在创建 K8s 资源并等待 Pod 就绪（30-240秒）
    # 需要足够长的重试时间确保 apply API 完成 CMDB 记录创建
    # 注意：有 packageUrl 时 apply API 等待 240 秒，无 packageUrl 时等待 30 秒
    MAX_RETRIES = 15      # 最多重试 15 次（减少重试次数）
    RETRY_INTERVAL = 4    # 每次间隔 4 秒（缩短间隔）
    # 总等待时间：最多 15 * 4 = 60 秒（足够 apply API 完成预创建）
    # 如果 60 秒后还没找到记录，说明不是 apply API 创建的，直接进入创建逻辑
    
    # 【修复】使用带自动fallback的客户端获取（支持token过期自动切换）
    # 优先使用creator_token（保持数据隔离），如果失效则自动切换到系统token
    cmdb_client, token_source = get_cmdb_client_with_fallback(pod_data, 'POD.ADDED')
    
    if not cmdb_client:
        LOG.warning('CMDB client not available, skipping pod add sync')
        return (None, False)
    
    LOG.info('Using %s token for CMDB access', token_source.upper())
    
    # 🧪 测试：首次调用时查询所有 pod 数据
    if cmdb_client and not hasattr(sync_pod_to_cmdb_on_added, '_test_executed'):
        test_query_all_pods_from_cmdb(cmdb_client)
        sync_pod_to_cmdb_on_added._test_executed = True  # 标记已执行，避免重复测试
    
    if not cmdb_client:
        LOG.warning('CMDB client not available, skipping pod add sync')
        return (None, False)
    
    try:
        pod_name = pod_data.get('name')
        pod_id = pod_data.get('asset_id')  # 使用 asset_id（cluster_id_pod_uid）而不是 id
        pod_host_ip = pod_data.get('host_ip')
        cluster_id = pod_data.get('cluster_id')
        pod_namespace = pod_data.get('namespace')
        
        if not pod_name or not pod_id or not cluster_id:
            LOG.warning('Pod name, asset_id or cluster_id missing, skipping CMDB sync: %s', pod_data)
            return (None, False)
        
        # ===== 【新增】等待 Pod 调度完成（获取 host_ip）=====
        # Pod 在 Pending 状态时没有 host_ip，需要等待调度完成
        # 总共等待 120 秒（通常 Pod 调度很快），每 5 秒检查一次
        POD_SCHEDULE_MAX_WAIT = 120  # 最多等待 120 秒（缩短等待时间）
        POD_SCHEDULE_CHECK_INTERVAL = 5  # 每 5 秒检查一次（加快检查频率）
        
        if not pod_host_ip:
            LOG.info('='*60)
            LOG.info('⏳ Pod has no host_ip yet (Pending状态), waiting for scheduling...')
            LOG.info('   Will check every %d seconds (max wait: %d seconds)', 
                     POD_SCHEDULE_CHECK_INTERVAL, POD_SCHEDULE_MAX_WAIT)
            
            # 查询集群配置以创建 K8s 客户端（用于重新读取 Pod 状态）
            try:
                cluster_list = api.db_resource.Cluster().list({'id': cluster_id})
                if not cluster_list:
                    LOG.error('❌ Cannot find cluster configuration for cluster_id: %s', cluster_id)
                    LOG.error('Cannot query Pod status, aborting')
                    LOG.warning('='*60)
                    return (None, False)
                
                cluster_info = cluster_list[0]
                
                # 创建 K8s 客户端
                from wecubek8s.common import k8s
                api_server = cluster_info['api_server']
                if not api_server.startswith('https://') and not api_server.startswith('http://'):
                    api_server = 'https://' + api_server
                
                k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
                k8s_client = k8s.Client(k8s_auth)
                
                # 循环等待 Pod 调度完成
                for wait_attempt in range(1, int(POD_SCHEDULE_MAX_WAIT / POD_SCHEDULE_CHECK_INTERVAL) + 1):
                    time.sleep(POD_SCHEDULE_CHECK_INTERVAL)
                    
                    # 重新读取 Pod 状态
                    LOG.info('[Wait %d/%d] Checking Pod scheduling status...', 
                             wait_attempt, int(POD_SCHEDULE_MAX_WAIT / POD_SCHEDULE_CHECK_INTERVAL))
                    
                    try:
                        pod_obj = k8s_client.get_pod(pod_name, pod_namespace)
                        if pod_obj and pod_obj.status and pod_obj.status.host_ip:
                            pod_host_ip = pod_obj.status.host_ip
                            # 更新 pod_data，供后续使用
                            pod_data['host_ip'] = pod_host_ip
                            LOG.info('[Wait %d/%d] ✅ Pod scheduled! host_ip: %s', 
                                     wait_attempt, int(POD_SCHEDULE_MAX_WAIT / POD_SCHEDULE_CHECK_INTERVAL), 
                                     pod_host_ip)
                            break
                        else:
                            LOG.info('[Wait %d/%d] Still pending, no host_ip yet', 
                                     wait_attempt, int(POD_SCHEDULE_MAX_WAIT / POD_SCHEDULE_CHECK_INTERVAL))
                    except Exception as pod_check_err:
                        LOG.warning('[Wait %d/%d] Failed to query Pod: %s', 
                                    wait_attempt, int(POD_SCHEDULE_MAX_WAIT / POD_SCHEDULE_CHECK_INTERVAL), 
                                    str(pod_check_err))
                
                # 等待结束后，再次检查 host_ip
                if not pod_host_ip:
                    LOG.error('='*60)
                    LOG.error('❌ Pod still has no host_ip after waiting %d seconds', POD_SCHEDULE_MAX_WAIT)
                    LOG.error('   Pod: %s/%s', pod_namespace, pod_name)
                    LOG.error('   Cannot sync Pod without host_ip (no host_resource available)')
                    LOG.error('   Will skip CMDB sync')
                    LOG.error('='*60)
                    return (None, False)
                else:
                    LOG.info('='*60)
                    LOG.info('✅ Pod scheduling complete, continuing CMDB sync')
                    LOG.info('='*60)
                    
            except Exception as e:
                LOG.error('❌ Failed to wait for Pod scheduling: %s', str(e))
                LOG.exception(e)
                LOG.error('Cannot sync Pod without host_ip, aborting')
                LOG.warning('='*60)
                return (None, False)
        
        LOG.info('='*60)
        LOG.info('Syncing POD.ADDED to CMDB: pod=%s, namespace=%s, asset_id=%s, host_ip=%s, cluster_id=%s', 
                 pod_name, pod_namespace or 'N/A', pod_id, pod_host_ip or 'N/A', cluster_id)
        
        # 检查是否是预期创建的 Pod（调用但不消费缓存，仅用于日志）
        # 真正的消费会在 notify_pod 中进行
        is_expected_creation = False
        if pod_namespace:
            # 先检查缓存（但不删除）
            with _expected_pod_lock:
                key = (cluster_id, pod_namespace, pod_name)
                if key in _expected_pod_cache:
                    info = _expected_pod_cache[key]
                    is_expected_creation = True
                    LOG.info('🏷️  This is an EXPECTED pod creation (marked by apply API)')
                    LOG.info('   Source: %s, Time since marked: %.2f seconds', 
                            info.get('source', 'unknown'), time.time() - info.get('timestamp', 0))
                    LOG.info('   Expected: Pod record already pre-created by apply API')
                    LOG.info('   Watcher task: Update asset_id and verify/update host_resource')
                    LOG.info('   Note: Will NOT send WeCube notification later')
                else:
                    LOG.info('⚠️  This is an UNEXPECTED pod creation (NOT marked by apply API)')
                    LOG.info('   Possible reasons: Pod drift, manual kubectl create, or apply marking failed')
                    LOG.info('   Watcher will: Try to update existing CMDB record or create new one')
        
        # 保存标志供 notify_pod 使用
        pod_data['_is_expected_creation'] = is_expected_creation
        
        # ===== 步骤1：通过 code（Pod name）查询 CMDB（带重试机制）=====
        # apply API 预创建时使用 Pod name 作为 code
        query_data = {
            "criteria": {
                "attrName": "code",
                "op": "contains",
                "condition": pod_name
            }
        }
        
        # ===== 步骤1.0：检查"最近删除的 Pod"缓存（快速漂移检测） =====
        cache_key = (pod_namespace, pod_name)
        recently_deleted_info = None
        
        with _recently_deleted_pods_lock:
            if cache_key in _recently_deleted_pods:
                cached_info = _recently_deleted_pods[cache_key]
                cache_age = time.time() - cached_info['timestamp']
                
                # 检查缓存是否在有效期内
                if cache_age <= _recently_deleted_pods_window:
                    recently_deleted_info = cached_info
                    LOG.info('='*60)
                    LOG.info('🎯 DRIFT DETECTED IN CACHE!')
                    LOG.info('='*60)
                    LOG.info('   Pod was recently deleted %d seconds ago', int(cache_age))
                    LOG.info('   This is a confirmed Pod drift/eviction scenario')
                    
                    # 根据是否有 GUID，显示不同的信息
                    if cached_info.get('guid'):
                        LOG.info('   Old GUID: %s', cached_info['guid'])
                        LOG.info('   Old asset_id: %s', cached_info['old_asset_id'])
                        LOG.info('   New asset_id: %s', pod_id)
                        LOG.info('   Will REUSE the GUID and update the record immediately (NO wait needed!)')
                    else:
                        LOG.warning('   ⚠️  Old GUID: None (CMDB was unavailable during deletion)')
                        LOG.warning('   Old asset_id: %s', cached_info['old_asset_id'])
                        LOG.warning('   New asset_id: %s', pod_id)
                        LOG.warning('   Will use backup drift detection strategy (query CMDB)')
                    
                    LOG.info('='*60)
                    
                    # 从缓存中删除（已使用）
                    del _recently_deleted_pods[cache_key]
                    LOG.info('[DRIFT-CACHE] Removed from cache (used for drift detection)')
                else:
                    # 缓存已过期，清理
                    LOG.info('[DRIFT-CACHE] Found expired cache entry (age: %d seconds), removing...', int(cache_age))
                    del _recently_deleted_pods[cache_key]
        
        # 如果检测到漂移场景（方案B：DELETE时删除，ADDED时创建新记录）
        # 记录已在DELETE时删除，现在需要创建新记录（不是更新！）
        if recently_deleted_info:
            # 【关键修复】检查新 Pod 是否有 API 创建标记
            # 如果有，说明这不是漂移，而是用户通过 API 重新部署（先删除旧 StatefulSet，再创建新的）
            created_by_api = pod_data.get('annotations', {}).get('wecube.io/created-by') == 'api'
            
            if created_by_api:
                # Pod 有 API 标记，但也在漂移缓存中，需要进一步判断
                LOG.info('='*60)
                LOG.info('🔍 API ANNOTATION + DRIFT CACHE DETECTED')
                LOG.info('='*60)
                LOG.info('   Same pod name as recently deleted pod, and has API annotation')
                LOG.info('   Old asset_id: %s', recently_deleted_info.get('old_asset_id'))
                LOG.info('   New asset_id: %s', pod_id)
                LOG.info('   Need to query CMDB to determine: API re-deployment OR drift')
                LOG.info('='*60)
                
                # 立即查询 CMDB，判断是否有预创建的记录
                LOG.info('[HYBRID-CHECK] Querying CMDB for pre-created record by code (pod name): %s', pod_name)
                LOG.info('[HYBRID-CHECK] Query data: %s', query_data)
                
                cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
                found_count = len(cmdb_response.get('data', [])) if cmdb_response else 0
                
                LOG.info('[HYBRID-CHECK] Query result: found %d record(s)', found_count)
                
                # 根据查询结果判断场景
                if found_count > 0:
                    # 找到了预创建的记录 → 这是 API 重新部署
                    is_fast_drift_detected = False
                    LOG.info('='*60)
                    LOG.info('✅ CONFIRMED: API RE-DEPLOYMENT (found pre-created record)')
                    LOG.info('   CMDB has pre-created record, this is API delete + create')
                    LOG.info('   Will update the record (NO drift notification)')
                    LOG.info('='*60)
                else:
                    # 没找到预创建的记录 → 这是 Pod 漂移（annotation 是旧的）
                    is_fast_drift_detected = True
                    cmdb_response = None  # 触发后续创建逻辑
                    LOG.info('='*60)
                    LOG.info('🎯 CONFIRMED: POD DRIFT (no pre-created record found)')
                    LOG.info('   Although Pod has API annotation, CMDB has no pre-created record')
                    LOG.info('   This means: Pod was deleted and K8s auto-recreated it (drift)')
                    LOG.info('   The API annotation is from the old Pod (inherited)')
                    LOG.info('   Will create new record immediately (NO 60s wait!)')
                    LOG.info('='*60)
            else:
                # 这是真正的 Pod 漂移（K8s 自动重建，没有 API 标记）
                LOG.info('='*60)
                LOG.info('🎯 FAST DRIFT DETECTED (from cache)!')
                LOG.info('='*60)
                LOG.info('   Pod was deleted and recreated by K8s (drift/eviction scenario)')
                LOG.info('   Old asset_id: %s', recently_deleted_info.get('old_asset_id'))
                LOG.info('   New asset_id: %s', pod_id)
                LOG.info('   Strategy (Scheme B): DELETE (done) + CREATE new record')
                LOG.info('   Note: CMDB record was already deleted in POD.DELETED event')
                LOG.info('   Will create new record immediately (NO wait needed!)')
                LOG.info('='*60)
                
                # 跳过后续的查询和等待逻辑，直接进入创建新记录的流程
                # 设置标记，让后续代码知道这是漂移场景（用于日志和通知）
                is_fast_drift_detected = True
                
                # 不需要查询CMDB，因为我们知道记录已被删除
                # 直接跳到创建新记录的逻辑（第832行）
                LOG.info('[FAST-DRIFT] Skipping CMDB query (record is already deleted)')
                LOG.info('[FAST-DRIFT] Will jump to record creation step...')
                
                # 设置 cmdb_response 为空，触发创建逻辑
                cmdb_response = None
                
                # 检查是否有 GUID（用于日志记录，不影响逻辑）
                old_guid = recently_deleted_info.get('guid')
                if old_guid:
                    LOG.info('[FAST-DRIFT] Old GUID: %s (will NOT be reused - Scheme B)', old_guid)
                else:
                    LOG.warning('[FAST-DRIFT] ⚠️  Old GUID: None (CMDB was unavailable during deletion)')
                
                # 跳过步骤1.1和1.2，直接到步骤1.3的创建逻辑
        
        else:
            # 没有检测到缓存中的漂移，继续正常流程
            is_fast_drift_detected = False
            
            # ===== 步骤1.1：首次查询 CMDB（没有检测到缓存中的漂移） =====
            LOG.info('[Step 1.1] Initial query: Checking if Pod record exists by code (pod name): %s', pod_name)
            LOG.info('[Step 1.1] Query data: %s', query_data)
            
            cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
            found_count = len(cmdb_response.get('data', [])) if cmdb_response else 0
            
            LOG.info('[Step 1.1] Query result: found %d record(s)', found_count)
        
        # ===== 步骤1.2：如果没找到记录，进一步检测是否是 Pod 漂移场景（备用检测） =====
        # 注意：这是备用检测机制，主要用于处理多 watcher 场景下，另一个 watcher 删除了记录的情况
        # 如果已经通过快速漂移检测确认是漂移场景，跳过备用检测
        if not is_fast_drift_detected and (not cmdb_response or not cmdb_response.get('data') or len(cmdb_response['data']) == 0):
            LOG.info('='*60)
            LOG.info('🔍 BACKUP DRIFT DETECTION: Cache miss, querying CMDB...')
            LOG.info('   This handles cases where another watcher deleted the record')
            LOG.info('   Looking for old records with same pod name but different UID')
            LOG.info('='*60)
            
            # 查询所有同名 Pod 记录（不论 UID）
            # 这是备用检测机制，主要用于多 watcher 场景
            drift_query_data = {
                "criteria": {
                    "attrName": "code",
                    "op": "eq",  # 使用精确匹配而不是 contains
                    "condition": pod_name
                }
            }
            
            LOG.info('[BACKUP-DRIFT-CHECK] Querying CMDB with exact match...')
            drift_response = cmdb_client.query('wecmdb', 'pod', drift_query_data)
            drift_records = drift_response.get('data', []) if drift_response else []
            
            LOG.info('[BACKUP-DRIFT-CHECK] Found %d record(s) with same pod name', len(drift_records))
            
            # 检查是否有旧记录（asset_id 不同）
            old_record = None
            for record in drift_records:
                record_asset_id = record.get('asset_id')
                LOG.info('[BACKUP-DRIFT-CHECK] Checking record: guid=%s, asset_id=%s', 
                        record.get('guid'), record_asset_id or 'NULL')
                
                if record_asset_id and record_asset_id != pod_id:
                    # 找到旧记录：Pod name 相同但 UID 不同（另一个 watcher 没删掉，或删除失败）
                    old_record = record
                    LOG.info('='*60)
                    LOG.info('🎯 BACKUP DRIFT DETECTED! Found stale Pod record with different UID')
                    LOG.info('   Old UID: %s', record_asset_id)
                    LOG.info('   New UID: %s', pod_id)
                    LOG.info('   This is a Pod drift scenario (cache miss, possibly multi-watcher)')
                    LOG.info('   Will update the CMDB record immediately (NO 240s wait needed)')
                    LOG.info('='*60)
                    break
            
            # 如果检测到漂移（备用机制），删除旧记录
            if old_record:
                LOG.info('='*60)
                LOG.info('[BACKUP-DRIFT-DELETE] Deleting stale Pod record for backup drift scenario...')
                LOG.info('[BACKUP-DRIFT-DELETE] GUID: %s', old_record.get('guid'))
                LOG.info('[BACKUP-DRIFT-DELETE] Old asset_id: %s', old_record.get('asset_id'))
                LOG.info('[BACKUP-DRIFT-DELETE] New asset_id: %s', pod_id)
                LOG.info('[BACKUP-DRIFT-DELETE] Strategy: Delete old + Create new')
                LOG.info('='*60)
                
                try:
                    # 删除旧记录
                    cmdb_client.delete('wecmdb', 'pod', [{'guid': old_record.get('guid')}])
                    LOG.info('[BACKUP-DRIFT-DELETE] ✅ Successfully deleted stale Pod record')
                    LOG.info('[BACKUP-DRIFT-DELETE]    GUID: %s', old_record.get('guid'))
                    LOG.info('[BACKUP-DRIFT-DELETE]    asset_id: %s', old_record.get('asset_id'))
                    
                    # 存入缓存，用于后续漂移检测
                    cache_key = (pod_data.get('namespace', 'default'), pod_name)
                    cache_value = {
                        'timestamp': time.time(),
                        'guid': old_record.get('guid'),
                        'old_asset_id': old_record.get('asset_id'),
                        'host_ip': old_record.get('host_resource'),
                        'cluster_id': cluster_id
                    }
                    with _recently_deleted_pods_lock:
                        _recently_deleted_pods[cache_key] = cache_value
                        LOG.info('[BACKUP-DRIFT-DELETE] Cached deletion for drift detection')
                    
                    # 删除成功后，继续进入创建新记录的流程（不 return，让代码继续执行）
                    # cmdb_response 仍然为空，所以会进入后续的创建逻辑
                    LOG.info('[BACKUP-DRIFT-DELETE] Will create new record in next step...')
                    
                except Exception as delete_err:
                    LOG.error('[BACKUP-DRIFT-DELETE] ❌ Delete failed: %s', str(delete_err))
                    LOG.exception(delete_err)
                    # 删除失败，继续进入重试循环或创建逻辑
            else:
                LOG.info('='*60)
                LOG.info('⚠️  No drift detected in backup check')
                LOG.info('   Cache miss AND no stale records found in CMDB')
                LOG.info('   This is likely a new Pod creation from apply API')
                LOG.info('   Will enter retry loop to wait for apply API to complete CMDB pre-creation')
                LOG.info('='*60)
        
        # ===== 步骤1.3：进入重试循环（等待 apply API 完成 CMDB 预创建）=====
        # 只有在没有找到记录且不是漂移场景时，才进入重试循环
        # 如果是快速漂移场景，跳过重试（记录已删除，直接创建新记录）
        if not is_fast_drift_detected and (not cmdb_response or not cmdb_response.get('data') or len(cmdb_response['data']) == 0):
            # 🎯 优化：检查是否有 API 创建标记，如果有，说明 apply API 应该已经预创建了记录
            # 如果没有标记，可能是手动创建或漂移，不需要等待太久
            has_api_annotation = pod_data.get('annotations', {}).get('wecube.io/created-by') == 'api'
            
            # 根据是否有 API 标记调整重试策略
            if has_api_annotation:
                actual_max_retries = MAX_RETRIES
                LOG.info('[Step 1.3] Pod has API annotation, will wait up to %d seconds for apply API',
                        MAX_RETRIES * RETRY_INTERVAL)
            else:
                # 没有 API 标记，很可能不是 apply API 创建的，减少等待时间
                actual_max_retries = max(3, MAX_RETRIES // 5)  # 最多 3 次重试（12 秒）
                LOG.info('[Step 1.3] Pod has NO API annotation, will only wait %d seconds before creating',
                        actual_max_retries * RETRY_INTERVAL)
            
            LOG.info('[Step 1.3] Entering retry loop (waiting for apply API to complete)...')
            
            for attempt in range(1, actual_max_retries + 1):
                LOG.info('[Step 1.3] [Retry %d/%d] Waiting %d seconds before retry...', 
                        attempt, actual_max_retries, RETRY_INTERVAL)
                time.sleep(RETRY_INTERVAL)
                
                LOG.info('[Step 1.3] [Retry %d/%d] Querying CMDB by code (pod name): %s', 
                        attempt, actual_max_retries, pod_name)
                
                cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
                found_count = len(cmdb_response.get('data', [])) if cmdb_response else 0
                
                LOG.info('[Step 1.3] [Retry %d/%d] Query result: found %d record(s)', 
                        attempt, actual_max_retries, found_count)
                
                # 如果找到记录，立即跳出循环
                if cmdb_response and cmdb_response.get('data') and len(cmdb_response['data']) > 0:
                    LOG.info('✅ Found CMDB record on retry %d/%d', attempt, actual_max_retries)
                    break
        
        # ===== 检查最终查询结果 =====
        if not cmdb_response or not cmdb_response.get('data') or len(cmdb_response['data']) == 0:
            # 如果是快速漂移场景，不显示警告（这是预期的）
            if is_fast_drift_detected:
                LOG.info('='*60)
                LOG.info('[FAST-DRIFT] CMDB record not found (as expected - deleted in POD.DELETED event)')
                LOG.info('   Will create new record immediately')
                LOG.info('='*60)
            else:
                LOG.warning('='*60)
                LOG.warning('❌ CMDB record NOT FOUND after drift detection + %d retries', actual_max_retries)
                LOG.warning('   Total wait time: %d seconds', actual_max_retries * RETRY_INTERVAL)
                LOG.warning('   Pod name: %s', pod_name)
                LOG.warning('   Cluster: %s', cluster_id)
                LOG.warning('   Possible reasons:')
                LOG.warning('   1. Pod was created manually (kubectl create) without apply API')
                LOG.warning('   2. apply API failed before creating CMDB record')
                LOG.warning('   3. StatefulSet was created without instanceId (missing wecube.io/app-instance annotation)')
                LOG.warning('   Note: Pod drift scenario is already handled by fast drift detection')
                LOG.warning('='*60)
            
            # ===== 新增逻辑：创建 Pod 记录（处理 Pod 漂移场景）=====
            LOG.info('🆕 Attempting to CREATE new Pod record in CMDB (drift/eviction scenario)')
            
            # 步骤1：获取 app_instance（从 StatefulSet 的 annotation）
            statefulset_name = pod_data.get('statefulset_name')  # 从 Pod 的 owner_references 获取
            pod_namespace = pod_data.get('namespace')
            app_instance_guid = None
            
            if statefulset_name and pod_namespace:
                LOG.info('[CREATE-Step-1] Pod belongs to StatefulSet: %s/%s', pod_namespace, statefulset_name)
                LOG.info('[CREATE-Step-1] Reading app_instance from StatefulSet annotation...')
                
                # 查询集群配置以创建 K8s 客户端
                try:
                    cluster_list = api.db_resource.Cluster().list({'id': cluster_id})
                    if not cluster_list:
                        LOG.error('[CREATE-Step-1] ❌ Cannot find cluster configuration for cluster_id: %s', cluster_id)
                        LOG.error('[CREATE-Step-1] Cannot create K8s client, aborting')
                        LOG.warning('='*60)
                        return (None, False)
                    
                    cluster_info = cluster_list[0]
                    
                    # 确保 api_server 有正确的协议前缀
                    from wecubek8s.common import k8s
                    api_server = cluster_info['api_server']
                    if not api_server.startswith('https://') and not api_server.startswith('http://'):
                        api_server = 'https://' + api_server
                    
                    # 创建 K8s 客户端
                    k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
                    k8s_client = k8s.Client(k8s_auth)
                    
                    # 从 StatefulSet 的 annotation 中读取 app_instance
                    app_instance_guid = query_statefulset_app_instance(k8s_client, statefulset_name, pod_namespace)
                    
                    if app_instance_guid:
                        LOG.info('[CREATE-Step-1] ✅ Found app_instance: %s', app_instance_guid)
                    else:
                        LOG.error('[CREATE-Step-1] ❌ Cannot find app_instance from StatefulSet annotation')
                        LOG.error('[CREATE-Step-1] StatefulSet: %s/%s', pod_namespace, statefulset_name)
                        LOG.error('[CREATE-Step-1] This StatefulSet was created without instanceId parameter')
                        LOG.error('[CREATE-Step-1] Solution: Add annotation manually or recreate with instanceId:')
                        LOG.error('[CREATE-Step-1]   kubectl annotate statefulset %s -n %s wecube.io/app-instance=<guid> --overwrite', 
                                 statefulset_name, pod_namespace)
                        LOG.error('[CREATE-Step-1] Cannot create Pod without app_instance, aborting')
                        LOG.warning('='*60)
                        return (None, False)
                        
                except Exception as e:
                    LOG.error('[CREATE-Step-1] ❌ Failed to read StatefulSet annotation: %s', str(e))
                    LOG.exception(e)
                    LOG.error('[CREATE-Step-1] Cannot create Pod without app_instance, aborting')
                    LOG.warning('='*60)
                    return (None, False)
            else:
                LOG.error('[CREATE-Step-1] ❌ Pod has no StatefulSet owner or namespace is missing')
                LOG.error('[CREATE-Step-1] statefulset_name: %s, namespace: %s', statefulset_name or 'None', pod_namespace or 'None')
                LOG.error('[CREATE-Step-1] This Pod may not be managed by StatefulSet')
                LOG.error('[CREATE-Step-1] Cannot create Pod without app_instance, aborting')
                LOG.warning('='*60)
                return (None, False)
            
            # 步骤2：获取 host_resource（从 host IP）
            host_resource_guid = None
            if pod_host_ip:
                LOG.info('[CREATE-Step-2] Querying host_resource for IP: %s', pod_host_ip)
                host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                
                if host_resource_guid:
                    LOG.info('[CREATE-Step-2] ✅ Found host_resource: %s', host_resource_guid)
                else:
                    LOG.error('[CREATE-Step-2] ❌ host_resource not found for IP: %s', pod_host_ip)
                    LOG.error('[CREATE-Step-2] Cannot create Pod without host_resource')
                    LOG.error('[CREATE-Step-2] Please ensure the node is registered in CMDB')
                    LOG.warning('='*60)
                    return (None, False)
            else:
                LOG.error('[CREATE-Step-2] ❌ Pod has no host_ip')
                LOG.error('[CREATE-Step-2] This should not happen - Pod should be scheduled after waiting')
                LOG.warning('='*60)
                return (None, False)
            
            # 步骤3：最终检查 - 必须同时有 app_instance 和 host_resource
            LOG.info('[CREATE-Step-3] Final validation before creating Pod record...')
            if not app_instance_guid:
                LOG.error('[CREATE-Step-3] ❌ Missing app_instance, cannot create Pod')
                LOG.error('[CREATE-Step-3] app_instance: %s', app_instance_guid or 'None')
                LOG.warning('='*60)
                return (None, False)
            
            if not host_resource_guid:
                LOG.error('[CREATE-Step-3] ❌ Missing host_resource, cannot create Pod')
                LOG.error('[CREATE-Step-3] host_resource: %s', host_resource_guid or 'None')
                LOG.warning('='*60)
                return (None, False)
            
            LOG.info('[CREATE-Step-3] ✅ Validation passed:')
            LOG.info('[CREATE-Step-3]    app_instance: %s', app_instance_guid)
            LOG.info('[CREATE-Step-3]    host_resource: %s', host_resource_guid)
            
            # 步骤4：创建 Pod 记录
            LOG.info('[CREATE-Step-4] Creating new Pod record in CMDB...')
            create_data = {
                'code': pod_name,
                'key_name': pod_name,
                'asset_id': pod_id,  # K8s UID（带 cluster_id 前缀）
                'app_instance': app_instance_guid,  # 从 StatefulSet 继承（必需）
                'host_resource': host_resource_guid,  # 从 host_ip 查询（必需）
                'state': 'created_0'  # 默认状态
            }
            
            LOG.info('[CREATE-Step-4] Create data: %s', create_data)
            
            try:
                # CMDB 的 code 字段有唯一性约束，天然支持跨进程去重
                # 如果多个 watcher 同时创建，只有一个会成功，其他会失败（然后查询到已存在的记录）
                create_response = cmdb_client.create('wecmdb', 'pod', [create_data])
                
                if create_response and create_response.get('data') and len(create_response['data']) > 0:
                    created_pod = create_response['data'][0]
                    created_guid = created_pod.get('guid')
                    
                    LOG.info('='*60)
                    if is_fast_drift_detected:
                        LOG.info('✅ Successfully CREATED Pod in CMDB (FAST DRIFT DETECTION)')
                        LOG.info('   Detection method: Cache-based (< 1 second)')
                        LOG.info('   Pod was deleted and recreated by K8s')
                    else:
                        LOG.info('✅ Successfully CREATED Pod in CMDB (drift/eviction scenario)')
                    LOG.info('   Pod name: %s', pod_name)
                    LOG.info('   Pod GUID: %s', created_guid)
                    LOG.info('   asset_id: %s', pod_id)
                    LOG.info('   app_instance: %s', app_instance_guid)
                    LOG.info('   host_resource: %s', host_resource_guid)
                    LOG.info('='*60)
                    # 这是新创建的 Pod（漂移场景），返回 (guid, is_pod_drift=True)
                    return (created_guid, True)
                else:
                    LOG.error('[CREATE-Step-4] ❌ Create returned no data')
                    LOG.error('[CREATE-Step-4] Response: %s', create_response)
                    LOG.warning('='*60)
                    return (None, False)
                    
            except Exception as create_err:
                # 可能是因为 code 唯一性冲突（多个 watcher 同时创建）
                # 重新查询一次，看是否已被其他 watcher 创建
                error_msg = str(create_err)
                LOG.warning('[CREATE-Step-4] Create failed: %s', error_msg)
                
                if 'unique' in error_msg.lower() or 'duplicate' in error_msg.lower() or 'exists' in error_msg.lower():
                    LOG.info('[CREATE-Step-4] Likely duplicate creation by another watcher, retrying query...')
                    time.sleep(1)  # 等待 1 秒确保其他 watcher 创建完成
                    
                    # 重新查询
                    retry_response = cmdb_client.query('wecmdb', 'pod', query_data)
                    if retry_response and retry_response.get('data') and len(retry_response['data']) > 0:
                        existing_pod = retry_response['data'][0]
                        existing_guid = existing_pod.get('guid')
                        existing_asset_id = existing_pod.get('asset_id')
                        
                        LOG.info('[CREATE-Step-4] ✅ Found Pod created by another watcher: guid=%s', existing_guid)
                        
                        # 更新 asset_id（如果为空或不匹配）
                        if not existing_asset_id or existing_asset_id != pod_id:
                            LOG.info('[CREATE-Step-4] Updating asset_id: %s -> %s', existing_asset_id or 'NULL', pod_id)
                            update_data = {
                                'guid': existing_guid,
                                'asset_id': pod_id,
                                'host_resource': host_resource_guid  # 确保 host_resource 也更新
                            }
                            
                            cmdb_client.update('wecmdb', 'pod', [update_data])
                            LOG.info('[CREATE-Step-4] ✅ Updated asset_id and host_resource successfully')
                        
                        LOG.info('='*60)
                        # 找到其他 watcher 创建的记录，也算是 Pod 漂移场景
                        return (existing_guid, True)
                    else:
                        LOG.error('[CREATE-Step-4] ❌ Retry query still found no record')
                        LOG.warning('='*60)
                        return (None, False)
                else:
                    LOG.error('[CREATE-Step-4] ❌ Create failed with unexpected error')
                    LOG.exception(create_err)
                    LOG.warning('='*60)
                    return (None, False)
        
        # ===== 步骤2：如果通过 code 找到记录，则更新 =====
        if cmdb_response and cmdb_response.get('data') and len(cmdb_response['data']) > 0:
            existing_pod = cmdb_response['data'][0]
            pod_guid = existing_pod.get('guid')
            existing_asset_id = existing_pod.get('asset_id')
            existing_host_resource = existing_pod.get('host_resource')
            existing_app_instance = existing_pod.get('app_instance')  # 读取已有的 app_instance
            
            LOG.info('[Step 2] Found existing pod by code: guid=%s, asset_id=%s', 
                    pod_guid, existing_asset_id or 'NULL')
            LOG.info('[Step 2] Existing relations: app_instance=%s, host_resource=%s',
                    existing_app_instance or 'NULL', existing_host_resource or 'NULL')
            
            if not pod_guid:
                LOG.warning('CMDB pod record has no guid, cannot update: %s', pod_name)
                return (None, False)
            
            # 判断场景
            is_pre_created = (not existing_asset_id or existing_asset_id == '')
            is_pod_rebuilt = (existing_asset_id and existing_asset_id != pod_id)
            
            if is_pre_created:
                LOG.info('✅ Scenario: PRE-CREATED by apply API (asset_id empty)')
                LOG.info('   app_instance already set by apply API: %s', existing_app_instance or 'NULL')
                LOG.info('   Will update: asset_id + host_resource (if changed)')
            elif is_pod_rebuilt:
                LOG.info('🔄 Scenario: POD REBUILT (asset_id changed)')
                LOG.info('   Old UID: %s → New UID: %s', existing_asset_id, pod_id)
                LOG.info('   Will update: asset_id + host_resource (if changed)')
                LOG.info('   Reason: pod restart, node eviction, or manual deletion')
                LOG.info('   ⚠️  This is a POD DRIFT/REBUILD - notification WILL be sent')
            else:
                LOG.info('Scenario: POD EXISTS with same asset_id, checking for drift')
            
            # Pod 重建时，清理重复记录
            if is_pod_rebuilt:
                check_query = {
                    "criteria": {
                        "attrName": "asset_id",
                        "op": "eq",
                        "condition": pod_id
                    }
                }
                check_response = cmdb_client.query('wecmdb', 'pod', check_query)
                
                if check_response and check_response.get('data'):
                    for duplicate_pod in check_response['data']:
                        dup_guid = duplicate_pod.get('guid')
                        if dup_guid and dup_guid != pod_guid:
                            LOG.warning('⚠️  Found duplicate pod with same asset_id %s (guid=%s), deleting...', 
                                       pod_id, dup_guid)
                            try:
                                cmdb_client.delete('wecmdb', 'pod', [{'guid': dup_guid}])
                                LOG.info('✅ Deleted duplicate pod record: guid=%s', dup_guid)
                            except Exception as del_err:
                                LOG.error('Failed to delete duplicate pod: %s', str(del_err))
            
            update_data = {
                'guid': pod_guid,
                'asset_id': pod_id  # 更新 K8s UID
            }
            
            # 查询并更新 host_resource（Pod 可能调度到不同节点或发生漂移）
            host_resource_guid = None
            if pod_host_ip:
                LOG.info('[Step 2] Querying host_resource for IP: %s', pod_host_ip)
                host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                
                if host_resource_guid:
                    # 检测 host_resource 是否变化
                    if existing_host_resource != host_resource_guid:
                        LOG.info('🚀 HOST CHANGED! Pod %s scheduled/drifted to different node:', pod_name)
                        LOG.info('   Old host_resource: %s', existing_host_resource or 'NULL (not scheduled yet)')
                        LOG.info('   New host_resource: %s (IP: %s)', host_resource_guid, pod_host_ip)
                    else:
                        LOG.info('✓ Host unchanged: %s (IP: %s)', host_resource_guid, pod_host_ip)
                    # 设置 host_resource（确保数据一致性）
                    update_data['host_resource'] = host_resource_guid
                else:
                    LOG.error('[Step 2] ❌ Cannot find host_resource for IP %s in CMDB', pod_host_ip)
                    LOG.error('[Step 2] Cannot update Pod without host_resource')
                    LOG.error('[Step 2] Please ensure the node is registered in CMDB')
                    LOG.warning('='*60)
                    return (None, False)
            else:
                LOG.error('[Step 2] ❌ Pod has no host_ip')
                LOG.error('[Step 2] This should not happen - Pod should be scheduled after waiting')
                LOG.warning('='*60)
                return (None, False)
            
            # 最终检查 - 必须同时有 app_instance 和 host_resource
            LOG.info('[Step 2] Final validation before updating Pod record...')
            if not existing_app_instance:
                LOG.error('[Step 2] ❌ Missing app_instance in existing record, cannot update Pod')
                LOG.error('[Step 2]    app_instance: %s', existing_app_instance or 'None')
                LOG.warning('='*60)
                return (None, False)
            
            if not host_resource_guid:
                LOG.error('[Step 2] ❌ Missing host_resource, cannot update Pod')
                LOG.error('[Step 2]    host_resource: %s', host_resource_guid or 'None')
                LOG.warning('='*60)
                return (None, False)
            
            LOG.info('[Step 2] ✅ Validation passed:')
            LOG.info('[Step 2]    app_instance: %s (existing)', existing_app_instance)
            LOG.info('[Step 2]    host_resource: %s', host_resource_guid)
            
            # 不查询 app_instance（apply API 已设置），但保留已有值（避免覆盖为空）
            # 只有在 apply API 没设置时才可能需要更新，但那是 apply 的 bug，watcher 不处理
            
            try:
                update_response = cmdb_client.update('wecmdb', 'pod', [update_data])
                LOG.info('[Step 2] ✅ Successfully UPDATED pod in CMDB')
                LOG.info('   Pod: %s (guid: %s)', pod_name, pod_guid)
                LOG.info('   asset_id: %s', pod_id)
                LOG.info('   host_resource: %s', update_data.get('host_resource', 'NOT_CHANGED'))
                LOG.info('='*60)
                
                # 【修复】判断是否需要发送通知
                # 如果是 Pod 重建场景（asset_id 变化），需要发送通知
                if is_pod_rebuilt:
                    LOG.info('🔔 Pod rebuild detected (asset_id changed) - this is a drift scenario')
                    LOG.info('   Will send WeCube notification')
                    # 返回 (guid, is_pod_drift=True) 标记需要发送通知
                    return (pod_guid, True)
                else:
                    # 正常预创建更新场景，不需要发送通知
                    return (pod_guid, False)
            except Exception as update_err:
                # 更新失败，可能是因为记录在查询后被 POD.DELETED 删除了（时序竞态）
                error_msg = str(update_err)
                LOG.warning('[Step 2] ⚠️  Update failed: %s', error_msg)
                
                if 'can not find' in error_msg.lower() or 'not found' in error_msg.lower():
                    LOG.warning('[Step 2] 🔄 Record was deleted after query (race condition with POD.DELETED)')
                    LOG.warning('[Step 2] This is a Pod drift/rebuild scenario')
                    LOG.warning('[Step 2] Will create new record instead...')
                    
                    # 跳转到创建逻辑（重用前面的创建代码逻辑）
                    # 注意：此时 Pod 可能还没有调度到节点（host_ip 为空）
                    LOG.info('[Step 2-Fallback] Creating new Pod record after update failure...')
                    
                    # 获取 app_instance（从现有记录或 StatefulSet）
                    app_instance_guid = existing_app_instance  # 复用查询到的 app_instance
                    
                    if not app_instance_guid:
                        LOG.error('[Step 2-Fallback] ❌ No app_instance available, cannot create Pod')
                        LOG.error('[Step 2-Fallback] This should not happen - record had app_instance before deletion')
                        LOG.warning('='*60)
                        return (None, False)
                    
                    # 获取 host_resource（必须有 host_ip 才能查询）
                    host_resource_guid = None
                    if pod_host_ip:
                        LOG.info('[Step 2-Fallback] Querying host_resource for IP: %s', pod_host_ip)
                        host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                        
                        if host_resource_guid:
                            LOG.info('[Step 2-Fallback] ✅ Found host_resource: %s', host_resource_guid)
                        else:
                            LOG.error('[Step 2-Fallback] ❌ host_resource not found for IP: %s', pod_host_ip)
                            LOG.error('[Step 2-Fallback] Cannot create Pod without host_resource')
                            LOG.error('[Step 2-Fallback] Please ensure the node is registered in CMDB')
                            LOG.warning('='*60)
                            return (None, False)
                    else:
                        LOG.error('[Step 2-Fallback] ❌ Pod has no host_ip')
                        LOG.error('[Step 2-Fallback] This should not happen - Pod should be scheduled after waiting')
                        LOG.warning('='*60)
                        return (None, False)
                    
                    # 最终检查 - 必须同时有 app_instance 和 host_resource
                    LOG.info('[Step 2-Fallback] Final validation before creating Pod record...')
                    if not app_instance_guid or not host_resource_guid:
                        LOG.error('[Step 2-Fallback] ❌ Missing required fields, cannot create Pod')
                        LOG.error('[Step 2-Fallback]    app_instance: %s', app_instance_guid or 'None')
                        LOG.error('[Step 2-Fallback]    host_resource: %s', host_resource_guid or 'None')
                        LOG.warning('='*60)
                        return (None, False)
                    
                    LOG.info('[Step 2-Fallback] ✅ Validation passed:')
                    LOG.info('[Step 2-Fallback]    app_instance: %s', app_instance_guid)
                    LOG.info('[Step 2-Fallback]    host_resource: %s', host_resource_guid)
                    
                    # 创建数据
                    create_data = {
                        'code': pod_name,
                        'key_name': pod_name,
                        'asset_id': pod_id,
                        'app_instance': app_instance_guid,  # 必需
                        'host_resource': host_resource_guid,  # 必需
                        'state': 'created_0'
                    }
                    
                    LOG.info('[Step 2-Fallback] Create data: %s', create_data)
                    
                    try:
                        create_response = cmdb_client.create('wecmdb', 'pod', [create_data])
                        
                        if create_response and create_response.get('data') and len(create_response['data']) > 0:
                            created_pod = create_response['data'][0]
                            created_guid = created_pod.get('guid')
                            
                            LOG.info('='*60)
                            LOG.info('✅ Successfully CREATED Pod in CMDB (fallback after update failure)')
                            LOG.info('   Pod name: %s', pod_name)
                            LOG.info('   Pod GUID: %s', created_guid)
                            LOG.info('   asset_id: %s', pod_id)
                            LOG.info('   app_instance: %s', app_instance_guid)
                            LOG.info('   host_resource: %s', create_data.get('host_resource', 'N/A'))
                            LOG.info('   🔔 This is a POD DRIFT scenario - WeCube notification WILL be sent')
                            LOG.info('='*60)
                            # 返回 (guid, is_pod_drift=True) 标记这是 Pod 漂移场景，需要发送通知
                            return (created_guid, True)
                        else:
                            LOG.error('[Step 2-Fallback] ❌ Create returned no data')
                            LOG.error('[Step 2-Fallback] Response: %s', create_response)
                            LOG.warning('='*60)
                            return (None, False)
                    except Exception as create_err:
                        LOG.error('[Step 2-Fallback] ❌ Create also failed: %s', str(create_err))
                        LOG.exception(create_err)
                        LOG.warning('='*60)
                        return (None, False)
                else:
                    # 其他类型的错误，直接抛出
                    LOG.error('[Step 2] ❌ Update failed with unexpected error')
                    LOG.exception(update_err)
                    LOG.warning('='*60)
                    raise
        else:
            # ===== 记录不存在：不执行任何操作（只更新模式） =====
            LOG.warning('='*60)
            LOG.warning('⚠️  Pod NOT found in CMDB by code (pod name)')
            LOG.warning('='*60)
            LOG.warning('Pod information:')
            LOG.warning('  - Name: %s', pod_name)
            LOG.warning('  - Namespace: %s', pod_data.get('namespace', 'N/A'))
            LOG.warning('  - Cluster: %s', cluster_id)
            LOG.warning('  - K8s UID (asset_id): %s', pod_id)
            LOG.warning('  - Host IP: %s', pod_host_ip or 'N/A')
            LOG.warning('')
            LOG.warning('Watcher policy: UPDATE-ONLY mode')
            LOG.warning('  ✗ Will NOT create new CMDB record')
            LOG.warning('  ✓ Only updates existing records pre-created by apply API')
            LOG.warning('')
            LOG.warning('Possible reasons:')
            LOG.warning('  1. Pod created manually via kubectl (not via apply API)')
            LOG.warning('  2. CMDB record was deleted manually')
            LOG.warning('  3. Race condition: apply API has not yet completed CMDB pre-creation')
            LOG.warning('')
            LOG.warning('Action: Skipping CMDB sync for this pod')
            LOG.warning('='*60)
            return (None, False)
    
    except Exception as e:
        LOG.error('='*60)
        LOG.error('❌ FATAL ERROR: Failed to sync POD.ADDED to CMDB')
        LOG.error('Pod name: %s, Pod ID: %s', pod_data.get('name', 'unknown'), pod_data.get('id', 'unknown'))
        LOG.error('Error: %s', str(e))
        LOG.exception(e)
        LOG.error('='*60)
        return (None, False)


def sync_pod_to_cmdb_on_deleted(pod_data):
    """Pod 删除时同步到 CMDB（硬删除）"""
    # 【修复】使用带自动fallback的客户端获取（支持token过期自动切换）
    # 优先使用creator_token（保持数据隔离），如果失效则自动切换到系统token
    cmdb_client, token_source = get_cmdb_client_with_fallback(pod_data, 'POD.DELETED')
    
    if not cmdb_client:
        LOG.warning('CMDB client not available, skipping pod delete sync')
        return
    
    LOG.info('Using %s token for CMDB access', token_source.upper())
    
    try:
        pod_name = pod_data.get('name')
        pod_asset_id = pod_data.get('asset_id')  # 使用 asset_id（cluster_id_pod_uid）
        pod_id = pod_asset_id  # 兼容旧代码中的 pod_id 变量名
        
        # 从 asset_id 中提取 cluster_id（格式：{cluster_id}_{pod_uid}）
        cluster_id = None
        if pod_asset_id and '_' in pod_asset_id:
            cluster_id = pod_asset_id.split('_', 1)[0]
        
        if not pod_name:
            LOG.warning('Pod name missing, skipping CMDB sync: %s', pod_data)
            return
        
        LOG.info('='*60)
        LOG.info('🗑️  Syncing POD.DELETED to CMDB: pod=%s, asset_id=%s', pod_name, pod_asset_id or 'N/A')
        LOG.info('='*60)
        
        # ===== 方式1：通过 code 字段查询（优先级最高） =====
        query_data = {
            "criteria": {
                "attrName": "code",
                "op": "eq",
                "condition": pod_name
            }
        }
        
        LOG.info('[Query-1] Querying CMDB by code (pod name): %s', pod_name)
        cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
        LOG.info('[Query-1] Response status: %s', 
                'SUCCESS' if cmdb_response and cmdb_response.get('data') else 'NO DATA')
        
        pod_guid = None
        existing_asset_id = None
        existing_pod = None
        
        if cmdb_response and cmdb_response.get('data') and len(cmdb_response['data']) > 0:
            LOG.info('[Query-1] ✅ Found %d pod(s) in CMDB by code', len(cmdb_response['data']))
            existing_pod = cmdb_response['data'][0]
            pod_guid = existing_pod.get('guid')
            existing_asset_id = existing_pod.get('asset_id')
            LOG.info('[Query-1] Pod details: guid=%s, asset_id=%s, code=%s, key_name=%s, state=%s', 
                    pod_guid, existing_asset_id, existing_pod.get('code'), 
                    existing_pod.get('key_name'), existing_pod.get('state'))
        else:
            LOG.warning('[Query-1] ❌ Pod not found by code')
            
            # ===== 方式2：通过 key_name 查询（某些 CMDB 使用 key_name 作为唯一键） =====
            LOG.info('[Query-2] Trying to query by key_name: %s', pod_name)
            query_by_keyname = {
                "criteria": {
                    "attrName": "key_name",
                    "op": "eq",
                    "condition": pod_name
                }
            }
            cmdb_response_keyname = cmdb_client.query('wecmdb', 'pod', query_by_keyname)
            LOG.info('[Query-2] Response status: %s', 
                    'SUCCESS' if cmdb_response_keyname and cmdb_response_keyname.get('data') else 'NO DATA')
            
            if cmdb_response_keyname and cmdb_response_keyname.get('data') and len(cmdb_response_keyname['data']) > 0:
                LOG.info('[Query-2] ✅ Found %d pod(s) in CMDB by key_name', len(cmdb_response_keyname['data']))
                existing_pod = cmdb_response_keyname['data'][0]
                pod_guid = existing_pod.get('guid')
                existing_asset_id = existing_pod.get('asset_id')
                LOG.info('[Query-2] Pod details: guid=%s, asset_id=%s, code=%s, key_name=%s, state=%s', 
                        pod_guid, existing_asset_id, existing_pod.get('code'), 
                        existing_pod.get('key_name'), existing_pod.get('state'))
            else:
                LOG.warning('[Query-2] ❌ Pod not found by key_name')
                
                # ===== 方式3：通过 asset_id 查询（备用） =====
                if pod_asset_id:
                    LOG.info('[Query-3] Trying to query by asset_id: %s', pod_asset_id)
                    query_by_asset_id = {
                        "criteria": {
                            "attrName": "asset_id",
                            "op": "eq",
                            "condition": pod_asset_id
                        }
                    }
                    
                    cmdb_response_by_id = cmdb_client.query('wecmdb', 'pod', query_by_asset_id)
                    LOG.info('[Query-3] Response status: %s', 
                            'SUCCESS' if cmdb_response_by_id and cmdb_response_by_id.get('data') else 'NO DATA')
                    
                    if cmdb_response_by_id and cmdb_response_by_id.get('data') and len(cmdb_response_by_id['data']) > 0:
                        LOG.info('[Query-3] ✅ Found %d pod(s) in CMDB by asset_id', len(cmdb_response_by_id['data']))
                        existing_pod = cmdb_response_by_id['data'][0]
                        pod_guid = existing_pod.get('guid')
                        existing_asset_id = existing_pod.get('asset_id')
                        LOG.info('[Query-3] Pod details: guid=%s, asset_id=%s, code=%s, key_name=%s, state=%s', 
                                pod_guid, existing_asset_id, existing_pod.get('code'), 
                                existing_pod.get('key_name'), existing_pod.get('state'))
                    else:
                        LOG.warning('[Query-3] ❌ Pod not found by asset_id')
                else:
                    LOG.warning('[Query-3] ⚠️  No asset_id available')
        
        # ===== 如果还是找不到，尝试模糊查询（处理命名不一致的情况） =====
        if not pod_guid:
            LOG.warning('='*60)
            LOG.warning('[Query-4] All exact matches failed, trying FUZZY search...')
            LOG.warning('[Query-4] Search criteria:')
            LOG.warning('  - code (pod name): %s', pod_name)
            LOG.warning('  - asset_id: %s', pod_asset_id if pod_asset_id else 'N/A')
            LOG.warning('='*60)
            
            # 尝试查询所有 Pod（可能是预创建但未同步的）
            try:
                LOG.info('[Query-4-Fuzzy] Step 1: Query all pods')
                fuzzy_query = {}
                fuzzy_response = cmdb_client.query('wecmdb', 'pod', fuzzy_query)
                
                if fuzzy_response and fuzzy_response.get('data') and len(fuzzy_response['data']) > 0:
                    total_pods = len(fuzzy_response['data'])
                    LOG.info('[Query-4-Fuzzy] Found %d pods', total_pods)
                    LOG.info('[Query-4-Fuzzy] Step 2: Filter by name similarity')
                    
                    # 检查是否有名称相似的 Pod
                    similar_pods = []
                    exact_match_pods = []  # 完全匹配（但可能是不同字段）
                    
                    for pod in fuzzy_response['data']:
                        pod_code = pod.get('code', '')
                        pod_key_name = pod.get('key_name', '')
                        pod_asset_id = pod.get('asset_id', '')
                        
                        # 精确匹配检查
                        is_exact = False
                        if pod_code == pod_name or pod_key_name == pod_name:
                            is_exact = True
                            exact_match_pods.append({
                                'guid': pod.get('guid'),
                                'code': pod_code,
                                'key_name': pod_key_name,
                                'asset_id': pod_asset_id,
                                'state': pod.get('state', '')
                            })
                        
                        # 模糊匹配检查（前缀或包含）
                        if not is_exact:
                            if (pod_code and (pod_name in pod_code or pod_code in pod_name)) or \
                               (pod_key_name and (pod_name in pod_key_name or pod_key_name in pod_name)):
                                similar_pods.append({
                                    'guid': pod.get('guid'),
                                    'code': pod_code,
                                    'key_name': pod_key_name,
                                    'asset_id': pod_asset_id,
                                    'state': pod.get('state', '')
                                })
                    
                    # 优先处理完全匹配
                    if exact_match_pods:
                        LOG.warning('[Query-4-Fuzzy] ✅ Found %d EXACT match(es):', len(exact_match_pods))
                        for idx, sp in enumerate(exact_match_pods, 1):
                            LOG.warning('   [%d] guid=%s, code=%s, key_name=%s, asset_id=%s, state=%s',
                                       idx, sp['guid'], sp['code'], sp['key_name'], sp['asset_id'], sp['state'])
                        
                        if len(exact_match_pods) == 1:
                            pod_guid = exact_match_pods[0]['guid']
                            existing_asset_id = exact_match_pods[0]['asset_id']
                            existing_pod = exact_match_pods[0]
                            LOG.info('[Query-4-Fuzzy] ✅ Only one exact match, will use it: guid=%s', pod_guid)
                        else:
                            # 如果有多个精确匹配，尝试通过 asset_id 区分
                            LOG.warning('[Query-4-Fuzzy] Multiple exact matches found')
                            if pod_id:
                                matching_by_asset = [p for p in exact_match_pods if p['asset_id'] == pod_id]
                                if len(matching_by_asset) == 1:
                                    pod_guid = matching_by_asset[0]['guid']
                                    existing_asset_id = matching_by_asset[0]['asset_id']
                                    existing_pod = matching_by_asset[0]
                                    LOG.info('[Query-4-Fuzzy] ✅ Found unique match by asset_id: guid=%s', pod_guid)
                                else:
                                    LOG.error('[Query-4-Fuzzy] Cannot determine which pod to delete (ambiguous)')
                            else:
                                LOG.error('[Query-4-Fuzzy] Cannot determine which pod to delete (no asset_id to compare)')
                    
                    # 如果没有精确匹配，使用相似匹配
                    elif similar_pods:
                        LOG.warning('[Query-4-Fuzzy] ⚠️  Found %d SIMILAR pods (not exact match):', len(similar_pods))
                        for idx, sp in enumerate(similar_pods, 1):
                            LOG.warning('   [%d] guid=%s, code=%s, key_name=%s, asset_id=%s, state=%s',
                                       idx, sp['guid'], sp['code'], sp['key_name'], sp['asset_id'], sp['state'])
                        
                        if len(similar_pods) == 1:
                            pod_guid = similar_pods[0]['guid']
                            existing_asset_id = similar_pods[0]['asset_id']
                            existing_pod = similar_pods[0]
                            LOG.warning('[Query-4-Fuzzy] ⚠️  Only one similar pod found, will use it: guid=%s', pod_guid)
                            LOG.warning('[Query-4-Fuzzy] Please verify this is correct!')
                        else:
                            LOG.error('[Query-4-Fuzzy] Multiple similar pods found, cannot auto-delete (ambiguous)')
                            LOG.error('[Query-4-Fuzzy] Please manually check and delete the correct record')
                    else:
                        LOG.warning('[Query-4-Fuzzy] ❌ No similar pods found in %d pods', total_pods)
                else:
                    LOG.warning('[Query-4-Fuzzy] ❌ No pods found')
            except Exception as fuzzy_err:
                LOG.error('[Query-4-Fuzzy] ❌ Fuzzy search failed: %s', str(fuzzy_err))
                LOG.exception(fuzzy_err)
        
        # ===== 执行删除操作 =====
        if not pod_guid:
            LOG.warning('='*60)
            LOG.warning('⚠️  Pod not found in CMDB (may be system pod or already deleted)')
            LOG.warning('='*60)
            LOG.warning('Pod information:')
            LOG.warning('  - name (code): %s', pod_name)
            LOG.warning('  - K8s UID (asset_id): %s', pod_id if pod_id else 'N/A')
            LOG.warning('')
            LOG.warning('Query attempts made:')
            LOG.warning('  ✗ Query by code (pod name)')
            LOG.warning('  ✗ Query by key_name')
            if pod_id:
                LOG.warning('  ✗ Query by asset_id (K8s UID)')
            LOG.warning('  ✗ Fuzzy search')
            LOG.warning('')
            LOG.warning('This is normal for:')
            LOG.warning('  - System pods (kube-system, kube-flannel, etc.)')
            LOG.warning('  - Pods not created via apply API')
            LOG.warning('  - Pods already deleted from CMDB')
            LOG.warning('='*60)
            
            # ===== 【关键修复】即使找不到 CMDB 记录，也要存入漂移缓存 =====
            # 这样 POD.ADDED 时才能快速检测到漂移，避免60秒等待
            LOG.info('[DRIFT-CACHE-FALLBACK] Caching deletion for drift detection (no CMDB record)')
            try:
                cache_key = (pod_data.get('namespace', 'default'), pod_name)
                cache_value = {
                    'timestamp': time.time(),
                    'guid': None,  # CMDB 中没有记录
                    'old_asset_id': pod_asset_id,  # 使用 K8s 的 asset_id
                    'host_ip': pod_data.get('host_ip'),
                    'cluster_id': cluster_id,  # 保存 cluster_id 供日志使用
                    'cmdb_not_found': True  # 标记 CMDB 中没找到
                }
                
                with _recently_deleted_pods_lock:
                    _recently_deleted_pods[cache_key] = cache_value
                    LOG.info('[DRIFT-CACHE-FALLBACK] ✅ Cached for drift detection:')
                    LOG.info('[DRIFT-CACHE-FALLBACK]   namespace=%s, pod=%s', 
                            pod_data.get('namespace', 'default'), pod_name)
                    LOG.info('[DRIFT-CACHE-FALLBACK]   old_asset_id=%s', pod_asset_id)
                    LOG.info('[DRIFT-CACHE-FALLBACK]   If Pod recreates within 60s, drift will be detected')
            except Exception as cache_err:
                LOG.error('[DRIFT-CACHE-FALLBACK] Failed to cache: %s', str(cache_err))
            
            return
        
        # 验证 Pod UID 是否匹配（如果提供了 pod_id）
        # asset_id 格式: {cluster_id}_{pod_uid}，我们只比较 pod_uid 部分
        uid_mismatch_detected = False  # 标记是否检测到 UID 不匹配
        if pod_id and existing_asset_id:
            # 提取 Pod UID（asset_id 中下划线后的部分）
            current_pod_uid = pod_id.split('_', 1)[-1] if '_' in pod_id else pod_id
            existing_pod_uid = existing_asset_id.split('_', 1)[-1] if '_' in existing_asset_id else existing_asset_id
            
            if current_pod_uid != existing_pod_uid:
                uid_mismatch_detected = True
                LOG.warning('='*60)
                LOG.warning('⚠️  POD UID MISMATCH DETECTED - POD DRIFT SCENARIO')
                LOG.warning('='*60)
                LOG.warning('Pod name: %s', pod_name)
                LOG.warning('CMDB Pod UID: %s', existing_pod_uid)
                LOG.warning('K8s Pod UID:  %s', current_pod_uid)
                LOG.warning('CMDB asset_id: %s', existing_asset_id)
                LOG.warning('K8s asset_id:  %s', pod_id)
                LOG.warning('')
                LOG.warning('Analysis: This is a Pod drift/eviction scenario:')
                LOG.warning('  1. Old Pod (UID: %s) was evicted/deleted from K8s', existing_pod_uid)
                LOG.warning('  2. K8s recreated Pod with new UID: %s', current_pod_uid)
                LOG.warning('  3. But CMDB still has the old Pod record (stale)')
                LOG.warning('  4. POD.DELETED event arrived AFTER POD.ADDED (event reordering)')
                LOG.warning('')
                LOG.warning('Action: WILL DELETE old Pod record (stale record cleanup)')
                LOG.warning('Reason: The record in CMDB belongs to old Pod instance')
                LOG.warning('Note: The new Pod will update CMDB in its POD.ADDED event')
                LOG.warning('      This deletion will trigger drift detection cache')
                LOG.warning('='*60)
                # 【修复】不再 return，继续执行删除操作
            elif existing_asset_id != pod_id:
                # Pod UID 匹配，但 cluster_id 不同（可能是多个 watcher 配置问题）
                LOG.info('='*60)
                LOG.info('ℹ️  CLUSTER_ID DIFFERENCE DETECTED (Pod UID matches)')
                LOG.info('='*60)
                LOG.info('Pod name: %s', pod_name)
                LOG.info('Pod UID: %s (matched)', current_pod_uid)
                LOG.info('CMDB asset_id: %s', existing_asset_id)
                LOG.info('K8s asset_id:  %s', pod_id)
                LOG.info('')
                LOG.info('This is likely due to:')
                LOG.info('  - Multiple watchers with different cluster_id configurations')
                LOG.info('  - cluster_id was changed in configuration')
                LOG.info('')
                LOG.info('Action: Proceeding with deletion (Pod UID matches)')
                LOG.info('='*60)
        
        # 执行删除操作
        try:
            LOG.info('='*60)
            LOG.info('[DELETE] Preparing to delete pod from CMDB')
            LOG.info('[DELETE] Target pod details:')
            LOG.info('  - guid: %s', pod_guid)
            LOG.info('  - code: %s', existing_pod.get('code') if existing_pod else pod_name)
            LOG.info('  - key_name: %s', existing_pod.get('key_name') if existing_pod else 'N/A')
            LOG.info('  - asset_id: %s', existing_asset_id if existing_asset_id else 'N/A')
            LOG.info('')
            
            LOG.info('[DELETE] Executing CMDB delete operation...')
            cmdb_client.delete('wecmdb', 'pod', [{'guid': pod_guid}])
            
            LOG.info('='*60)
            LOG.info('✅ Successfully deleted pod from CMDB')
            LOG.info('  - Pod name: %s', pod_name)
            LOG.info('  - GUID: %s', pod_guid)
            LOG.info('  - Asset ID: %s', existing_asset_id if existing_asset_id else 'N/A')
            if uid_mismatch_detected:
                LOG.info('  - Scenario: UID mismatch (stale record cleanup)')
                LOG.info('  - Old UID in CMDB: %s', existing_pod_uid if 'existing_pod_uid' in locals() else 'N/A')
                LOG.info('  - New UID in K8s:  %s', current_pod_uid if 'current_pod_uid' in locals() else 'N/A')
            LOG.info('='*60)
            
            # ===== 存入"最近删除的 Pod"缓存，用于后续快速检测 Pod 漂移场景 =====
            cache_key = (pod_data.get('namespace', 'default'), pod_name)
            cache_value = {
                'timestamp': time.time(),
                'guid': pod_guid,
                'old_asset_id': existing_asset_id,  # 使用 CMDB 中的 asset_id（可能是旧的）
                'host_ip': existing_pod.get('host_resource') if existing_pod else None,  # 保存旧的 host_resource
                'cluster_id': cluster_id,  # 保存 cluster_id 供日志使用（非 key 的一部分）
                'uid_mismatch': uid_mismatch_detected  # 标记是否 UID 不匹配
            }
            
            with _recently_deleted_pods_lock:
                _recently_deleted_pods[cache_key] = cache_value
                LOG.info('[DRIFT-CACHE] Added to recently deleted pods cache:')
                LOG.info('[DRIFT-CACHE]   Key: namespace=%s, pod_name=%s', 
                        pod_data.get('namespace', 'default'), pod_name)
                LOG.info('[DRIFT-CACHE]   Value: guid=%s, old_asset_id=%s', 
                        pod_guid, existing_asset_id)
                if uid_mismatch_detected:
                    LOG.info('[DRIFT-CACHE]   Note: UID mismatch detected - stale record cleanup')
                    LOG.info('[DRIFT-CACHE]   This means POD.ADDED already arrived with new UID')
                LOG.info('[DRIFT-CACHE]   TTL: %d seconds (for drift detection)', 
                        _recently_deleted_pods_window)
        except Exception as del_err:
            LOG.error('='*60)
            LOG.error('❌ DELETE FAILED: CMDB delete operation error')
            LOG.error('='*60)
            LOG.error('Target pod:')
            LOG.error('  - name: %s', pod_name)
            LOG.error('  - guid: %s', pod_guid)
            LOG.error('Error: %s', str(del_err))
            LOG.exception(del_err)
            LOG.error('')
            LOG.error('Possible causes:')
            LOG.error('  1. Network connection to CMDB failed')
            LOG.error('  2. Authentication token expired')
            LOG.error('  3. Pod record no longer exists')
            LOG.error('  4. Insufficient permissions')
            LOG.error('')
            LOG.error('Recommendation: Check CMDB logs and retry manually')
            LOG.error('='*60)
            raise
    
    except Exception as e:
        LOG.error('Failed to sync POD.DELETED to CMDB for pod %s: %s', 
                 pod_data.get('name', 'unknown'), str(e))
        LOG.exception(e)
        
        # ===== 容错机制：即使 CMDB 失败，也要存入缓存（用于漂移检测） =====
        LOG.warning('='*60)
        LOG.warning('⚠️  CMDB OPERATION FAILED - Using fallback cache strategy')
        LOG.warning('='*60)
        LOG.warning('Even though CMDB sync failed, we will cache this deletion')
        LOG.warning('This allows drift detection to work even when CMDB is unavailable')
        
        try:
            # 使用 Pod 的基本信息建立缓存（不需要 CMDB GUID）
            namespace = pod_data.get('namespace', 'default')
            cache_key = (namespace, pod_name)
            cache_value = {
                'timestamp': time.time(),
                'guid': None,  # CMDB 不可用，无法获取 GUID
                'old_asset_id': pod_asset_id,  # 使用 K8s 的 asset_id
                'host_ip': pod_data.get('host_ip'),  # 使用 K8s 的 host_ip
                'cluster_id': cluster_id,  # 保存 cluster_id 供日志使用
                'cmdb_unavailable': True  # 标记 CMDB 不可用
            }
            
            with _recently_deleted_pods_lock:
                _recently_deleted_pods[cache_key] = cache_value
                LOG.warning('[DRIFT-CACHE-FALLBACK] Added to cache despite CMDB failure:')
                LOG.warning('[DRIFT-CACHE-FALLBACK]   Key: namespace=%s, pod_name=%s', 
                           namespace, pod_name)
                LOG.warning('[DRIFT-CACHE-FALLBACK]   Value: old_asset_id=%s, host_ip=%s', 
                           pod_asset_id, pod_data.get('host_ip'))
                LOG.warning('[DRIFT-CACHE-FALLBACK]   Note: guid=None (CMDB unavailable)')
                LOG.warning('[DRIFT-CACHE-FALLBACK]   This allows drift detection even if CMDB is down')
        except Exception as cache_err:
            LOG.error('Failed to add fallback cache entry: %s', str(cache_err))
        
        LOG.warning('='*60)


def notify_pod(event, cluster_id, data):
    """通知 WeCube 编排引擎 Pod 事件（先同步 CMDB，再发送通知）"""
    LOG.info('=' * 80)
    LOG.info('notify_pod started - event: %s, cluster: %s', event, cluster_id)
    LOG.info('Pod details - name: %s, namespace: %s, id: %s', 
             data.get('name', 'N/A'), data.get('namespace', 'N/A'), data.get('id', 'N/A'))
    LOG.info('Pod location - node: %s, host_ip: %s', 
             data.get('node_id', 'N/A'), data.get('host_ip', 'N/A'))
    LOG.info('Pod controller - deployment: %s, statefulset: %s, replicaset: %s',
             data.get('deployment_id', 'N/A'), data.get('statefulset_id', 'N/A'), data.get('replicaset_id', 'N/A'))
    LOG.info('Full pod data: %s', data)
    
    try:
        # ===== 事件去重检查 =====
        pod_uid = data.get('id')  # Kubernetes Pod UID
        if not pod_uid:
            LOG.error('Pod UID not found in data, cannot perform deduplication check')
        else:
            event_key = (pod_uid, event)
            current_time = time.time()
            
            with _event_dedup_lock:
                # 清理过期的缓存条目（超过去重窗口的）
                expired_keys = [k for k, t in _event_dedup_cache.items() 
                               if current_time - t > _event_dedup_window]
                for k in expired_keys:
                    del _event_dedup_cache[k]
                
                # 检查是否是重复事件
                if event_key in _event_dedup_cache:
                    time_since_last = current_time - _event_dedup_cache[event_key]
                    LOG.warning('=' * 80)
                    LOG.warning('🔄 DUPLICATE EVENT DETECTED - SKIPPING')
                    LOG.warning('Event: %s, Pod UID: %s', event, pod_uid)
                    LOG.warning('Time since last event: %.2f seconds', time_since_last)
                    LOG.warning('Dedup window: %d seconds', _event_dedup_window)
                    LOG.warning('This is likely a retry or duplicate notification from Kubernetes')
                    LOG.warning('=' * 80)
                    return
                
                # 记录本次事件
                _event_dedup_cache[event_key] = current_time
                LOG.info('✅ Event deduplication check passed - this is a new event')
                LOG.info('Event key: %s, Total cached events: %d', event_key, len(_event_dedup_cache))
        
        # ===== 第一步：同步 CMDB（在通知之前） =====
        # 注意：无论是预期创建还是漂移，都需要同步 CMDB（填充 asset_id）
        # 区别在于是否发送 WeCube 通知（预期创建不发送，漂移才发送）
        LOG.info('-' * 40)
        LOG.info('Step 1: Start CMDB synchronization')
        
        pod_cmdb_guid = None  # 用于存储 CMDB 中 Pod 的 GUID
        is_pod_drift = False  # 用于标记是否是 Pod 漂移场景（需要发送通知）
        
        if event == 'POD.ADDED':
            LOG.info('Event type: POD.ADDED - will create record in CMDB')
            LOG.info('Calling sync_pod_to_cmdb_on_added with pod_id: %s', data.get('id'))
            pod_cmdb_guid, is_pod_drift = sync_pod_to_cmdb_on_added(data)
            
            if pod_cmdb_guid:
                LOG.info('CMDB sync completed successfully for POD.ADDED - GUID: %s', pod_cmdb_guid)
                if is_pod_drift:
                    LOG.info('🔔 Pod drift detected - WeCube notification will be sent')
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
        
        # ===== 预期 Pod 创建检查（只针对 POD.ADDED 事件）=====
        # 如果是通过 apply API 创建的 Pod，跳过 WeCube 通知（CMDB 已经更新过了）
        if event == 'POD.ADDED':
            pod_name = data.get('name')
            pod_namespace = data.get('namespace')
            
            # 【修复】优先检查 Pod annotations 中的创建来源标记
            # 这是跨进程的标记（存储在 K8s Pod 对象中），不受进程间内存隔离影响
            created_by = data.get('annotations', {}).get('wecube.io/created-by', '')
            
            # 【修复 2】如果是 Pod 漂移场景，即使有 API 标记，也要发送通知
            if created_by == 'api' and not is_pod_drift:
                LOG.warning('=' * 80)
                LOG.warning('🏷️  API-CREATED POD DETECTED - SKIPPING WECUBE NOTIFICATION')
                LOG.warning('Pod: %s, Namespace: %s, Cluster: %s', pod_name, pod_namespace or 'N/A', cluster_id)
                LOG.warning('Detection method: Pod annotation "wecube.io/created-by" = "api"')
                LOG.warning('This Pod was created via API (StatefulSet apply), not due to drift/crash')
                LOG.warning('CMDB has been updated (asset_id filled), but notification is skipped')
                LOG.warning('=' * 80)
                LOG.info('notify_pod completed - API-created Pod, CMDB updated, no notification sent')
                return
            elif created_by == 'api' and is_pod_drift:
                LOG.warning('=' * 80)
                LOG.warning('🔔 POD DRIFT DETECTED - WILL SEND NOTIFICATION')
                LOG.warning('Pod: %s, Namespace: %s, Cluster: %s', pod_name, pod_namespace or 'N/A', cluster_id)
                LOG.warning('Although Pod has "wecube.io/created-by" = "api" annotation,')
                LOG.warning('it was created due to Pod drift/eviction (race condition detected)')
                LOG.warning('CMDB has been updated, and notification WILL be sent')
                LOG.warning('=' * 80)
            
            # 备用检查：进程内缓存（仅作为第二层保护，处理 annotation 标记失败的情况）
            if pod_name and pod_namespace:
                is_expected, info = is_expected_pod(cluster_id, pod_namespace, pod_name)
                
                if is_expected:
                    LOG.warning('=' * 80)
                    LOG.warning('🏷️  EXPECTED POD CREATION DETECTED (Cache) - SKIPPING WECUBE NOTIFICATION')
                    LOG.warning('Pod: %s, Namespace: %s, Cluster: %s', pod_name, pod_namespace, cluster_id)
                    LOG.warning('Source: %s, Time since marked: %.2f seconds', 
                               info.get('source', 'unknown'), info.get('time_since_mark', 0))
                    LOG.warning('Detection method: In-process cache (may not work across processes)')
                    LOG.warning('This Pod was created via API (StatefulSet apply), not due to drift/crash')
                    LOG.warning('CMDB has been updated (asset_id filled), but notification is skipped')
                    LOG.warning('=' * 80)
                    LOG.info('notify_pod completed - expected Pod creation, CMDB updated, no notification sent')
                    return
                else:
                    LOG.info('✅ Pod NOT marked as API-created - this is a drift/crash/restart event')
                    LOG.info('Watcher will send WeCube notification')
            else:
                LOG.warning('Pod name or namespace missing, cannot check expected Pod list')
        
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
        LOG.info('WeCube endpoint: %s', CONF.wecube.base_url)
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
    """监听单个集群的 Pod 事件（带指数退避重试）
    
    多 watcher 安全性说明：
    - 多个 watcher 同时监听同一集群是安全的（通过 CMDB 唯一性约束 + 幂等操作保证）
    - 创建操作：CMDB 的 code 字段有唯一性约束，多个 watcher 创建时只有一个成功，
      其他失败后会查询到已存在的记录并更新
    - 更新操作：完全幂等，多个 watcher 同时更新同一 Pod 不会产生副作用
    - 查询操作：只读，无并发问题
    - 删除操作：通过 guid 删除，即使多次删除也只会删除一次（第二次会报错但不影响数据）
    - 进程内去重：30秒窗口避免同一 watcher 重复处理
    - 跨进程去重：依赖 CMDB 唯一性约束（自动处理）
    
    Pod 漂移处理：
    - 漂移时 Pod 会先删除再创建（UID 变化）
    - Watcher 会监听到 POD.DELETED 和 POD.ADDED 两个事件
    - POD.DELETED：从 CMDB 删除旧 Pod 记录
    - POD.ADDED：重试查询（等待 apply API），找不到则创建新记录（从 StatefulSet 继承 app_instance）
    
    重连策略：
    - 稳定连接超时断开（如 TCP 4 分钟超时）：快速重连（0.5 秒）
    - 持续连接失败（如 API Server 故障）：指数退避（最高 60 秒）
    - 稳定运行阈值：60 秒（超过此时间断开视为正常超时，非故障）
    
    建议：
    - 生产环境可以运行多个 watcher 实例（已确保安全性和一致性）
    - 建议 2-3 个实例，提供高可用性同时避免过多日志
    - 如需更高可用，使用 Kubernetes Deployment + HPA
    """
    retry_delay = 0.1  # 初始延迟 0.1 秒
    max_retry_delay = 60  # 最大延迟 60 秒
    stable_threshold = 60  # 稳定运行阈值：60 秒（超过此时间断开视为正常超时，非故障）
    
    cluster_name = cluster.get('name', cluster['id'])
    LOG.info('Starting pod watcher for cluster: %s', cluster_name)
    
    while not event_stop.is_set():
        start_time = time.time()  # 记录连接开始时间
        
        try:
            api.Pod().watch(cluster, event_stop, notify_pod)
            retry_delay = 0.1  # 成功后重置延迟
        except Exception as e:
            # 计算连接持续时间
            connection_duration = time.time() - start_time
            
            # 区分预期内的连接中断（ProtocolError）和真正的错误
            is_connection_error = isinstance(e, (
                urllib3.exceptions.ProtocolError,
                urllib3.exceptions.TimeoutError,
                ConnectionError,
            )) or 'Connection broken' in str(e) or 'InvalidChunkLength' in str(e)
            
            if is_connection_error:
                # 连接中断是正常现象（超时重连），只记录 WARNING 级别
                LOG.warning('Watch connection interrupted for cluster %s after %.1fs: %s (auto-retrying)', 
                           cluster_name, connection_duration, str(e)[:150])  # 只输出前150个字符
                
                # 如果连接稳定运行超过阈值，说明不是持续失败，重置延迟
                if connection_duration >= stable_threshold:
                    LOG.info('Connection was stable for %.1fs (>= %ds threshold), resetting retry delay to 0.1s', 
                            connection_duration, stable_threshold)
                    retry_delay = 0.1
            else:
                # 其他异常记录完整的错误信息
                LOG.error('Exception raised while watching pod from cluster %s after %.1fs', 
                         cluster_name, connection_duration)
                LOG.exception(e)
            
            # 指数退避：0.5s -> 1s -> 2s -> 4s -> 8s -> ... -> 60s
            # 但如果上面检测到稳定连接，retry_delay 已被重置为 0.5s
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