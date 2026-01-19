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

    def validate_item_apply(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.deployment_rules, item, 'check')
        self.set_item_default(clean_item)
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

    def validate_item_apply(self, item_index, item):
        # 先解析 envs 字符串（如果需要）
        self.parse_envs_if_string(item)
        
        clean_item = crud.ColumnValidator.get_clean_data(rules.deployment_rules, item, 'check')
        self.set_item_default(clean_item)
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