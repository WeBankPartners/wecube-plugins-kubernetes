# coding=utf-8
# coding=utf-8

from __future__ import absolute_import

import os


class Tag:
    NODE_ID_TAG = 'wecube-node-correlation-id'
    POD_AUTO_TAG = 'wecube-pod-auto-tag'
    POD_AFFINITY_TAG = 'wecube-pod-affinity-tag'
    DEPLOYMENT_ID_TAG = 'wecube-deployment-correlation-id'
    STATEFULSET_ID_TAG = 'wecube-statefulset-correlation-id'
    DAEMONSET_ID_TAG = 'wecube-daemonset-correlation-id'
    SERVICE_ID_TAG = 'wecube-service-correlation-id'
    POD_ID_TAG = 'wecube-pod-correlation-id'
    PVC_ID_TAG = 'wecube-pvc-correlation-id'


class CmdbCI:
    """WeCMDB CI type names injected by Kubernetes plugin system parameters."""

    PVC = os.getenv('KUBERNETES_CMDB_PVC_CI_NAME', 'k8s_pvc').strip() or 'k8s_pvc'
    POD = os.getenv('KUBERNETES_CMDB_POD_CI_NAME', 'pod').strip() or 'pod'
    HOST_RESOURCE = (
        os.getenv('KUBERNETES_CMDB_HOST_RESOURCE_CI_NAME', 'host_resource_instance').strip()
        or 'host_resource_instance'
    )


class Registry:
    """镜像仓库相关常量"""
    # initContainer 镜像名称（不含仓库地址）
    # 1.0.0 版本支持从 MinIO/S3 和 HTTP/HTTPS 下载文件
    INIT_CONTAINER_IMAGE = 'package-init-container:1.0.0'
    # 默认私有仓库地址
    DEFAULT_PRIVATE_REGISTRY = '***REMOVED***'
