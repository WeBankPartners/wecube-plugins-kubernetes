# coding=utf-8

from __future__ import absolute_import

from wecubek8s.apps.plugin import controller


def add_routes(api):
    api.add_route('/kubernetes/v1/clusters/apply', controller.Cluster(action='apply'))
    api.add_route('/kubernetes/v1/clusters/destroy', controller.Cluster(action='destroy'))

    api.add_route('/kubernetes/v1/deployments/apply', controller.Deployment(action='apply'))
    api.add_route('/kubernetes/v1/deployments/destroy', controller.Deployment(action='destroy'))
    
    api.add_route('/kubernetes/v1/statefulsets/apply', controller.StatefulSet(action='apply'))
    api.add_route('/kubernetes/v1/statefulsets/destroy', controller.StatefulSet(action='destroy'))
    api.add_route('/kubernetes/v1/statefulsets/sync_pods_to_cmdb', controller.StatefulSet(action='sync_pods_to_cmdb'))
    
    api.add_route('/kubernetes/v1/daemonsets/apply', controller.DaemonSet(action='apply'))
    api.add_route('/kubernetes/v1/daemonsets/destroy', controller.DaemonSet(action='destroy'))
    
    api.add_route('/kubernetes/v1/services/apply', controller.Service(action='apply'))
    api.add_route('/kubernetes/v1/services/destroy', controller.Service(action='destroy'))
    
    api.add_route('/kubernetes/v1/nodes/label', controller.Node(action='label'))
    api.add_route('/kubernetes/v1/nodes/remove_label', controller.Node(action='remove_label'))
    
    # 共享 PVC 接口（支持多 Pod 共用一个 PVC，accessMode 推荐 ReadWriteMany）
    api.add_route('/kubernetes/v1/pvcs/apply', controller.SharedPVC(action='apply'))
    api.add_route('/kubernetes/v1/pvcs/destroy', controller.SharedPVC(action='destroy'))

    # PVC 批量销毁接口（自动识别共享 PVC 和 volumeClaimTemplate PVC，按 statefulset_name + pvc_key_names 批量删除）
    api.add_route('/kubernetes/v1/pvcs/batch_destroy', controller.PvcBatchDestroy(action='destroy'))

    # 包部署接口（通过 K8s Job + init-container 镜像，将远程 tar.gz 包下载并解压到共享 PVC 的指定目录）
    api.add_route('/kubernetes/v1/packages/deploy', controller.PackageDeploy(action='apply'))

    # 跨集群互联接口
    api.add_route('/kubernetes/v1/interconnect/external_service',
                  controller.ClusterInterconnect(action='create_external_service'))
    api.add_route('/kubernetes/v1/interconnect/network_policy',
                  controller.ClusterInterconnect(action='create_network_policy'))
    api.add_route('/kubernetes/v1/interconnect/setup',
                  controller.ClusterInterconnect(action='setup_interconnect'))
