# coding=utf-8

from __future__ import absolute_import

from talos.db import crud
from talos.db import converter
from wecubek8s.db import validator

tag_item_rules = [
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    crud.ColumnValidator(field='value', rule=validator.TypeValidator(str), validate_on=['check:M'], nullable=False),
]

# env = name, value, valueFrom
#   valueFrom in [configMapKeyRef, fieldRef, resourceFieldRef, secretKeyRef]
#     * configMapKeyRef = name,key
#     * secretKeyRef = name,key
#     * fieldRef = fieldPath
#     [unsupported]resourceFieldRef = containerName, resource, divisor
env_item_rules = [
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    crud.ColumnValidator(field='value', rule=validator.TypeValidator(str), validate_on=['check:M'], nullable=False),
    crud.ColumnValidator(field='valueFrom',
                         rule=validator.InValidator(['value', 'configMap', 'secretKey', 'fieldRef']),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='valueRef',
                         rule=validator.MappingValidator(crud.ColumnValidator.get_clean_data, tag_item_rules, 'check'),
                         validate_on=['check:M'],
                         nullable=True),
]

# volume = name, mountPath, readOnly, type,
#   type in [configMap, hostPath, emptyDir, secret, nfs]
#           [cephfs, cinder, csi, fc, glusterfs, iscsi, persistentVolumeClaim, rbd, vsphereVolume]
#           see https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.20/#volume-v1-core for more
volume_item_rules = [
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    crud.ColumnValidator(field='mountPath',
                         rule=validator.LengthValidator(1, 1024),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='readOnly',
                         validate_on=['check:O'],
                         nullable=False,
                         converter=converter.BooleanConverter()),
    crud.ColumnValidator(field='type',
                         rule=validator.InValidator(
                             ['configMap', 'hostPath', 'emptyDir', 'secret', 'nfs', 'persistentVolumeClaim']),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='typeSpec', rule=validator.TypeValidator(dict), validate_on=['check:O'], nullable=True),
]

deployment_rules = [
    crud.ColumnValidator(field='cluster',
                         rule=validator.LengthValidator(1, 255),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='id', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    # default 'default'
    crud.ColumnValidator(field='namespace',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='images', rule=validator.TypeValidator(list), validate_on=['check:M'], nullable=False),
    # default no auth
    crud.ColumnValidator(field='image_pull_username',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='image_pull_password',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
    # tag: {name: xxx, value: xxxx}
    crud.ColumnValidator(field='tags',
                         rule=validator.IterableValidator(crud.ColumnValidator.get_clean_data, tag_item_rules, 'check'),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='replicas',
                         rule=validator.NumberValidator(int, range_min=0),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='ports', rule=validator.LengthValidator(0, 255), validate_on=['check:O'], nullable=True),
    crud.ColumnValidator(field='cpu',
                         rule=validator.RegexValidator(r'^((\d+\.\d+)|(\d+))m?$'),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='memory',
                         rule=validator.RegexValidator(r'^(\d+)(Ei|Pi|Ti|Gi|Mi|Ki|E|P|T|G|M|K)?$'),
                         validate_on=['check:O'],
                         nullable=True),
    # for stateful set, difference env & volume for each pod
    crud.ColumnValidator(field='pod_tags',
                         rule=validator.IterableValidator(crud.ColumnValidator.get_clean_data, tag_item_rules, 'check'),
                         validate_on=['check:M'],
                         nullable=True),
    crud.ColumnValidator(field='affinity',
                         rule=validator.InValidator(['anti-host-preferred', 'anti-host-required']),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='envs',
                         rule=validator.IterableValidator(crud.ColumnValidator.get_clean_data, env_item_rules, 'check'),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='volumes',
                         rule=validator.IterableValidator(crud.ColumnValidator.get_clean_data, volume_item_rules,
                                                          'check'),
                         validate_on=['check:O'],
                         nullable=True),
]

service_rules = [
    crud.ColumnValidator(field='cluster',
                         rule=validator.LengthValidator(1, 255),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='id', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    # default 'default'
    crud.ColumnValidator(field='namespace',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
    # default ClusterIP, other choices: NodePort/ClusterIP/LoadBalancer
    crud.ColumnValidator(field='type',
                         rule=validator.InValidator(['NodePort', 'ClusterIP', 'LoadBalancer']),
                         validate_on=['check:O'],
                         nullable=True),
    # when type=ClusterIP, user can assign ip to it, or not, None means Headless Service
    # so if you are using Round-Robin service, don't include clusterIP field
    crud.ColumnValidator(field='clusterIP',
                         rule=validator.LengthValidator(1, 255),
                         validate_on=['check:O'],
                         nullable=True),
    # empty as RoundRobin or ClientIP
    crud.ColumnValidator(field='sessionAffinity',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='tags',
                         rule=validator.IterableValidator(crud.ColumnValidator.get_clean_data, tag_item_rules, 'check'),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='selectors',
                         rule=validator.IterableValidator(crud.ColumnValidator.get_clean_data,
                                                          tag_item_rules,
                                                          'check',
                                                          length_min=1),
                         validate_on=['check:M'],
                         nullable=True),
    crud.ColumnValidator(field='instances', rule=validator.TypeValidator(list), validate_on=['check:M'],
                         nullable=False),
]

service_instances_rules = [
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(0, 255), validate_on=['check:O'], nullable=True),
    # TCP/UDP, default TCP
    crud.ColumnValidator(field='protocol',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
    crud.ColumnValidator(field='port', rule=validator.RegexValidator(r'^\d+$'), validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='targetPort',
                         rule=validator.RegexValidator(r'^\d+$'),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='nodePort',
                         rule=validator.RegexValidator(r'^\d*$'),
                         validate_on=['check:O'],
                         nullable=True),
]

remove_rules = [
    crud.ColumnValidator(field='cluster',
                         rule=validator.LengthValidator(1, 255),
                         validate_on=['check:M'],
                         nullable=False),
    crud.ColumnValidator(field='name', rule=validator.LengthValidator(1, 255), validate_on=['check:M'], nullable=False),
    # default 'default'
    crud.ColumnValidator(field='namespace',
                         rule=validator.LengthValidator(0, 255),
                         validate_on=['check:O'],
                         nullable=True),
]