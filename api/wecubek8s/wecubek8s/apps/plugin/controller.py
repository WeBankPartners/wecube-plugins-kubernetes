# coding=utf-8

from __future__ import absolute_import

import falcon
from talos.db import crud
from talos.db import validator as base_validator
from talos.core.i18n import _

from wecubek8s.common import controller
from wecubek8s.common import exceptions
from wecubek8s.db import validator
from wecubek8s.apps.plugin import api as plugin_api


class Deployment(controller.Plugin):
    allow_methods = ('POST', )
    name = 'k8s.plugin.deployment'
    _item_rules = [
        # default v1
        crud.ColumnValidator(field='apiVersion',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='clusterUrl',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='clusterToken',
                             rule=validator.LengthValidator(1, 2048),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='name',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:M'],
                             nullable=False),
        # default 'default'
        crud.ColumnValidator(field='namespace',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='images',
                             rule=validator.TypeValidator(list),
                             validate_on=['check:M'],
                             nullable=False),
        # default no auth
        crud.ColumnValidator(field='image_pull_username',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='image_pull_password',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        # tag: {name: xxx, value: xxxx}
        crud.ColumnValidator(field='tags', rule=validator.TypeValidator(list), validate_on=['check:O'], nullable=True),
        crud.ColumnValidator(field='instances',
                             rule=validator.TypeValidator(list),
                             validate_on=['check:M'],
                             nullable=False),
    ]

    _instances_rules = [
        crud.ColumnValidator(field='ports',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='cpu',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='memory',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        # for stateful set, difference env & volume for each pod
        crud.ColumnValidator(field='tags', rule=validator.TypeValidator(list), validate_on=['check:M'], nullable=False),
        crud.ColumnValidator(field='envs', rule=validator.TypeValidator(list), validate_on=['check:O'], nullable=True),
        crud.ColumnValidator(field='volumes',
                             rule=validator.TypeValidator(list),
                             validate_on=['check:O'],
                             nullable=True),
    ]

    def set_item_default(self, item):
        defaults = {'apiVersion': 'V1', 'namespace': 'default'}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(self._item_rules, item, 'check')
        self.set_item_default(clean_item)
        for idx, instance in enumerate(clean_item['instances']):
            clean_instance = crud.ColumnValidator.get_clean_data(self._instances_rules, instance, 'check')
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
    _item_rules = [
        # default v1
        crud.ColumnValidator(field='apiVersion',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='clusterUrl',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='clusterToken',
                             rule=validator.LengthValidator(1, 2048),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='name',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:M'],
                             nullable=False),
        # default 'default'
        crud.ColumnValidator(field='namespace',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        # default ClusterIP, other choices: nodePort/ClusterIP/LoadBalancer
        crud.ColumnValidator(field='type',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        # when type=ClusterIP, user can assign ip to it, or not, None means Headless Service
        # so if you are using Round-Robin service, don't include clusterIP field
        crud.ColumnValidator(field='clusterIP',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        # empty as RoundRobin or ClientIP
        crud.ColumnValidator(field='sessionAffinity',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='tags', rule=validator.TypeValidator(list), validate_on=['check:O'], nullable=True),
        crud.ColumnValidator(field='selectors',
                             rule=validator.TypeValidator(list),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='instances',
                             rule=validator.TypeValidator(list),
                             validate_on=['check:M'],
                             nullable=False),
    ]

    _instances_rules = [
        crud.ColumnValidator(field='name',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        # TCP/UDP, default TCP
        crud.ColumnValidator(field='protocol',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='port',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='targetPort',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:M'],
                             nullable=False),
        crud.ColumnValidator(field='nodePort',
                             rule=validator.LengthValidator(0, 255),
                             validate_on=['check:O'],
                             nullable=True),
    ]

    def set_item_default(self, item):
        defaults = {'apiVersion': 'V1', 'namespace': 'default', 'type': 'ClusterIP', 'sessionAffinity': None}
        for key, value in defaults.items():
            if not item.get(key):
                item[key] = value

    def validate_item(self, item_index, item):
        clean_item = crud.ColumnValidator.get_clean_data(self._item_rules, item, 'check')
        self.set_item_default(clean_item)
        for idx, instance in enumerate(clean_item['instances']):
            clean_instance = crud.ColumnValidator.get_clean_data(self._instances_rules, instance, 'check')
            clean_item['instances'][idx] = clean_instance
        return clean_item

    def process(self, reqid, operator, item_index, item, **kwargs):
        return plugin_api.Service().apply(item)