# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

from apps.common.validate_auth_info import validate_cluster_auth
from apps.common.validate_auth_info import validate_cluster_info
from core import local_exceptions as exception_common
from core import validation
from core.controller import BaseController
from lib.uuid_util import get_uuid
from .base import ServiceApi


class ServiceListController(BaseController):
    name = "Service"
    resource_describe = "Service"
    allow_methods = ("POST",)
    resource = ServiceApi()

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


class ServiceAddController(BaseController):
    name = "Service"
    resource_describe = "Service"
    allow_methods = ("POST",)
    resource = ServiceApi()

    def create(self, request, data, **kwargs):
        '''
                :param request:
                :param data:
                example:
                data = {"kubernetes_url": "xxx",
                        "kubernetes_token": "xxx",
                        "kubernetes_ca": "xxxx",
                        "apiversion": "v1",
                        "labels": "app:nginx, service:nginx",
                        "name": "nginx-dep",
                        "containerports": 8080,
                        "selector": "app:nginx",
                        "nodeport": 8080,
                        "serviceport"： 8080}
                :param kwargs:
                :return:
                '''

        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url", "name",
                                          "containerports" "nodeport",
                                          "serviceport"]
                                    )

        uuid = data.get("id", None) or get_uuid()

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        nodeport = validation.validate_port(port=data["nodeport"])
        containerport = validation.validate_port(port=data["containerport"])
        serviceport = validation.validate_port(port=data["serviceport"])

        apiversion = data.get("apiversion", "v1")
        name = data["name"]

        selector = data.get("selector", {})
        if selector:
            selector = validation.validate_dict("selector", selector)

        labels = data.get("labels", {})
        if labels:
            labels = validation.validate_dict("labels", labels)
        else:
            labels = {"svr": name}

        result = self.resource.create(uuid=uuid, name=name, nodeport=nodeport,
                                      serviceport=serviceport,
                                      containerport=containerport,
                                      kubernetes_url=kubernetes_url,
                                      kubernetes_token=kubernetes_token,
                                      kubernetes_ca=kubernetes_ca,
                                      apiversion=apiversion,
                                      labels=labels,
                                      selector=selector,
                                      namespace=data.get("namespace", "default")
                                      )
        return 1, result


class ServiceCreateController(BaseController):
    name = "Service"
    resource_describe = "Service"
    allow_methods = ("POST",)
    resource = ServiceApi()

    def _format_data(self, data):
        validate_cluster_auth(data)
        validation.not_allowed_null(data=data,
                                    keys=["kubernetes_url", "name",
                                          "containerports" "nodeport",
                                          "serviceport"]
                                    )

        uuid = data.get("id", None) or get_uuid()

        kubernetes_url = data["kubernetes_url"]
        kubernetes_token = data.get("kubernetes_token")
        kubernetes_ca = data.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        nodeport = validation.validate_port(port=data["nodeport"])
        containerport = validation.validate_port(port=data["containerport"])
        serviceport = validation.validate_port(port=data["serviceport"])

        apiversion = data.get("apiversion", "v1")
        name = data["name"]

        selector = data.get("selector", {})
        if selector:
            selector = validation.validate_dict("selector", selector)

        labels = data.get("labels", {})
        if labels:
            labels = validation.validate_dict("labels", labels)
        else:
            labels = {"svr": name}

        return {"uuid": uuid, "name": name,
                "nodeport": nodeport,
                "serviceport": serviceport,
                "containerport": containerport,
                "kubernetes_url": kubernetes_url,
                'kubernetes_token': kubernetes_token,
                'kubernetes_ca': kubernetes_ca,
                'apiversion': apiversion,
                'labels': labels,
                'selector': selector,
                'namespace': data.get("namespace", "default")
                }

    def create(self, request, data, **kwargs):
        '''
                :param request:
                :param data:
                example:
                data = {"kubernetes_url": "xxx",
                        "kubernetes_token": "xxx",
                        "kubernetes_ca": "xxxx",
                        "apiversion": "v1",
                        "labels": "app:nginx, service:nginx",
                        "name": "nginx-dep",
                        "containerports": 8080,
                        "selector": "app:nginx",
                        "nodeport": 8080,
                        "serviceport"： 8080}
                :param kwargs:
                :return:
                '''

        create_datas = []
        for _info in data:
            create_datas.append(self._format_data(_info))

        result = []
        success_service = []
        failed_service = []
        for create_data in create_datas:
            create_res = self.resource.create(**create_data)
            if create_res:
                create_data.update({"errorCode": 0, "errorMessage": ""})
                success_service.append(create_data)
            else:
                create_data.update({"errorCode": 1, "errorMessage": "创建失败"})
                failed_service.append(create_data)

        failed_name = []
        for failed in failed_service:
            failed_name.append(failed["name"])

        failed_name = ",".join(failed_name)
        result = success_service + failed_service
        if failed_deploy:
            raise exception_common.ResourceNotCompleteError(param="",
                                                            msg="service %s 部署失败" % failed_name,
                                                            return_data=result)
        return len(result), result


class ServiceIdController(BaseController):
    name = "Service.id"
    resource_describe = "Service"
    allow_methods = ('POST',)
    resource = ServiceApi()

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
        result = self.resource.show(name=name,
                                    kubernetes_url=kubernetes_url,
                                    kubernetes_token=kubernetes_token,
                                    kubernetes_ca=kubernetes_ca,
                                    apiversion=data.get("apiversion"),
                                    namespace=data.get("namespace", "default")
                                    )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return 1, result


class ServiceDelIdController(BaseController):
    name = "Service.id"
    resource_describe = "Service"
    allow_methods = ('POST',)
    resource = ServiceApi()

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

        result = self.resource.delete(name=name,
                                      kubernetes_url=kubernetes_url,
                                      kubernetes_token=kubernetes_token,
                                      kubernetes_ca=kubernetes_ca,
                                      apiversion=data.get("apiversion"),
                                      namespace=data.get("namespace", "default")
                                      )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return result
