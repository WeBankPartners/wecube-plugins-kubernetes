# coding=utf-8

from __future__ import absolute_import

from talos.db import crud
from talos.core.i18n import _

from wecubek8s.common import controller
from wecubek8s.common import exceptions
from wecubek8s.apps.plugin import rules
from wecubek8s.apps.plugin import api as plugin_api


class Deployment(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.deployment'

    def set_item_default(self, item):
        defaults = {'namespace': 'default'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.deployment_rules, item, 'check')
        self.set_item_default(clean_item)
        for idx, instance in enumerate(clean_item['instances']):
            clean_instance = crud.ColumnValidator.get_clean_data(rules.deployment_instances_rules, instance, 'check')
            clean_item['instances'][idx] = clean_instance
        pre_instance = None
        for idx, instance in enumerate(clean_item['instances']):
            if pre_instance is None:
                pre_instance = instance
            else:
                # FIXME: test equal
                if pre_instance != instance:
                    raise exceptions.ValidationError(attribute='inputs.%d.instances.%d' % (item_index + 1, idx + 1),
                                                     msg='!= inputs.%d.instances.%d' % (item_index + 1, idx))
        return clean_item

    def process(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Deployment().apply(item)


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

    def validate_item(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(rules.service_rules, item, 'check')
        self.set_item_default(clean_item)
        for idx, instance in enumerate(clean_item['instances']):
            clean_instance = crud.ColumnValidator.get_clean_data(rules.service_instances_rules, instance, 'check')
            self.set_instance_default(clean_instance)
            clean_item['instances'][idx] = clean_instance
        return clean_item

    def process(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Service().apply(item)