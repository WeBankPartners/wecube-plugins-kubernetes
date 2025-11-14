# coding=utf-8

from __future__ import absolute_import

from talos.db import crud
from talos.core.i18n import _

from wecubek8s.common import controller
from wecubek8s.common import exceptions
from wecubek8s.apps.plugin import rules
from wecubek8s.apps.plugin import api as plugin_api


class Cluster(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.cluster'

    def set_item_default(self, item):
        defaults = {}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item_apply(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.cluster_rules, item, 'check')
        self.set_item_default(clean_item)
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
        return plugin_api.StatefulSet().apply(item)

    def destroy(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.StatefulSet().remove(item)


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