# coding=utf-8
# coding=utf-8

from __future__ import absolute_import


class Tag:
    NODE_ID_TAG = 'wecube-node-correlation-id'
    POD_AUTO_TAG = 'wecube-pod-auto-tag'
    POD_AFFINITY_TAG = 'wecube-pod-affinity-tag'
    DEPLOYMENT_ID_TAG = 'wecube-deployment-correlation-id'
    STATEFULSET_ID_TAG = 'wecube-statefulset-correlation-id'
    SERVICE_ID_TAG = 'wecube-service-correlation-id'
    POD_ID_TAG = 'wecube-pod-correlation-id'


class Registry:
    """镜像仓库相关常量"""
    # initContainer 镜像名称（不含仓库地址）
    INIT_CONTAINER_IMAGE = 'package-init-container:1.0.0'
    # 默认私有仓库地址
    DEFAULT_PRIVATE_REGISTRY = '***REMOVED***'