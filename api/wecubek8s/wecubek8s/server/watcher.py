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
            
            LOG.info('Creating CMDB client for server: %s with WeCube token', cmdb_server)
            _cmdb_client = wecmdb.EntityClient(cmdb_server, wecube_client.token)
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
        
        LOG.info('='*60)
        LOG.info('Syncing POD.ADDED to CMDB: pod=%s, id=%s, host_ip=%s', 
                 pod_name, pod_id, pod_host_ip or 'N/A')
        LOG.info('Deployment/StatefulSet: %s', app_instance_id or 'N/A')
        
        # ===== 步骤1：通过 code（Pod name）查询 =====
        # StatefulSet Pod name 是稳定的，部署时可能已预创建记录
        query_data = {
            "criteria": {
                "attrName": "code",
                "op": "eq",
                "condition": pod_name
            }
        }
        
        LOG.info('[Step 1] Querying CMDB by code: %s', pod_name)
        cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
        LOG.info('[Step 1] Query result: found %d record(s)', 
                len(cmdb_response.get('data', [])) if cmdb_response else 0)
        
        # ===== 步骤2：如果通过 code 找到记录，则更新（包括预创建的和重建的） =====
        if cmdb_response and cmdb_response.get('data') and len(cmdb_response['data']) > 0:
            existing_pod = cmdb_response['data'][0]
            pod_guid = existing_pod.get('guid')
            existing_asset_id = existing_pod.get('asset_id')
            existing_host_resource = existing_pod.get('host_resource')
            
            LOG.info('[Step 2] Found existing pod by code: guid=%s, asset_id=%s', 
                    pod_guid, existing_asset_id or 'NULL')
            
            if not pod_guid:
                LOG.warning('CMDB pod record has no guid, cannot update: %s', pod_name)
                return None
            
            # 判断是否是预创建的记录（asset_id 为空）或 Pod 重建（asset_id 不同）
            is_pre_created = (not existing_asset_id or existing_asset_id == '')
            is_pod_rebuilt = (existing_asset_id and existing_asset_id != pod_id)
            
            if is_pre_created:
                LOG.info('✅ Found PRE-CREATED pod record (asset_id is empty), will UPDATE it')
                LOG.info('   This is expected for StatefulSet/Deployment pods created via API')
            elif is_pod_rebuilt:
                LOG.info('🔄 Pod %s REBUILT detected: old UID=%s, new UID=%s, updating...', 
                        pod_name, existing_asset_id, pod_id)
                LOG.info('   This could be due to: pod restart, node eviction (taint), or manual deletion')
            else:
                LOG.info('Pod %s already exists with same asset_id, updating metadata', pod_name)
            
            # 如果是 Pod 重建（不是预创建），检查新的 asset_id 是否已被其他记录使用
            if is_pod_rebuilt:
                # 检查新的 asset_id 是否已被其他记录使用（防止重复）
                check_query = {
                    "criteria": {
                        "attrName": "asset_id",
                        "op": "eq",
                        "condition": pod_id
                    }
                }
                check_response = cmdb_client.query('wecmdb', 'pod', check_query)
                
                # 如果新 asset_id 已存在且不是当前记录，删除重复记录
                if check_response and check_response.get('data'):
                    for duplicate_pod in check_response['data']:
                        dup_guid = duplicate_pod.get('guid')
                        if dup_guid and dup_guid != pod_guid:
                            LOG.warning('⚠️  Found duplicate pod with same asset_id %s (guid=%s), deleting...', 
                                       pod_id, dup_guid)
                            try:
                                cmdb_client.delete('wecmdb', 'pod', [dup_guid])
                                LOG.info('✅ Deleted duplicate pod record: guid=%s', dup_guid)
                            except Exception as del_err:
                                LOG.error('Failed to delete duplicate pod: %s', str(del_err))
            
            update_data = {
                'guid': pod_guid,
                'asset_id': pod_id  # 更新为新的 UID（StatefulSet Pod 重建时必须）
            }
            
            # 查询并关联 host_resource（Pod 漂移时宿主机可能会变化）
            if pod_host_ip:
                host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                if host_resource_guid:
                    update_data['host_resource'] = host_resource_guid
                    
                    # 检测 host_resource 是否发生变化
                    if existing_host_resource != host_resource_guid:
                        LOG.info('🚀 POD DRIFT DETECTED! Pod %s moved to different host:', pod_name)
                        LOG.info('   Old host_resource: %s', existing_host_resource or 'None')
                        LOG.info('   New host_resource: %s (IP: %s)', host_resource_guid, pod_host_ip)
                        LOG.info('   Reason: likely node eviction/taint or manual rescheduling')
                    else:
                        LOG.info('Pod %s host unchanged: host_resource=%s (IP: %s)', 
                                pod_name, host_resource_guid, pod_host_ip)
                else:
                    LOG.warning('Failed to query host_resource for pod %s (IP: %s)', pod_name, pod_host_ip)
            else:
                LOG.warning('Pod %s has no host IP, cannot update host_resource', pod_name)
            
            # 关联 app_instance（如果有）
            if app_instance_id:
                update_data['app_instance'] = app_instance_id
            
            update_response = cmdb_client.update('wecmdb', 'pod', [update_data])
            LOG.info('[Step 2] ✅ Successfully UPDATED existing pod in CMDB: %s (guid: %s, asset_id: %s)', 
                    pod_name, pod_guid, pod_id)
            LOG.info('='*60)
            return pod_guid
        else:
            # ===== 步骤3：通过 code 未找到，检查 asset_id 是否已存在 =====
            # 防止 CMDB 中有孤儿记录（code 不同但 asset_id 相同）
            LOG.info('[Step 3] Pod not found by code, checking by asset_id: %s', pod_id)
            check_query = {
                "criteria": {
                    "attrName": "asset_id",
                    "op": "eq",
                    "condition": pod_id
                }
            }
            check_response = cmdb_client.query('wecmdb', 'pod', check_query)
            LOG.info('[Step 3] Query result: found %d record(s) by asset_id', 
                    len(check_response.get('data', [])) if check_response else 0)
            
            if check_response and check_response.get('data') and len(check_response['data']) > 0:
                # 发现有相同 asset_id 的记录，更新它（可能是 code 不一致）
                existing_pod = check_response['data'][0]
                pod_guid = existing_pod.get('guid')
                existing_code = existing_pod.get('code')
                LOG.warning('[Step 3] ⚠️  Found existing pod by asset_id but with different code!')
                LOG.warning('   Expected code: %s', pod_name)
                LOG.warning('   Existing code: %s', existing_code)
                LOG.warning('   Will UPDATE the record (guid=%s)', pod_guid)
                
                update_data = {
                    'guid': pod_guid,
                    'code': pod_name,  # 更新 code 为正确的名称
                    'asset_id': pod_id
                }
                
                # 关联 app_instance
                if app_instance_id:
                    update_data['app_instance'] = app_instance_id
                
                # 查询并关联 host_resource
                if pod_host_ip:
                    host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                    if host_resource_guid:
                        update_data['host_resource'] = host_resource_guid
                
                cmdb_client.update('wecmdb', 'pod', [update_data])
                LOG.info('[Step 3] ✅ Successfully UPDATED pod with correct code: %s (guid: %s)', pod_name, pod_guid)
                LOG.info('='*60)
                return pod_guid
            
            # ===== 步骤4：双重确认后创建新记录 =====
            LOG.info('[Step 4] Pod not found by code or asset_id, creating new record...')
            LOG.warning('[Step 4] ⚠️  ATTENTION: Creating new pod record')
            LOG.warning('   If you see duplicate records, check if deployment pre-created pods with different code values')
            
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
            
            try:
                create_response = cmdb_client.create('wecmdb', 'pod', [create_data])
                
                # 从创建响应中获取 GUID
                pod_guid = None
                if create_response and create_response.get('data') and len(create_response['data']) > 0:
                    pod_guid = create_response['data'][0].get('guid')
                
                if pod_guid:
                    LOG.info('[Step 4] ✅ Successfully CREATED new pod in CMDB: %s (asset_id: %s, guid: %s)', 
                            pod_name, pod_id, pod_guid)
                    LOG.info('='*60)
                    return pod_guid
                else:
                    LOG.warning('[Step 4] Pod created in CMDB but no GUID returned: %s', pod_name)
                    LOG.info('='*60)
                    return None
            
            except Exception as create_err:
                # 如果创建失败（可能是唯一性冲突），尝试查询并更新
                error_msg = str(create_err)
                LOG.warning('[Step 4] ⚠️  Pod creation FAILED: %s', error_msg)
                if 'Unique validate fail' in error_msg or 'key_name' in error_msg or 'unique' in error_msg.lower():
                    LOG.warning('[Step 4] Detected uniqueness conflict (likely pre-created by API)')
                    LOG.warning('   This is expected when deploying StatefulSet/Deployment via API')
                    LOG.warning('   Will retry query by code (pod name) with small delay to handle race condition')
                    
                    # 等待一小段时间（并发情况下，另一个线程可能刚创建完，数据库事务还没提交）
                    import time
                    time.sleep(0.1)
                    
                    # 尝试 1: 再次按 code 查询（可能是并发创建）
                    LOG.info('[Step 4-Retry-1] Retrying query by code (pod name): %s', pod_name)
                    retry_query_code = {
                        "criteria": {
                            "attrName": "code",
                            "op": "eq",
                            "condition": pod_name
                        }
                    }
                    retry_response = cmdb_client.query('wecmdb', 'pod', retry_query_code)
                    
                    if retry_response and retry_response.get('data') and len(retry_response['data']) > 0:
                        existing_pod = retry_response['data'][0]
                        pod_guid = existing_pod.get('guid')
                        existing_asset_id = existing_pod.get('asset_id')
                        LOG.info('[Step 4-Retry-1] ✅ Found pre-created pod by code (pod name)!')
                        LOG.info('   guid=%s, asset_id=%s (empty means pre-created)', 
                                pod_guid, existing_asset_id or 'EMPTY')
                        
                        # 更新记录（填充 asset_id 和其他信息）
                        update_data = {
                            'guid': pod_guid,
                            'code': pod_name,  # 确保 code 正确
                            'asset_id': pod_id  # 填充真实的 K8s Pod UID
                        }
                        
                        if app_instance_id:
                            update_data['app_instance'] = app_instance_id
                        
                        if pod_host_ip:
                            host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                            if host_resource_guid:
                                update_data['host_resource'] = host_resource_guid
                                LOG.info('   Will update host_resource to: %s (IP: %s)', host_resource_guid, pod_host_ip)
                        
                        cmdb_client.update('wecmdb', 'pod', [update_data])
                        LOG.info('[Step 4-Retry-1] ✅ Successfully UPDATED pre-created pod: %s (guid=%s)', 
                                pod_name, pod_guid)
                        LOG.info('='*60)
                        return pod_guid
                    
                    # 尝试 2: 按 asset_id 查询（极少数情况：code 不同但 asset_id 相同）
                    LOG.info('[Step 4-Retry-2] Code query still failed, trying asset_id: %s', pod_id)
                    retry_query_asset = {
                        "criteria": {
                            "attrName": "asset_id",
                            "op": "eq",
                            "condition": pod_id
                        }
                    }
                    retry_response = cmdb_client.query('wecmdb', 'pod', retry_query_asset)
                    
                    if retry_response and retry_response.get('data') and len(retry_response['data']) > 0:
                        existing_pod = retry_response['data'][0]
                        pod_guid = existing_pod.get('guid')
                        existing_code = existing_pod.get('code')
                        LOG.warning('[Step 4-Retry-2] ⚠️  Found pod by asset_id with different code!')
                        LOG.warning('   Expected code: %s, Existing code: %s', pod_name, existing_code)
                        LOG.info('[Step 4-Retry-2] Updating to correct code: %s (guid=%s)', pod_name, pod_guid)
                        
                        # 更新记录
                        update_data = {
                            'guid': pod_guid,
                            'code': pod_name,  # 更正 code
                            'asset_id': pod_id
                        }
                        
                        if app_instance_id:
                            update_data['app_instance'] = app_instance_id
                        
                        if pod_host_ip:
                            host_resource_guid = query_host_resource_guid(cmdb_client, pod_host_ip)
                            if host_resource_guid:
                                update_data['host_resource'] = host_resource_guid
                        
                        cmdb_client.update('wecmdb', 'pod', [update_data])
                        LOG.info('[Step 4-Retry-2] ✅ Successfully UPDATED pod with correct code: %s (guid=%s)', 
                                pod_name, pod_guid)
                        LOG.info('='*60)
                        return pod_guid
                    else:
                        LOG.error('[Step 4-Retry] ❌ Cannot find existing pod by code or asset_id after retry')
                        LOG.error('   Pod name (code): %s, asset_id: %s', pod_name, pod_id)
                        LOG.error('   This suggests a race condition or database inconsistency')
                        LOG.error('   Recommendation: manually check CMDB pod table for orphan records')
                        LOG.info('='*60)
                        raise  # Re-raise original exception
                else:
                    # 其他类型的错误，直接抛出
                    LOG.error('[Step 4] Unexpected error during pod creation: %s', error_msg)
                    LOG.info('='*60)
                    raise
    
    except Exception as e:
        LOG.error('='*60)
        LOG.error('❌ FATAL ERROR: Failed to sync POD.ADDED to CMDB')
        LOG.error('Pod name: %s, Pod ID: %s', pod_data.get('name', 'unknown'), pod_data.get('id', 'unknown'))
        LOG.error('Error: %s', str(e))
        LOG.exception(e)
        LOG.error('='*60)
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
        
        LOG.info('='*60)
        LOG.info('🗑️  Syncing POD.DELETED to CMDB: pod=%s, id=%s', pod_name, pod_id)
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
                if pod_id:
                    LOG.info('[Query-3] Trying to query by asset_id: %s', pod_id)
                    query_by_asset_id = {
                        "criteria": {
                            "attrName": "asset_id",
                            "op": "eq",
                            "condition": pod_id
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
                    LOG.warning('[Query-3] ⚠️  No asset_id available (K8s Pod UID missing)')
        
        # ===== 如果还是找不到，尝试模糊查询（处理命名不一致的情况） =====
        if not pod_guid:
            LOG.warning('='*60)
            LOG.warning('[Query-4] All exact matches failed, trying FUZZY search...')
            LOG.warning('[Query-4] Search criteria:')
            LOG.warning('  - code (pod name): %s', pod_name)
            LOG.warning('  - asset_id (K8s UID): %s', pod_id if pod_id else 'N/A')
            LOG.warning('='*60)
            
            # 尝试查询所有状态为 created_0 的 Pod（可能是预创建但未同步的）
            try:
                LOG.info('[Query-4-Fuzzy] Step 1: Query all pods with state=created_0')
                fuzzy_query = {
                    "criteria": {
                        "attrName": "state",
                        "op": "eq",
                        "condition": "created_0"
                    }
                }
                fuzzy_response = cmdb_client.query('wecmdb', 'pod', fuzzy_query)
                
                if fuzzy_response and fuzzy_response.get('data') and len(fuzzy_response['data']) > 0:
                    total_created_pods = len(fuzzy_response['data'])
                    LOG.info('[Query-4-Fuzzy] Found %d pods in created_0 state', total_created_pods)
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
                        LOG.warning('[Query-4-Fuzzy] ✅ Found %d EXACT match(es) in created_0 pods:', len(exact_match_pods))
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
                        LOG.warning('[Query-4-Fuzzy] ❌ No similar pods found in %d created_0 pods', total_created_pods)
                else:
                    LOG.warning('[Query-4-Fuzzy] ❌ No pods in created_0 state')
            except Exception as fuzzy_err:
                LOG.error('[Query-4-Fuzzy] ❌ Fuzzy search failed: %s', str(fuzzy_err))
                LOG.exception(fuzzy_err)
        
        # ===== 执行删除操作 =====
        if not pod_guid:
            LOG.error('='*60)
            LOG.error('❌ DELETION FAILED: Pod not found in CMDB')
            LOG.error('='*60)
            LOG.error('Pod information:')
            LOG.error('  - name (code): %s', pod_name)
            LOG.error('  - K8s UID (asset_id): %s', pod_id if pod_id else 'N/A')
            LOG.error('')
            LOG.error('Query attempts made:')
            LOG.error('  ✗ Query by code (pod name)')
            LOG.error('  ✗ Query by key_name')
            if pod_id:
                LOG.error('  ✗ Query by asset_id (K8s UID)')
            LOG.error('  ✗ Fuzzy search in created_0 pods')
            LOG.error('')
            LOG.error('📋 Manual cleanup required:')
            LOG.error('  1. Open WeCMDB UI: %s', CONF.wecube.base_url if CONF.wecube.base_url else '<cmdb-url>')
            LOG.error('  2. Navigate to: Data Management → Pod table')
            LOG.error('  3. Search conditions:')
            LOG.error('     - code LIKE "%%%s%%"', pod_name[:40])
            LOG.error('     - OR key_name LIKE "%%%s%%"', pod_name[:40])
            if pod_id:
                LOG.error('     - OR asset_id = "%s"', pod_id)
            LOG.error('  4. Check the found record(s) and delete manually')
            LOG.error('  5. Or use CMDB API to delete:')
            LOG.error('     curl -X DELETE %s/wecmdb/api/v1/ci/pod/<guid>', 
                     CONF.wecube.base_url if CONF.wecube.base_url else '<cmdb-url>')
            LOG.error('='*60)
            return
        
        # 验证 asset_id 是否匹配（如果提供了 pod_id）
        if pod_id and existing_asset_id and existing_asset_id != pod_id:
            LOG.warning('='*60)
            LOG.warning('⚠️  ASSET_ID MISMATCH DETECTED')
            LOG.warning('='*60)
            LOG.warning('Pod name: %s', pod_name)
            LOG.warning('CMDB asset_id: %s', existing_asset_id)
            LOG.warning('K8s Pod UID:   %s', pod_id)
            LOG.warning('')
            LOG.warning('This suggests one of the following:')
            LOG.warning('  1. Pod was recreated with same name but different UID')
            LOG.warning('  2. CMDB record is stale (old Pod instance)')
            LOG.warning('  3. Name collision between different pods')
            LOG.warning('')
            LOG.warning('Action: Skipping deletion to avoid removing wrong record')
            LOG.warning('Recommendation: Manually verify and cleanup in CMDB UI')
            LOG.warning('='*60)
            return
        
        # 执行删除
        try:
            LOG.info('='*60)
            LOG.info('[DELETE] Preparing to delete pod from CMDB')
            LOG.info('[DELETE] Target pod details:')
            LOG.info('  - guid: %s', pod_guid)
            LOG.info('  - code: %s', existing_pod.get('code') if existing_pod else pod_name)
            LOG.info('  - key_name: %s', existing_pod.get('key_name') if existing_pod else 'N/A')
            LOG.info('  - asset_id: %s', existing_asset_id if existing_asset_id else 'N/A')
            LOG.info('  - state: %s', existing_pod.get('state') if existing_pod else 'N/A')
            LOG.info('')
            
            LOG.info('[DELETE] Executing CMDB delete operation...')
            cmdb_client.delete('wecmdb', 'pod', [pod_guid])
            
            LOG.info('='*60)
            LOG.info('✅ Successfully deleted pod from CMDB')
            LOG.info('  - Pod name: %s', pod_name)
            LOG.info('  - GUID: %s', pod_guid)
            LOG.info('  - Asset ID: %s', existing_asset_id if existing_asset_id else 'N/A')
            LOG.info('='*60)
        except Exception as del_err:
            LOG.error('='*60)
            LOG.error('❌ DELETION FAILED: CMDB delete operation error')
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
            LOG.error('  3. Pod record has dependencies (foreign key constraints)')
            LOG.error('  4. Insufficient permissions')
            LOG.error('')
            LOG.error('Recommendation: Check CMDB logs and retry manually')
            LOG.error('='*60)
            raise
    
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
    LOG.info('Pod location - node: %s, host_ip: %s', 
             data.get('node_id', 'N/A'), data.get('host_ip', 'N/A'))
    LOG.info('Pod controller - deployment: %s, statefulset: %s, replicaset: %s',
             data.get('deployment_id', 'N/A'), data.get('statefulset_id', 'N/A'), data.get('replicaset_id', 'N/A'))
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
