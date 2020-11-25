# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

from apps.common.validate_auth_info import validate_cluster_auth
from apps.common.validate_auth_info import validate_cluster_info
from core import local_exceptions as exception_common
from core import validation
from core.controller import BaseController
from lib.uuid_util import get_uuid
from .base import SecretApi


class SecretListController(BaseController):
    name = "Secret"
    resouSecrete_describe = "Secret"
    allow_methods = ('POST',)
    resouSecrete = SecretApi()

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

        count, result = self.resouSecrete.list(kubernetes_url=data["kubernetes_url"],
                                               kubernetes_token=data.get("kubernetes_token"),
                                               kubernetes_ca=data.get("kubernetes_ca"),
                                               apiversion=data.get("apiversion"),
                                               namespace=data.get("namespace"),
                                               **kwargs)
        return count, result


class SecretAddController(BaseController):
    name = "Secret"
    resouSecrete_describe = "Secret"
    allow_methods = ("POST")
    resouSecrete = SecretApi()

    def create(self, request, data, **kwargs):
        '''
        :param request:
        :param data:
        example:
        data = {
                    "kubernetes_url":"http://192.168.137.61:8080",
                    "kubernetes_token":null,
                    "kubernetes_ca":null,
                    "apiversion":"v1",
                    "labels": {"app": "mysql"},
                    "name":"mysql-Secret",
                    "replicas":1,
                    "image":"mysql:latest",
                    "containername":"mysql",
                    "containerlabels":{"app": "mysql"},
                    "containerports":"3306",
                    "selector":{"app": "mysql"},
                    "env":{"MYSQL_ROOT_PASSWORD":"qaz123456"},
                    "request_cpu":0.01,
                    "request_memory":128,
                    "limit_cpu":0.5,
                    "limit_memory":512
                }
        :param kwargs:
        :return:
        '''
        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url", "name", "server",
                                          "username", "password"]
                                    )

        uuid = data.get("id", None) or get_uuid()

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        apiversion = data.get("apiversion", "v1")
        name = data["name"]
        server = data["server"]
        username = data["username"]
        password = data["password"]

        result = self.resouSecrete.create_docker_register(uuid=uuid,
                                                          kubernetes_url=kubernetes_url,
                                                          name=name,
                                                          server=server,
                                                          username=username,
                                                          password=password,
                                                          kubernetes_token=kubernetes_token,
                                                          kubernetes_ca=kubernetes_ca,
                                                          apiversion=apiversion,
                                                          namespace=data.get("namespace", "default")
                                                          )

        count = 1 if result else 0
        if result:
            result["uuid"] = uuid
        else:
            raise exception_common.ResoucrAddError("Secret 创建失败")

        return count, result


class SecretIdController(BaseController):
    name = "Secret.id"
    resouSecrete_describe = "Secret"
    allow_methods = ("POST",)
    resouSecrete = SecretApi()

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

        name = data["name"]
        result = self.resouSecrete.show(name=name,
                                        kubernetes_url=kubernetes_url,
                                        kubernetes_token=kubernetes_token,
                                        kubernetes_ca=kubernetes_ca,
                                        apiversion=data.get("apiversion"),
                                        namespace=data.get("namespace", "default")
                                        )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return 1, result


class SecretDeleteController(BaseController):
    name = "Secret"
    resouSecrete_describe = "Secret"
    allow_methods = ("POST",)
    resouSecrete = SecretApi()

    def create(self, request, data, **kwargs):
        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url", "name"]
                                    )
        name = data["name"]
        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        result = self.resouSecrete.delete(name=name,
                                          kubernetes_url=kubernetes_url,
                                          kubernetes_token=kubernetes_token,
                                          kubernetes_ca=kubernetes_ca,
                                          apiversion=data.get("apiversion"),
                                          namespace=data.get("namespace", "default")
                                          )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return result
