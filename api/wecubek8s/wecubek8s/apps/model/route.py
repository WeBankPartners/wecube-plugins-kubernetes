# coding=utf-8

from __future__ import absolute_import

from wecubek8s.apps.model import controller


def add_routes(api):
    '''
    model route required:
    query:
        POST /kubernetes/entities/cluster/query
            {"additionalFilters": []}
        GET /kubernetes/entities/cluster

        return {'data': [], 'message': '', 'status': 'OK'}
    
    create:
    update:
    delete:
    '''
    api.add_route('/kubernetes/entities/cluster/query', controller.PostQueryCluster())
    api.add_route('/kubernetes/entities/cluster', controller.GetQueryCluster())
    api.add_route('/kubernetes/entities/node/query', controller.PostQueryNode())
    api.add_route('/kubernetes/entities/node', controller.GetQueryNode())
    api.add_route('/kubernetes/entities/deployment/query', controller.PostQueryDeployment())
    api.add_route('/kubernetes/entities/deployment', controller.GetQueryDeployment())
    api.add_route('/kubernetes/entities/service/query', controller.PostQueryService())
    api.add_route('/kubernetes/entities/service', controller.GetQueryService())
    api.add_route('/kubernetes/entities/pod/query', controller.PostQueryPod())
    api.add_route('/kubernetes/entities/pod', controller.GetQueryPod())
