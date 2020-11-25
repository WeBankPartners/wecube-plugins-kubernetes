# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

from apps.common.validate_auth_info import validate_cluster_auth
from apps.common.validate_auth_info import validate_cluster_info
from core import local_exceptions as exception_common
from core import validation
from core.controller import BaseController
from lib.uuid_util import get_uuid
from .base import DeploymentApi


class DeploymentListController(BaseController):
    name = "Deployment"
    resource_describe = "Deployment"
    allow_methods = ("POST",)
    resource = DeploymentApi()

    def create(self, request, data, **kwargs):
        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url"]
                                    )

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        validation.not_allowed_null(keys=["kubernetes_url"],
                                    data=data)

        count, result = self.resource.list(kubernetes_url=data["kubernetes_url"],
                                           kubernetes_token=data.get("kubernetes_token"),
                                           kubernetes_ca=data.get("kubernetes_ca"),
                                           apiversion=data.get("apiversion"),
                                           namespace=data.get("namespace"),
                                           **kwargs)
        return count, result


class DeploymentAddController(BaseController):
    name = "Deployment"
    resource_describe = "Deployment"
    allow_methods = ("POST",)
    resource = DeploymentApi()

    def create(self, request, data, **kwargs):
        '''
        :param request:
        :param data:
        example:
        data = {"kubernetes_url": "xxx",
                "kubernetes_token": "xxx",
                "kubernetes_ca": "xxxx",
                "apiversion": "apps/v1",
                "labels": "app:nginx, service:nginx",
                "name": "nginx-dep",
                "replicas": 1,
                "image": "nginx:1.15.4",
                "containername": "nginx",
                "containerlabels": "app:nginx",
                "containerports": "80, 8080",
                "selector": "app:nginx",
                "env": {"xx": 1, "xss": 2},
                "request_cpu": "1",
                "request_memory": "512Mi",
                "limit_cpu": "1.5",
                "limit_memory": "1024Mi"}
        :param kwargs:
        :return:
        '''

        uuid = data.get("id", None) or get_uuid()

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        apiversion = data.get("apiversion", "extensions/v1beta1")
        name = data["name"]
        image = data["image"]

        replicas = data.get("replicas", 1)
        replicas = validation.validate_number("replicas", replicas, min=1, max=20)

        containername = data.get("containername")
        if containername:
            containername = validation.validate_string("containername", containername)

        imagePullSecrets = data.get("imagePullSecrets")
        if imagePullSecrets:
            imagePullSecrets = validation.validate_string("imagePullSecrets", imagePullSecrets)

        docker_register_server = data.get("docker_register_server")
        if docker_register_server:
            docker_register_server = validation.validate_string("docker_register_server",
                                                                docker_register_server)

        docker_password = data.get("docker_password")
        if docker_password:
            docker_password = validation.validate_string("docker_password", docker_password)

        docker_username = data.get("docker_username")
        if docker_username:
            docker_username = validation.validate_string("docker_username", docker_username)

        containerlabels = data.get("containerlabels", {})
        if containerlabels:
            containerlabels = validation.validate_dict("containerlabels", containerlabels)
        else:
            containerlabels = {"app": name}

        selector = data.get("selector", {})
        if selector:
            selector = validation.validate_dict("selector", selector)

        labels = data.get("labels", {})
        if labels:
            labels = validation.validate_dict("labels", labels)
        else:
            labels = {"app": name}

        env = data.get("env")
        if env:
            env = validation.validate_dict("env", env)

        containerports = data.get("containerports")
        if containerports:
            containerports = validation.validate_port(containerports)

        request_cpu = data.get("request_cpu")
        if request_cpu:
            request_cpu = validation.validate_number("request_cpu",
                                                     value=request_cpu,
                                                     min=0.01, max=32)

        request_memory = data.get("request_memory")
        if request_memory:
            request_memory = validation.validate_number("request_memory",
                                                        value=request_memory,
                                                        min=128, max=64 * 1024)

        limit_cpu = data.get("limit_cpu")
        if limit_cpu:
            limit_cpu = validation.validate_number("limit_cpu",
                                                   value=limit_cpu,
                                                   min=0.01, max=32)

        limit_memory = data.get("limit_memory")
        if limit_memory:
            limit_memory = validation.validate_number("limit_memory",
                                                      value=limit_memory,
                                                      min=128, max=64 * 1024)

        result = self.resource.create(uuid=uuid, kubernetes_url=kubernetes_url,
                                      name=name, image=image,
                                      containerports=containerports,
                                      kubernetes_token=kubernetes_token,
                                      kubernetes_ca=kubernetes_ca,
                                      apiversion=apiversion, labels=labels,
                                      replicas=replicas, selector=selector,
                                      containername=containername,
                                      containerlabels=containerlabels,
                                      env=env, request_cpu=request_cpu,
                                      request_memory=request_memory,
                                      limit_cpu=limit_cpu,
                                      limit_memory=limit_memory,
                                      namespace=data.get("namespace", "default"),
                                      docker_password=docker_password,
                                      docker_username=docker_username,
                                      docker_register_server=docker_register_server,
                                      imagePullSecrets=imagePullSecrets
                                      )

        count = 1 if result else 0
        if result:
            result["uuid"] = uuid
        else:
            raise exception_common.ResoucrAddError("deployment 创建失败")

        return count, result


class DeploymentIdController(BaseController):
    name = "Deployment.id"
    resource_describe = "Deployment"
    allow_methods = ("POST",)
    resource = DeploymentApi()

    def create(self, request, data, **kwargs):
        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url", "name"]
                                    )

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        result = self.resource.show(name=data["name"],
                                    kubernetes_url=kubernetes_url,
                                    kubernetes_token=kubernetes_token,
                                    kubernetes_ca=kubernetes_ca,
                                    apiversion=data.get("apiversion"),
                                    namespace=data.get("namespace", "default")
                                    )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return 1, result


class DeploymentUpdateIdController(BaseController):
    name = "Deployment.id"
    resource_describe = "Deployment"
    allow_methods = ("PATCH",)
    resource = DeploymentApi()

    def update(self, request, data, **kwargs):
        validation.not_allowed_null(keys=["kubernetes_url", "name"],
                                    data=data)

        validate_cluster_auth(data)
        validation.validate_string("kubernetes_url", data["kubernetes_url"])
        validate_cluster_info(data["kubernetes_url"])

        kubernetes_url = data.pop("kubernetes_url", None)
        kubernetes_token = data.pop("kubernetes_token", None)
        kubernetes_ca = data.pop("kubernetes_ca", None)

        result = self.resource.update(name=data["name"], updatedata=data,
                                      kubernetes_url=kubernetes_url,
                                      kubernetes_token=kubernetes_token,
                                      kubernetes_ca=kubernetes_ca,
                                      apiversion=data.get("apiversion"),
                                      namespace=data.get("namespace", "default")
                                      )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return 1, result


class DeploymentDeleteIdController(BaseController):
    name = "Deployment.id"
    resource_describe = "Deployment"
    allow_methods = ("POST",)
    resource = DeploymentApi()

    def create(self, request, data, **kwargs):
        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url", "name"]
                                    )

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        result = self.resource.delete(name=data["name"],
                                      kubernetes_url=kubernetes_url,
                                      kubernetes_token=kubernetes_token,
                                      kubernetes_ca=kubernetes_ca,
                                      apiversion=data.get("apiversion"),
                                      namespace=data.get("namespace", "default"))
        if not result:
            raise exception_common.ResourceNotFoundError()

        return result
