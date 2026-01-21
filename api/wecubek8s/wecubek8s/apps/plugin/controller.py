# coding=utf-8

from __future__ import absolute_import

import logging
import json
import ast
from talos.db import crud
from talos.core import config
from talos.core.i18n import _

from wecubek8s.common import controller
from wecubek8s.common import exceptions
from wecubek8s.common import utils as k8s_utils
from wecubek8s.apps.plugin import rules
from wecubek8s.apps.plugin import api as plugin_api

CONF = config.CONF
LOG = logging.getLogger(__name__)


class Cluster(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.cluster'
    
    # 需要检查预解密的字段列表
    # 注意：这里只列出可能以加密格式 {cipher_a}xxx 传入的字段
    # 如果客户端传入的是明文，代码会自动跳过（通过 startswith 判断）
    # 如果你确定 image_pull_password 总是明文，可以移除它
    ENCRYPTED_FIELDS = ['token']  # image_pull_password 通常是明文，不需要预解密

    def set_item_default(self, item):
        defaults = {}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value
    
    def decrypt_incoming_fields(self, item):
        """
        解密客户端传入的已加密字段
        如果客户端发送的是 {cipher_a}xxx 格式的加密数据，需要先解密
        然后系统会在入库时重新加密
        """
        # 生成一个临时的 guid 用于解密客户端传入的加密数据
        # 客户端加密时使用的 guid 通常是 correlation_id 或者固定值
        decrypt_guid = item.get('correlation_id', item.get('name', ''))
        
        for field in self.ENCRYPTED_FIELDS:
            if field in item and item[field]:
                field_value = item[field]
                # 检查是否是加密格式
                if isinstance(field_value, str) and field_value.startswith('{cipher_a}'):
                    try:
                        # 使用 platform_encrypt_seed 解密
                        decrypted_value = k8s_utils.platform_decrypt(
                            field_value, 
                            decrypt_guid, 
                            CONF.platform_encrypt_seed
                        )
                        item[field] = decrypted_value
                        LOG.info('Successfully decrypted incoming field %s for cluster %s', 
                                field, item.get('name'))
                    except Exception as e:
                        LOG.error('Failed to decrypt incoming field %s for cluster %s: %s', 
                                 field, item.get('name'), str(e))
                        # 如果解密失败，尝试当作明文处理
                        # 或者可以选择抛出异常
                        LOG.warning('Will treat field %s as plaintext', field)
        
        return item

    def validate_item_apply(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.cluster_rules, item, 'check')
        self.set_item_default(clean_item)
        # 在验证后、保存前解密客户端传入的加密字段
        clean_item = self.decrypt_incoming_fields(clean_item)
        return clean_item

    def validate_item_destroy(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.cluster_destroy_rules, item, 'check')
        return clean_item

    def apply(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Cluster().apply(item)

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Cluster().remove(item)


class Deployment(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.deployment'

    def set_item_default(self, item):
        defaults = {'namespace': 'default', 'replicas': '1', 'affinity': 'anti-host-preferred'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value
    
    def validate_log_path(self, item):
        """
        校验 log_path 参数
        如果 log_path 为空字符串或只包含空白字符，则移除该字段（使用默认值）
        如果 log_path 有值但不以 / 开头，则抛出验证错误
        """
        if 'log_path' in item:
            log_path = item['log_path']
            if log_path is None or (isinstance(log_path, str) and log_path.strip() == ''):
                # 空值，移除该字段，将使用默认值 /logs
                del item['log_path']
                LOG.info('[Deployment] log_path is empty, will use default /logs for %s', item.get('name'))
            elif not log_path.startswith('/'):
                # 非空值但格式不正确
                raise exceptions.ValidationError(
                    attribute='log_path',
                    msg=_('log_path must be an absolute path starting with /, got: %(path)s') % {'path': log_path}
                )

    def validate_item_apply(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.deployment_rules, item, 'check')
        self.set_item_default(clean_item)
        self.validate_log_path(clean_item)
        return clean_item

    def validate_item_destroy(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.destroy_rules, item, 'check')
        if not clean_item.get('namespace'):
            clean_item['namespace'] = 'default'
        return clean_item

    def apply(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Deployment().apply(item)

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Deployment().remove(item)


class StatefulSet(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.statefulset'

    def set_item_default(self, item):
        defaults = {'namespace': 'default', 'replicas': '1', 'affinity': 'anti-host-preferred'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value
        # StatefulSet 默认 serviceName 为资源名称
        if not item.get('serviceName'):
            item['serviceName'] = item.get('name', '')
    
    def _query_block_storage_from_cmdb(self, guid):
        """
        从 CMDB 查询 block_storage CI 的详细信息
        
        Args:
            guid: block_storage 的 GUID
            
        Returns:
            dict: 包含 name, accessModes, storageClassName, storage 的字典，失败时返回 None
        """
        try:
            from wecubek8s.common import wecmdb
            cmdb_server = CONF.wecube.base_url
            if not cmdb_server:
                LOG.warning('CMDB base_url not configured, cannot query block_storage')
                return None
            
            # 获取 CMDB 客户端
            cmdb_client = wecmdb.EntityClient(cmdb_server)
            
            # 通过 GUID 查询 block_storage
            query_data = {
                "criteria": {
                    "attrName": "guid",
                    "op": "eq",
                    "condition": guid
                }
            }
            
            LOG.info('Querying pvc from CMDB with guid: %s', guid)
            response = cmdb_client.query('wecmdb', 'pvc', query_data)
            
            if response and response.get('data') and len(response['data']) > 0:
                pvc_data = response['data'][0]
                # 从 CMDB 获取存储容量，默认单位为 Gi
                storage_amount = pvc_data.get('storage_amount', '10')
                # 如果 storage_amount 是纯数字字符串，添加 Gi 单位
                if storage_amount and not any(unit in storage_amount for unit in ['Gi', 'Mi', 'Ti', 'G', 'M', 'T']):
                    storage_amount = f'{storage_amount}Gi'
                
                result = {
                    'name': pvc_data.get('key_name', 'data'),
                    'accessModes': pvc_data.get('access_mode', 'ReadWriteOnce'),
                    'storageClassName': pvc_data.get('storage_class', 'standard'),
                    'storage': storage_amount
                }
                LOG.info('Found pvc: name=%s, accessModes=%s, storageClassName=%s, storage=%s',
                        result['name'], result['accessModes'], result['storageClassName'], result['storage'])
                return result
            else:
                LOG.warning('No pvc found in CMDB for guid: %s', guid)
                return None
        except Exception as e:
            LOG.error('Failed to query block_storage from CMDB for guid %s: %s', guid, str(e), exc_info=True)
            return None
    
    def parse_and_build_volume_claim_templates(self, item):
        """
        解析 block_storage 和 mount_path 参数，构建 volumeClaimTemplates
        
        Args:
            item: 请求数据字典
            
        处理逻辑：
        1. 从 item 中获取 block_storage 和 mount_path 参数
        2. 解析逗号分隔的字符串
        3. 验证两个列表长度是否一致
        4. 对每个 block_storage GUID 查询 CMDB 获取配置信息
        5. 构建 volumeClaimTemplates 和 volumes 配置
        """
        block_storage_str = item.get('block_storage', '').strip()
        mount_path_str = item.get('mount_path', '').strip()
        
        # 如果两个参数都为空，不处理
        if not block_storage_str and not mount_path_str:
            LOG.info('No block_storage or mount_path provided, skipping volume claim template generation')
            return
        
        # 如果只提供了其中一个参数，抛出错误
        if not block_storage_str or not mount_path_str:
            raise exceptions.ValidationError(
                attribute='block_storage/mount_path',
                msg=_('block_storage and mount_path must be provided together')
            )
        
        # 解析逗号分隔的字符串
        block_storage_guids = [guid.strip() for guid in block_storage_str.split(',') if guid.strip()]
        mount_paths = [path.strip() for path in mount_path_str.split(',') if path.strip()]
        
        LOG.info('Parsed block_storage guids: %s', block_storage_guids)
        LOG.info('Parsed mount_paths: %s', mount_paths)
        
        # 验证数量是否匹配
        if len(block_storage_guids) != len(mount_paths):
            raise exceptions.ValidationError(
                attribute='block_storage/mount_path',
                msg=_('block_storage and mount_path count mismatch: %(bs_count)d vs %(mp_count)d') % {
                    'bs_count': len(block_storage_guids),
                    'mp_count': len(mount_paths)
                }
            )
        
        # 验证 mount_path 格式（必须是绝对路径）
        for mount_path in mount_paths:
            if not mount_path.startswith('/'):
                raise exceptions.ValidationError(
                    attribute='mount_path',
                    msg=_('mount_path must be an absolute path starting with /, got: %(path)s') % {'path': mount_path}
                )
        
        # 查询 CMDB 并构建 volumeClaimTemplates
        volume_claim_templates = []
        volumes = []
        
        for idx, (guid, mount_path) in enumerate(zip(block_storage_guids, mount_paths)):
            LOG.info('Processing block_storage [%d/%d]: guid=%s, mount_path=%s', 
                    idx + 1, len(block_storage_guids), guid, mount_path)
            
            # 从 CMDB 查询 block_storage 信息
            block_storage_info = self._query_block_storage_from_cmdb(guid)
            
            if not block_storage_info:
                # 查询失败，使用默认值并记录警告
                LOG.warning('Failed to query block_storage info for guid %s, using default values', guid)
                block_storage_info = {
                    'name': f'data-{idx}',
                    'accessModes': 'ReadWriteOnce',
                    'storageClassName': 'standard',
                    'storage': '10Gi'
                }
            
            # 确保 accessModes 是数组格式
            access_modes = block_storage_info['accessModes']
            if isinstance(access_modes, str):
                # 如果是字符串，转换为数组
                access_modes = [access_modes]
            elif not isinstance(access_modes, list):
                LOG.warning('Invalid accessModes type: %s, using default [ReadWriteOnce]', type(access_modes))
                access_modes = ['ReadWriteOnce']
            
            # 构建 volumeClaimTemplate
            volume_name = block_storage_info['name']
            volume_claim_template = {
                'metadata': {
                    'name': volume_name
                },
                'spec': {
                    'accessModes': access_modes,
                    'storageClassName': block_storage_info['storageClassName'],
                    'resources': {
                        'requests': {
                            'storage': block_storage_info['storage']
                        }
                    }
                }
            }
            
            volume_claim_templates.append(volume_claim_template)
            
            # 构建 volume mount 配置（用于 Pod 容器挂载）
            volume_mount = {
                'name': volume_name,
                'mountPath': mount_path
            }
            volumes.append(volume_mount)
            
            LOG.info('Created volumeClaimTemplate: name=%s, accessModes=%s, storageClass=%s, storage=%s, mountPath=%s',
                    volume_name, access_modes, block_storage_info['storageClassName'], 
                    block_storage_info['storage'], mount_path)
        
        # 将生成的配置保存到 item 中
        item['volumeClaimTemplates'] = volume_claim_templates
        
        # 将 volumes 合并到现有的 volumes 配置中
        # 注意：这里的 volumes 是 volumeMount 配置，需要添加到容器的 volumeMounts 中
        if 'volumes' not in item:
            item['volumes'] = []
        
        # 添加持久卷挂载到 volumes 列表
        item['volumes'].extend(volumes)
        
        LOG.info('Successfully built %d volumeClaimTemplates and %d volume mounts',
                len(volume_claim_templates), len(volumes))
    
    def validate_log_path(self, item):
        """
        校验 log_path 参数
        如果 log_path 为空字符串或只包含空白字符，则移除该字段（使用默认值）
        如果 log_path 有值但不以 / 开头，则抛出验证错误
        """
        if 'log_path' in item:
            log_path = item['log_path']
            if log_path is None or (isinstance(log_path, str) and log_path.strip() == ''):
                # 空值，移除该字段，将使用默认值 /logs
                del item['log_path']
                LOG.info('[StatefulSet] log_path is empty, will use default /logs for %s', item.get('name'))
            elif not log_path.startswith('/'):
                # 非空值但格式不正确
                raise exceptions.ValidationError(
                    attribute='log_path',
                    msg=_('log_path must be an absolute path starting with /, got: %(path)s') % {'path': log_path}
                )

    def parse_envs_if_string(self, item):
        """
        解析 envs 参数，如果是字符串则转换为数组
        支持的格式：
        1. "[{name: 'sdf', value: 'we'}, {name: '44', value: '66'}]" (类Python字面量数组)
        2. '[{"name": "sdf", "value": "we"}, {"name": "44", "value": "66"}]' (标准JSON数组)
        3. "{key1: 'value1', key2: 'value2'}" (字典格式，会转换为数组)
        4. '{"key1": "value1", "key2": "value2"}' (标准JSON字典，会转换为数组)
        """
        if 'envs' not in item or item['envs'] is None:
            return
        
        envs = item['envs']
        
        # 如果已经是列表，直接返回
        if isinstance(envs, list):
            return
        
        # 如果是字符串，尝试解析
        if isinstance(envs, str):
            envs = envs.strip()
            if not envs:
                item['envs'] = []
                return
            
            # 尝试多种解析方式
            parse_error = None
            
            # 方法1: 尝试标准 JSON 解析
            try:
                parsed_envs = json.loads(envs)
                if isinstance(parsed_envs, list):
                    item['envs'] = parsed_envs
                    LOG.info('[StatefulSet] Successfully parsed envs using json.loads (array) for %s', 
                             item.get('name'))
                    return
                elif isinstance(parsed_envs, dict):
                    # 将字典转换为数组格式 [{name: key, value: value}, ...]
                    item['envs'] = [{'name': k, 'value': v} for k, v in parsed_envs.items()]
                    LOG.info('[StatefulSet] Successfully parsed envs using json.loads (dict) for %s', 
                             item.get('name'))
                    return
                else:
                    raise exceptions.ValidationError(
                        attribute='envs',
                        msg=_('envs must be an array or dict, got: %(type)s') % {'type': type(parsed_envs).__name__}
                    )
            except (json.JSONDecodeError, ValueError) as e:
                parse_error = str(e)
                LOG.debug('[StatefulSet] json.loads failed for envs: %s', parse_error)
            
            # 方法2: 尝试 Python 字面量解析 (支持单引号和无引号的key)
            try:
                parsed_envs = ast.literal_eval(envs)
                if isinstance(parsed_envs, list):
                    item['envs'] = parsed_envs
                    LOG.info('[StatefulSet] Successfully parsed envs using ast.literal_eval (array) for %s', 
                             item.get('name'))
                    return
                elif isinstance(parsed_envs, dict):
                    # 将字典转换为数组格式 [{name: key, value: value}, ...]
                    item['envs'] = [{'name': k, 'value': v} for k, v in parsed_envs.items()]
                    LOG.info('[StatefulSet] Successfully parsed envs using ast.literal_eval (dict) for %s', 
                             item.get('name'))
                    return
                else:
                    raise exceptions.ValidationError(
                        attribute='envs',
                        msg=_('envs must be an array or dict, got: %(type)s') % {'type': type(parsed_envs).__name__}
                    )
            except (SyntaxError, ValueError) as e:
                LOG.debug('[StatefulSet] ast.literal_eval failed for envs: %s', str(e))
            
            # 如果两种方法都失败，抛出错误
            raise exceptions.ValidationError(
                attribute='envs',
                msg=_('Failed to parse envs string. Expected array format like "[{name: \'key\', value: \'val\'}]" or dict format like "{key: \'value\'}". Original error: %(error)s') % {'error': parse_error}
            )
        else:
            # 如果既不是字符串也不是列表，抛出错误
            raise exceptions.ValidationError(
                attribute='envs',
                msg=_('envs must be a string or array, got: %(type)s') % {'type': type(envs).__name__}
            )

    def add_default_envs(self, item):
        """
        为 envs 添加默认的环境变量
        如果 envs 中不存在 CONTAINER 和 DOCKER，则添加默认值
        """
        # 确保 envs 是列表格式
        if 'envs' not in item or item['envs'] is None:
            item['envs'] = []
        
        envs = item['envs']
        
        # 如果不是列表，不处理（应该在 parse_envs_if_string 中已经处理过了）
        if not isinstance(envs, list):
            return
        
        # 获取已存在的环境变量名称
        existing_env_names = {env.get('name') for env in envs if isinstance(env, dict) and 'name' in env}
        
        # 添加默认环境变量（如果不存在）
        default_envs = [
            {'name': 'CONTAINER', 'value': 'true'},
            {'name': 'DOCKER', 'value': 'true'}
        ]
        
        for default_env in default_envs:
            if default_env['name'] not in existing_env_names:
                envs.append(default_env)
                LOG.info('[StatefulSet] Added default env: %s=%s for %s', 
                         default_env['name'], default_env['value'], item.get('name'))

    def validate_item_apply(self, item_index, item):
        # 先解析 envs 字符串（如果需要）
        self.parse_envs_if_string(item)
        
        # 添加默认环境变量
        self.add_default_envs(item)
        
        # 解析并构建 volumeClaimTemplates（基于 block_storage 和 mount_path）
        self.parse_and_build_volume_claim_templates(item)
        
        clean_item = crud.ColumnValidator.get_clean_data(rules.deployment_rules, item, 'check')
        self.set_item_default(clean_item)
        self.validate_log_path(clean_item)
        return clean_item

    def validate_item_destroy(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.destroy_rules, item, 'check')
        if not clean_item.get('namespace'):
            clean_item['namespace'] = 'default'
        return clean_item

    def apply(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.StatefulSet().apply(item)

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.StatefulSet().remove(item)


class DaemonSet(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.daemonset'

    def set_item_default(self, item):
        defaults = {'namespace': 'default'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item_apply(self, item_index, item):
        LOG.info('[DaemonSet-Controller] validate_item_apply started for item_index=%s, name=%s', 
                 item_index, item.get('name'))
        LOG.debug('[DaemonSet-Controller] Raw item data: %s', item)
        
        try:
            clean_item = crud.ColumnValidator.get_clean_data(rules.daemonset_rules, item, 'check')
            LOG.info('[DaemonSet-Controller] Validation passed for %s', item.get('name'))
            
            self.set_item_default(clean_item)
            LOG.info('[DaemonSet-Controller] Defaults set: namespace=%s', clean_item.get('namespace'))
            
            LOG.debug('[DaemonSet-Controller] Clean item data: %s', clean_item)
            return clean_item
        except Exception as e:
            LOG.error('[DaemonSet-Controller] Validation failed for item_index=%s: %s', 
                     item_index, str(e), exc_info=True)
            raise

    def validate_item_destroy(self, item_index, item):
        LOG.info('[DaemonSet-Controller] validate_item_destroy started for item_index=%s, name=%s', 
                 item_index, item.get('name'))
        
        clean_item = crud.ColumnValidator.get_clean_data(rules.destroy_rules, item, 'check')
        if not clean_item.get('namespace'):
            clean_item['namespace'] = 'default'
        
        LOG.info('[DaemonSet-Controller] Destroy validation passed for %s', item.get('name'))
        return clean_item

    def apply(self, reqid, operator, item_index, item, **kwargs):
        LOG.info('[DaemonSet-Controller] apply started - reqid=%s, operator=%s, item_index=%s, name=%s', 
                 reqid, operator, item_index, item.get('name'))
        LOG.debug('[DaemonSet-Controller] Full item data: %s', item)
        
        try:
            result = plugin_api.DaemonSet().apply(item)
            LOG.info('[DaemonSet-Controller] apply completed successfully for %s, result=%s', 
                     item.get('name'), result)
            return result
        except Exception as e:
            LOG.error('[DaemonSet-Controller] apply failed for %s: %s', 
                     item.get('name'), str(e), exc_info=True)
            raise

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        LOG.info('[DaemonSet-Controller] destroy started - reqid=%s, operator=%s, item_index=%s, name=%s', 
                 reqid, operator, item_index, item.get('name'))
        
        try:
            result = plugin_api.DaemonSet().remove(item)
            LOG.info('[DaemonSet-Controller] destroy completed successfully for %s', item.get('name'))
            return result
        except Exception as e:
            LOG.error('[DaemonSet-Controller] destroy failed for %s: %s', 
                     item.get('name'), str(e), exc_info=True)
            raise


class Service(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.service'

    def set_item_default(self, item):
        defaults = {'namespace': 'default', 'type': 'ClusterIP', 'sessionAffinity': None}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def set_instance_default(self, item):
        defaults = {'protocol': 'TCP'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item_apply(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.service_rules, item, 'check')
        self.set_item_default(clean_item)
        for idx, instance in enumerate(clean_item['instances']):
            clean_instance = crud.ColumnValidator.get_clean_data(rules.service_instances_rules, instance, 'check')
            self.set_instance_default(clean_instance)
            clean_item['instances'][idx] = clean_instance
        return clean_item

    def validate_item_destroy(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.destroy_rules, item, 'check')
        if not clean_item.get('namespace'):
            clean_item['namespace'] = 'default'
        return clean_item

    def apply(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Service().apply(item)

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Service().remove(item)


class Node(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.node'

    def validate_item_label(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.node_label_rules, item, 'check')
        return clean_item

    def label(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Node().label(item)
    
    def validate_item_remove_label(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.node_remove_label_rules, item, 'check')
        return clean_item
    
    def remove_label(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Node().remove_label(item)


class ClusterInterconnect(controller.Plugin):
    allow_methods = ('POST',)
    name = 'k8s.plugin.interconnect'

    def validate_item_create_external_service(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.interconnect_external_service_rules, item, 'check')
        return clean_item

    def validate_item_create_network_policy(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.interconnect_network_policy_rules, item, 'check')
        return clean_item

    def validate_item_setup_interconnect(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.interconnect_setup_rules, item, 'check')
        return clean_item

    def create_external_service(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.ClusterInterconnect().create_external_service(item)

    def create_network_policy(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.ClusterInterconnect().create_network_policy(item)

    def setup_interconnect(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.ClusterInterconnect().setup_interconnect(item)