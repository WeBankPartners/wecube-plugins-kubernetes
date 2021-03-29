# coding=utf-8

from __future__ import absolute_import

from talos.db import crud
from talos.core.i18n import _

from wecubek8s.common import controller
from wecubek8s.common import exceptions
from wecubek8s.apps.model import api as model_api


class PostQueryCluster(controller.ModelPostQuery):
    def list(self, req, criteria):
        return model_api.Cluster().list(criteria['filters'])


# class GetQueryCluster(controller.ModelGetQuery):
#     def list(self, req, criteria):
#         return model_api.Cluster().list(criteria['filters'])


class PostQueryNode(controller.ModelPostQuery):
    def list(self, req, criteria):
        return model_api.Node().list(criteria['filters'])


class PostQueryDeployment(controller.ModelPostQuery):
    def list(self, req, criteria):
        return model_api.Deployment().list(criteria['filters'])


class PostQueryService(controller.ModelPostQuery):
    def list(self, req, criteria):
        return model_api.Service().list(criteria['filters'])


class PostQueryPod(controller.ModelPostQuery):
    def list(self, req, criteria):
        return model_api.Pod().list(criteria['filters'])
