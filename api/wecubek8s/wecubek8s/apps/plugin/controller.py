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
        LOG.info('=== [_query_block_storage_from_cmdb] Start querying CMDB for guid: %s ===', guid)
        try:
            from wecubek8s.common import wecmdb
            cmdb_server = CONF.wecube.base_url
            LOG.debug('CMDB server configured: %s', cmdb_server)
            
            if not cmdb_server:
                LOG.warning('CMDB base_url not configured, cannot query block_storage')
                return None
            
            # 获取 CMDB 客户端
            cmdb_client = wecmdb.EntityClient(cmdb_server)
            LOG.debug('Created CMDB client successfully')
            
            # 通过 GUID 查询 block_storage
            query_data = {
                "criteria": {
                    "attrName": "guid",
                    "op": "eq",
                    "condition": guid
                }
            }
            
            LOG.info('Querying pvc from CMDB with guid: %s, query_data: %s', guid, query_data)
            response = cmdb_client.query('wecmdb', 'pvc', query_data)
            LOG.debug('CMDB response received: %s', response)
            
            if response and response.get('data') and len(response['data']) > 0:
                pvc_data = response['data'][0]
                LOG.debug('PVC data from CMDB: %s', pvc_data)
                
                # 从 CMDB 获取存储容量，默认单位为 Gi
                storage_amount = pvc_data.get('storage_amount', '10')
                LOG.debug('Original storage_amount from CMDB: %s', storage_amount)
                
                # 如果 storage_amount 是纯数字字符串，添加 Gi 单位
                if storage_amount and not any(unit in storage_amount for unit in ['Gi', 'Mi', 'Ti', 'G', 'M', 'T']):
                    storage_amount = f'{storage_amount}Gi'
                    LOG.debug('Added Gi unit to storage_amount: %s', storage_amount)
                
                # 从 CMDB 获取 mount_path
                mount_path = pvc_data.get('mount_path', '')
                LOG.debug('mount_path from CMDB: %s', mount_path)
                
                if not mount_path:
                    LOG.warning('No mount_path found in CMDB for guid: %s', guid)
                
                result = {
                    'name': pvc_data.get('key_name', '').strip() or 'data',
                    'accessModes': pvc_data.get('access_mode', '').strip() or 'ReadWriteOnce',
                    'storageClassName': pvc_data.get('storage_class', '').strip() or 'standard',
                    'storage': storage_amount,
                    'mountPath': mount_path
                }
                LOG.info('✓ Successfully found pvc: name=%s, accessModes=%s, storageClassName=%s, storage=%s, mountPath=%s',
                        result['name'], result['accessModes'], result['storageClassName'], result['storage'], result['mountPath'])
                LOG.info('=== [_query_block_storage_from_cmdb] End successfully for guid: %s ===', guid)
                return result
            else:
                LOG.warning('✗ No pvc found in CMDB for guid: %s, response: %s', guid, response)
                LOG.info('=== [_query_block_storage_from_cmdb] End with no data for guid: %s ===', guid)
                return None
        except Exception as e:
            LOG.error('✗ Failed to query block_storage from CMDB for guid %s: %s', guid, str(e), exc_info=True)
            LOG.info('=== [_query_block_storage_from_cmdb] End with error for guid: %s ===', guid)
            return None
    
    def parse_and_build_volume_claim_templates(self, item):
        """
        解析 block_storage 参数，构建 volumeClaimTemplates
        
        Args:
            item: 请求数据字典
            
        处理逻辑：
        1. 从 item 中获取 block_storage 参数（数组或字符串数组格式）
        2. 解析为列表
        3. 对每个 block_storage GUID 查询 CMDB 获取配置信息（包括 mount_path）
        4. 构建 volumeClaimTemplates 和 volumes 配置
        """
        LOG.info('========================================')
        LOG.info('=== [parse_and_build_volume_claim_templates] Start ===')
        LOG.info('========================================')
        
        import ast
        
        block_storage_value = item.get('block_storage', '')
        LOG.debug('Raw block_storage parameter from item: "%s" (type: %s)', block_storage_value, type(block_storage_value))
        
        # 如果 block_storage 为空，不处理
        if not block_storage_value:
            LOG.info('No block_storage provided, skipping volume claim template generation')
            LOG.info('=== [parse_and_build_volume_claim_templates] End (no block_storage) ===')
            return
        
        # 处理 block_storage 参数（支持列表或字符串格式）
        try:
            # 如果已经是列表，直接使用（WeCube multiple="Y" 会传入列表）
            if isinstance(block_storage_value, list):
                LOG.info('block_storage is already a list: %s', block_storage_value)
                block_storage_guids = block_storage_value
            # 如果是字符串，尝试解析（向后兼容）
            elif isinstance(block_storage_value, str):
                block_storage_str = block_storage_value.strip()
                if not block_storage_str:
                    LOG.info('block_storage is empty string, skipping volume claim template generation')
                    LOG.info('=== [parse_and_build_volume_claim_templates] End (empty string) ===')
                    return
                
                LOG.info('Attempting to parse block_storage string: "%s"', block_storage_str)
                # 尝试将字符串解析为 Python 列表
                block_storage_guids = ast.literal_eval(block_storage_str)
                LOG.debug('Parsed result: %s (type: %s)', block_storage_guids, type(block_storage_guids))
            else:
                LOG.error('block_storage must be a list or string, but got: %s', type(block_storage_value).__name__)
                raise ValueError(f'block_storage must be a list or string, got: {type(block_storage_value).__name__}')
            
            # 确保解析结果是列表
            if not isinstance(block_storage_guids, list):
                LOG.error('block_storage must be a list, but got: %s', type(block_storage_guids).__name__)
                raise ValueError(f'block_storage must be a list, got: {type(block_storage_guids).__name__}')
            
            LOG.debug('Before filtering: %d items: %s', len(block_storage_guids), block_storage_guids)
            
            # 过滤空字符串并去除空白（确保每个元素都是字符串）
            block_storage_guids = [str(guid).strip() for guid in block_storage_guids if guid and str(guid).strip()]
            LOG.debug('After filtering: %d items: %s', len(block_storage_guids), block_storage_guids)
            
            if not block_storage_guids:
                LOG.info('block_storage is empty list after filtering, skipping volume claim template generation')
                LOG.info('=== [parse_and_build_volume_claim_templates] End (empty after filtering) ===')
                return
                
        except (ValueError, SyntaxError) as e:
            LOG.error('Failed to parse block_storage: %s, error: %s', block_storage_value, str(e), exc_info=True)
            raise exceptions.ValidationError(
                attribute='block_storage',
                msg=_('block_storage must be a list or valid string array format like "[\'guid1\', \'guid2\']", error: %(error)s') % {'error': str(e)}
            )
        
        LOG.info('✓ Successfully parsed %d block_storage guids: %s', len(block_storage_guids), block_storage_guids)
        
        # 查询 CMDB 并构建 volumeClaimTemplates
        LOG.info('----------------------------------------')
        LOG.info('Starting CMDB queries and volume template building...')
        LOG.info('----------------------------------------')
        
        volume_claim_templates = []
        volumes = []
        
        for idx, guid in enumerate(block_storage_guids):
            LOG.info('>>> Processing block_storage [%d/%d]: guid=%s', 
                    idx + 1, len(block_storage_guids), guid)
            
            # 从 CMDB 查询 block_storage 信息（包括 mount_path）
            LOG.debug('Calling _query_block_storage_from_cmdb for guid: %s', guid)
            block_storage_info = self._query_block_storage_from_cmdb(guid)
            
            if not block_storage_info:
                # 查询失败，抛出错误（因为 mount_path 必须从 CMDB 获取）
                LOG.error('✗ Failed to query block_storage info from CMDB for guid: %s', guid)
                raise exceptions.PluginError(
                    message=_('Failed to query block_storage info from CMDB for guid: %(guid)s. Cannot proceed without mount_path.') % {'guid': guid}
                )
            
            LOG.debug('block_storage_info retrieved: %s', block_storage_info)
            
            # 从 CMDB 查询结果中获取 mount_path
            mount_path = block_storage_info.get('mountPath', '')
            LOG.debug('Extracted mount_path: "%s" for guid: %s', mount_path, guid)
            
            if not mount_path:
                LOG.error('✗ mount_path not found in CMDB for block_storage guid: %s', guid)
                raise exceptions.ValidationError(
                    attribute='mount_path',
                    msg=_('mount_path not found in CMDB for block_storage guid: %(guid)s') % {'guid': guid}
                )
            
            # 验证 mount_path 格式（必须是绝对路径）
            if not mount_path.startswith('/'):
                LOG.error('✗ mount_path must be absolute path, got: "%s" for guid: %s', mount_path, guid)
                raise exceptions.ValidationError(
                    attribute='mount_path',
                    msg=_('mount_path from CMDB must be an absolute path starting with /, got: %(path)s for guid: %(guid)s') % {
                        'path': mount_path,
                        'guid': guid
                    }
                )
            
            LOG.debug('✓ mount_path validation passed: "%s"', mount_path)
            
            # 确保 accessModes 是数组格式
            access_modes = block_storage_info['accessModes']
            LOG.debug('Original accessModes: %s (type: %s)', access_modes, type(access_modes))
            
            if isinstance(access_modes, str):
                # 如果是字符串，转换为数组
                access_modes = [access_modes]
                LOG.debug('Converted string accessModes to list: %s', access_modes)
            elif not isinstance(access_modes, list):
                LOG.warning('Invalid accessModes type: %s, using default [ReadWriteOnce]', type(access_modes))
                access_modes = ['ReadWriteOnce']
            
            # 构建 volumeClaimTemplate
            volume_name = block_storage_info['name']
            LOG.debug('Building volumeClaimTemplate with volume_name: %s', volume_name)
            
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
            LOG.debug('volumeClaimTemplate created: %s', volume_claim_template)
            
            volume_claim_templates.append(volume_claim_template)
            LOG.debug('Appended to volume_claim_templates list (current count: %d)', len(volume_claim_templates))
            
            # 构建 volume mount 配置（用于 Pod 容器挂载）
            # 注意：对于 StatefulSet + volumeClaimTemplates：
            # - volumeClaimTemplate 会自动创建 PVC 并使其对 Pod 可用
            # - 我们只需要提供容器的 volumeMount 配置（name + mountPath）
            # - 不需要在 Pod 的 volumes 中显式引用 PVC（这会导致 PVC not found 错误）
            volume_mount = {
                'name': volume_name,
                'mountPath': mount_path
            }
            LOG.debug('volumeMount created: %s', volume_mount)
            
            volumes.append(volume_mount)
            LOG.debug('Appended to volumes list (current count: %d)', len(volumes))
            
            LOG.info('✓ [%d/%d] Created volumeClaimTemplate: name=%s, accessModes=%s, storageClass=%s, storage=%s, mountPath=%s',
                    idx + 1, len(block_storage_guids),
                    volume_name, access_modes, block_storage_info['storageClassName'], 
                    block_storage_info['storage'], mount_path)
        
        # 将生成的配置保存到 item 中
        LOG.info('----------------------------------------')
        LOG.info('Saving results to item dictionary...')
        LOG.info('----------------------------------------')
        
        LOG.debug('Setting item["volumeClaimTemplates"] with %d templates', len(volume_claim_templates))
        item['volumeClaimTemplates'] = volume_claim_templates
        LOG.debug('item["volumeClaimTemplates"] = %s', volume_claim_templates)
        
        # 将 volumeClaimTemplate 的挂载信息保存到单独的字段
        # 注意：对于 StatefulSet，volumeClaimTemplates 会自动创建 PVC 并使其对 Pod 可用
        # 我们不应该在 Pod 的 volumes 中引用这些 PVC（会导致 "PVC not found" 错误）
        # 而是应该将挂载信息单独保存，在 api.py 中直接添加到容器的 volumeMounts
        LOG.debug('Setting item["volumeClaimMounts"] with %d mounts', len(volumes))
        item['volumeClaimMounts'] = volumes
        LOG.debug('item["volumeClaimMounts"] = %s', volumes)
        
        LOG.info('========================================')
        LOG.info('✓ Successfully built %d volumeClaimTemplates and %d volumeClaimMounts',
                len(volume_claim_templates), len(volumes))
        LOG.info('✓ volumeClaimTemplates will be used by StatefulSet to auto-create PVCs')
        LOG.info('✓ volumeClaimMounts will be added to container volumeMounts (NOT to Pod volumes)')
        LOG.info('=== [parse_and_build_volume_claim_templates] End successfully ===')
        LOG.info('========================================')
    
    def parse_and_build_shared_pvc_volumes(self, item):
        """
        解析 shared_block_storage 参数，构建共享 PVC 的 Pod-level volumes 和容器挂载配置。

        与 block_storage/volumeClaimTemplates 的核心区别：
        - block_storage     → StatefulSet volumeClaimTemplates，每个 Pod 自动获得独立 PVC
        - shared_block_storage → 引用已存在的共享 PVC（claimName），所有 Pod 挂载同一个 PVC

        处理逻辑：
        1. 从 item 获取 shared_block_storage（GUID 数组）
        2. 对每个 GUID 查询 CMDB 获取 key_name（PVC 实际名称）和 mount_path
        3. 构建 Pod-level volumes（persistentVolumeClaim 引用）和容器 volumeMounts
        4. 结果保存到 item['sharedPvcVolumes'] 和 item['sharedPvcMounts']
        """
        LOG.info('=== [parse_and_build_shared_pvc_volumes] Start ===')

        import ast

        shared_storage_value = item.get('shared_block_storage', '')
        LOG.debug('Raw shared_block_storage from item: "%s" (type: %s)',
                  shared_storage_value, type(shared_storage_value))

        if not shared_storage_value:
            LOG.info('No shared_block_storage provided, skipping shared PVC volume building')
            LOG.info('=== [parse_and_build_shared_pvc_volumes] End (no shared_block_storage) ===')
            return

        # 解析 GUID 列表（支持 list 或字符串格式，与 block_storage 保持一致）
        try:
            if isinstance(shared_storage_value, list):
                LOG.info('shared_block_storage is already a list: %s', shared_storage_value)
                shared_guids = shared_storage_value
            elif isinstance(shared_storage_value, str):
                shared_str = shared_storage_value.strip()
                if not shared_str:
                    LOG.info('shared_block_storage is empty string, skipping')
                    LOG.info('=== [parse_and_build_shared_pvc_volumes] End (empty string) ===')
                    return
                LOG.info('Parsing shared_block_storage string: "%s"', shared_str)
                shared_guids = ast.literal_eval(shared_str)
            else:
                raise ValueError('shared_block_storage must be a list or string, got: %s' % type(shared_storage_value).__name__)

            if not isinstance(shared_guids, list):
                raise ValueError('shared_block_storage must be a list, got: %s' % type(shared_guids).__name__)

            shared_guids = [str(g).strip() for g in shared_guids if g and str(g).strip()]
            if not shared_guids:
                LOG.info('shared_block_storage is empty after filtering, skipping')
                LOG.info('=== [parse_and_build_shared_pvc_volumes] End (empty after filtering) ===')
                return

        except (ValueError, SyntaxError) as e:
            LOG.error('Failed to parse shared_block_storage: %s, error: %s',
                      shared_storage_value, str(e), exc_info=True)
            raise exceptions.ValidationError(
                attribute='shared_block_storage',
                msg=_('shared_block_storage must be a list or valid string array format, error: %(error)s') % {'error': str(e)}
            )

        LOG.info('✓ Parsed %d shared_block_storage guids: %s', len(shared_guids), shared_guids)

        shared_pvc_volumes = []  # Pod-level volumes（引用已有 PVC）
        shared_pvc_mounts = []   # 容器 volumeMounts

        for idx, guid in enumerate(shared_guids):
            LOG.info('>>> Processing shared_block_storage [%d/%d]: guid=%s',
                     idx + 1, len(shared_guids), guid)

            pvc_info = self._query_block_storage_from_cmdb(guid)
            if not pvc_info:
                LOG.error('✗ Failed to query shared PVC info from CMDB for guid: %s', guid)
                raise exceptions.PluginError(
                    message=_('Failed to query shared PVC info from CMDB for guid: %(guid)s. '
                               'Cannot proceed without PVC name and mount_path.') % {'guid': guid}
                )

            mount_path = pvc_info.get('mountPath', '')
            if not mount_path:
                LOG.error('✗ mount_path not found in CMDB for shared PVC guid: %s', guid)
                raise exceptions.ValidationError(
                    attribute='mount_path',
                    msg=_('mount_path not found in CMDB for shared_block_storage guid: %(guid)s') % {'guid': guid}
                )

            if not mount_path.startswith('/'):
                LOG.error('✗ mount_path must be absolute path, got: "%s" for guid: %s', mount_path, guid)
                raise exceptions.ValidationError(
                    attribute='mount_path',
                    msg=_('mount_path from CMDB must start with /, got: %(path)s for guid: %(guid)s') % {
                        'path': mount_path,
                        'guid': guid
                    }
                )

            # key_name 即 CMDB 中存储的 PVC 实际名称（对应 pvcs/apply 时传入的 name 经 escape_name 后的值）
            pvc_name = pvc_info.get('name', '').strip()
            if not pvc_name:
                LOG.error('✗ key_name(name) not found in CMDB for shared PVC guid: %s', guid)
                raise exceptions.ValidationError(
                    attribute='name',
                    msg=_('PVC name not found in CMDB for shared_block_storage guid: %(guid)s') % {'guid': guid}
                )

            # volume 名称需符合 K8s 规范，使用 escape_name 转义
            from wecubek8s.apps.plugin import utils as api_utils
            volume_name = api_utils.escape_name(pvc_name)

            # Pod-level volume：通过 claimName 引用已存在的共享 PVC
            shared_pvc_volumes.append({
                'name': volume_name,
                'persistentVolumeClaim': {
                    'claimName': volume_name,
                    'readOnly': False
                }
            })

            # 容器 volumeMount
            shared_pvc_mounts.append({
                'name': volume_name,
                'mountPath': mount_path
            })

            LOG.info('✓ [%d/%d] Built shared PVC volume: claimName=%s, mountPath=%s',
                     idx + 1, len(shared_guids), volume_name, mount_path)

        item['sharedPvcVolumes'] = shared_pvc_volumes
        item['sharedPvcMounts'] = shared_pvc_mounts

        LOG.info('✓ Built %d shared PVC volumes and %d mounts', len(shared_pvc_volumes), len(shared_pvc_mounts))
        LOG.info('=== [parse_and_build_shared_pvc_volumes] End successfully ===')

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
        
        # 解析并构建 volumeClaimTemplates（基于 block_storage，每个 Pod 独立 PVC）
        self.parse_and_build_volume_claim_templates(item)
        
        # 解析并构建共享 PVC 挂载（基于 shared_block_storage，所有 Pod 共用同一 PVC）
        self.parse_and_build_shared_pvc_volumes(item)
        
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


class SharedPVC(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.shared_pvc'

    def set_item_default(self, item):
        defaults = {'namespace': 'default'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def normalize_capacity(self, item):
        """
        将 capacity（单位 G，纯数字）转换为 K8s 规范格式（Gi）
        例如："10" -> "10Gi", "0.5" -> "0.5Gi"
        """
        capacity = item.get('capacity', '')
        if capacity and not any(unit in str(capacity) for unit in ['Gi', 'Mi', 'Ti', 'G', 'M', 'T']):
            item['capacity'] = '%sGi' % capacity
            LOG.info('[SharedPVC] Normalized capacity: %s -> %s', capacity, item['capacity'])
        else:
            LOG.debug('[SharedPVC] capacity already has unit or is empty, no normalization needed: %s', capacity)

    def validate_item_apply(self, item_index, item):
        LOG.info('[SharedPVC] validate_item_apply started - item_index=%s, name=%s, cluster=%s',
                 item_index, item.get('name'), item.get('cluster'))
        LOG.debug('[SharedPVC] Raw apply item data: %s', item)
        try:
            clean_item = crud.ColumnValidator.get_clean_data(rules.shared_pvc_rules, item, 'check')
            LOG.info('[SharedPVC] Field validation passed for name=%s', clean_item.get('name'))

            self.set_item_default(clean_item)
            LOG.debug('[SharedPVC] Defaults applied: namespace=%s', clean_item.get('namespace'))

            self.normalize_capacity(clean_item)
            LOG.info('[SharedPVC] validate_item_apply finished - name=%s, namespace=%s, capacity=%s, '
                     'accessMode=%s, storageClass=%s, instanceId=%s',
                     clean_item.get('name'), clean_item.get('namespace'), clean_item.get('capacity'),
                     clean_item.get('accessMode'), clean_item.get('storageClass'), clean_item.get('instanceId'))
            return clean_item
        except Exception as e:
            LOG.error('[SharedPVC] validate_item_apply failed - item_index=%s, name=%s, error=%s',
                      item_index, item.get('name'), str(e), exc_info=True)
            raise

    def validate_item_destroy(self, item_index, item):
        LOG.info('[SharedPVC] validate_item_destroy started - item_index=%s, name=%s, cluster=%s',
                 item_index, item.get('name'), item.get('cluster'))
        LOG.debug('[SharedPVC] Raw destroy item data: %s', item)
        try:
            clean_item = crud.ColumnValidator.get_clean_data(rules.shared_pvc_destroy_rules, item, 'check')
            if not clean_item.get('namespace'):
                clean_item['namespace'] = 'default'
            LOG.info('[SharedPVC] validate_item_destroy finished - name=%s, namespace=%s, cluster=%s',
                     clean_item.get('name'), clean_item.get('namespace'), clean_item.get('cluster'))
            return clean_item
        except Exception as e:
            LOG.error('[SharedPVC] validate_item_destroy failed - item_index=%s, name=%s, error=%s',
                      item_index, item.get('name'), str(e), exc_info=True)
            raise

    def apply(self, reqid, operator, item_index, item, **kwargs):
        LOG.info('[SharedPVC] apply called - reqid=%s, operator=%s, item_index=%s, name=%s, cluster=%s',
                 reqid, operator, item_index, item.get('name'), item.get('cluster'))
        try:
            result = plugin_api.SharedPVC().apply(item)
            LOG.info('[SharedPVC] apply succeeded - name=%s, status=%s', item.get('name'), result.get('status'))
            return result
        except Exception as e:
            LOG.error('[SharedPVC] apply failed - name=%s, cluster=%s, error=%s',
                      item.get('name'), item.get('cluster'), str(e), exc_info=True)
            raise

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        LOG.info('[SharedPVC] destroy called - reqid=%s, operator=%s, item_index=%s, name=%s, cluster=%s',
                 reqid, operator, item_index, item.get('name'), item.get('cluster'))
        try:
            result = plugin_api.SharedPVC().remove(item)
            LOG.info('[SharedPVC] destroy succeeded - name=%s', item.get('name'))
            return result
        except Exception as e:
            LOG.error('[SharedPVC] destroy failed - name=%s, cluster=%s, error=%s',
                      item.get('name'), item.get('cluster'), str(e), exc_info=True)
            raise


class PackageDeploy(controller.Plugin):
    """
    包部署接口：通过 K8s Job + busybox 镜像，将远程 tar.gz 包下载并解压到共享 PVC 的指定目录。
    """
    allow_methods = ('POST',)
    name = 'k8s.plugin.package_deploy'

    def set_item_default(self, item):
        defaults = {
            'namespace': 'default',
            'target_path': '/',
        }
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item_apply(self, item_index, item):
        LOG.info('[PackageDeploy] validate_item_apply started - item_index=%s, correlation_id=%s, cluster=%s',
                 item_index, item.get('correlation_id'), item.get('cluster'))
        try:
            clean_item = crud.ColumnValidator.get_clean_data(rules.package_deploy_rules, item, 'check')
            self.set_item_default(clean_item)
            LOG.info('[PackageDeploy] validate_item_apply finished - correlation_id=%s, namespace=%s, pvc_name=%s, '
                     'package_url=%s, target_path=%s',
                     clean_item.get('correlation_id'), clean_item.get('namespace'), clean_item.get('pvc_name'),
                     clean_item.get('package_url'), clean_item.get('target_path'))
            return clean_item
        except Exception as e:
            LOG.error('[PackageDeploy] validate_item_apply failed - item_index=%s, correlation_id=%s, error=%s',
                      item_index, item.get('correlation_id'), str(e), exc_info=True)
            raise

    def apply(self, reqid, operator, item_index, item, **kwargs):
        LOG.info('[PackageDeploy] apply called - reqid=%s, operator=%s, item_index=%s, '
                 'correlation_id=%s, cluster=%s',
                 reqid, operator, item_index, item.get('correlation_id'), item.get('cluster'))
        try:
            result = plugin_api.PackageDeploy().apply(item)
            LOG.info('[PackageDeploy] apply succeeded - job_name=%s, status=%s',
                     result.get('job_name'), result.get('status'))
            return result
        except Exception as e:
            LOG.error('[PackageDeploy] apply failed - correlation_id=%s, cluster=%s, error=%s',
                      item.get('correlation_id'), item.get('cluster'), str(e), exc_info=True)
            raise


class PvcBatchDestroy(controller.Plugin):
    """
    PVC 批量销毁接口：同时支持共享 PVC 和 volumeClaimTemplate PVC 的批量删除。
    """
    allow_methods = ('POST',)
    name = 'k8s.plugin.pvc_batch_destroy'

    def set_item_default(self, item):
        if not item.get('namespace'):
            item['namespace'] = 'default'

    def validate_item_destroy(self, item_index, item):
        LOG.info('[PvcBatchDestroy] validate_item_destroy started - item_index=%s, '
                 'cluster=%s, statefulset_name=%s, pvc_key_names=%s',
                 item_index, item.get('cluster'), item.get('statefulset_name'), item.get('pvc_key_names'))
        try:
            clean_item = crud.ColumnValidator.get_clean_data(rules.pvc_batch_destroy_rules, item, 'check')
            self.set_item_default(clean_item)

            # pvc_key_names 每项去空、去重
            raw_keys = clean_item.get('pvc_key_names') or []
            clean_keys = list(dict.fromkeys(k.strip() for k in raw_keys if k and k.strip()))
            if not clean_keys:
                raise exceptions.ValidationError(
                    attribute='pvc_key_names',
                    message='pvc_key_names must contain at least one non-empty key name'
                )
            clean_item['pvc_key_names'] = clean_keys

            LOG.info('[PvcBatchDestroy] validate_item_destroy finished - namespace=%s, '
                     'statefulset_name=%s, pvc_key_names=%s',
                     clean_item.get('namespace'), clean_item.get('statefulset_name'),
                     clean_item.get('pvc_key_names'))
            return clean_item
        except Exception as e:
            LOG.error('[PvcBatchDestroy] validate_item_destroy failed - item_index=%s, error=%s',
                      item_index, str(e), exc_info=True)
            raise

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        LOG.info('[PvcBatchDestroy] destroy called - reqid=%s, operator=%s, item_index=%s, '
                 'cluster=%s, statefulset_name=%s, pvc_key_names=%s',
                 reqid, operator, item_index,
                 item.get('cluster'), item.get('statefulset_name'), item.get('pvc_key_names'))
        try:
            result = plugin_api.PvcBatchDestroy().remove(item)
            LOG.info('[PvcBatchDestroy] destroy succeeded - deleted_count=%d, deleted_pvcs=%s',
                     result.get('deleted_count', 0), result.get('deleted_pvcs', ''))
            return result
        except Exception as e:
            LOG.error('[PvcBatchDestroy] destroy failed - cluster=%s, statefulset_name=%s, error=%s',
                      item.get('cluster'), item.get('statefulset_name'), str(e), exc_info=True)
            raise