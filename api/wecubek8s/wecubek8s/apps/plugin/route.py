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
    
    api.add_route('/kubernetes/v1/services/apply', controller.Service(action='apply'))
    api.add_route('/kubernetes/v1/services/destroy', controller.Service(action='destroy'))
    
    api.add_route('/kubernetes/v1/nodes/label', controller.Node(action='label'))
    api.add_route('/kubernetes/v1/nodes/remove_label', controller.Node(action='remove_label'))
    
    # 跨集群互联接口
    api.add_route('/kubernetes/v1/interconnect/external_service',
                  controller.ClusterInterconnect(action='create_external_service'))
    api.add_route('/kubernetes/v1/interconnect/network_policy',
                  controller.ClusterInterconnect(action='create_network_policy'))
    api.add_route('/kubernetes/v1/interconnect/setup',
                  controller.ClusterInterconnect(action='setup_interconnect'))
