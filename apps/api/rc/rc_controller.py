# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import random
import time
from apps.common.validate_auth_info import validate_cluster_auth
from apps.common.validate_auth_info import validate_cluster_info
from core import local_exceptions as exception_common
from core import validation
from core.controller import BaseController
from lib.json_helper import format_json_dumps
from lib.uuid_util import get_uuid
from .base import RCApi


class RCListController(BaseController):
    name = "RC"
    resource_describe = "RC"
    allow_methods = ('POST',)
    resource = RCApi()

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


class RCAddController(BaseController):
    name = "RC"
    resource_describe = "RC"
    allow_methods = ("POST")
    resource = RCApi()

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
                    "name":"mysql-rc",
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
                                    keys=["kubernetes_url", "name",
                                          "image", "containerports"]
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
        image = data["image"]

        replicas = data.get("replicas", 1)
        replicas = validation.validate_number("replicas", replicas, min=1, max=20)

        containername = data.get("containername")
        if containername:
            containername = validation.validate_string("containername", containername)

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
                                      namespace=data.get("namespace", "default")
                                      )

        count = 1 if result else 0
        if result:
            result["uuid"] = uuid
        else:
            raise exception_common.ResoucrAddError("rc 创建失败")

        return count, result


class RCCreateController(BaseController):
    name = "RC"
    resource_describe = "RC"
    allow_methods = ("POST")
    resource = RCApi()

    def _format_data(self, deployment):
        validate_cluster_auth(deployment)
        validation.not_allowed_null(data=deployment,
                                    keys=["kubernetes_url", "name",
                                          "image", "containername", "containerports"]
                                    )

        kubernetes_url = deployment["kubernetes_url"]
        kubernetes_token = deployment.get("kubernetes_token")
        kubernetes_ca = deployment.get("kubernetes_ca")

        validation.validate_string("kubernetes_url", kubernetes_url)
        validation.validate_string("kubernetes_token", kubernetes_token)
        validation.validate_string("kubernetes_ca", kubernetes_ca)
        validate_cluster_info(kubernetes_url)

        name = deployment["name"]
        containername = validation.validate_string("containername", deployment.get("containername"))

        containerlabels = deployment.get("containerlabels", {})
        if containerlabels:
            containerlabels = validation.validate_dict("containerlabels", containerlabels)
        else:
            containerlabels = {"app": name}

        selector = deployment.get("selector", {})
        if selector:
            selector = validation.validate_dict("selector", selector)
        else:
            selector = {"app": name}

        labels = deployment.get("labels", {})
        if labels:
            labels = validation.validate_dict("labels", labels)
        else:
            labels = {"app": name}

        env = deployment.get("env")
        if env:
            env = validation.validate_dict("env", env)

        containerports = deployment.get("containerports")
        if containerports:
            containerports = validation.validate_port(containerports)

        request_cpu = deployment.get("request_cpu")
        if request_cpu:
            request_cpu = validation.validate_number("request_cpu",
                                                     value=request_cpu,
                                                     min=0.01, max=32)

        request_memory = deployment.get("request_memory")
        if request_memory:
            request_memory = validation.validate_number("request_memory",
                                                        value=request_memory,
                                                        min=128, max=64 * 1024)

        limit_cpu = deployment.get("limit_cpu")
        if limit_cpu:
            limit_cpu = validation.validate_number("limit_cpu",
                                                   value=limit_cpu,
                                                   min=0.01, max=32)

        limit_memory = deployment.get("limit_memory")
        if limit_memory:
            limit_memory = validation.validate_number("limit_memory",
                                                      value=limit_memory,
                                                      min=128, max=64 * 1024)

        replicas = deployment.get("replicas", 1)
        apiversion = deployment.get("apiversion", "v1")
        name = deployment["name"]
        image = deployment["image"]

        return {"kubernetes_url": kubernetes_url, "name": name,
                "id": deployment.get("id"),
                "image": image, "containerports": containerports,
                "kubernetes_token": kubernetes_token,
                "kubernetes_ca": kubernetes_ca,
                "apiversion": apiversion,
                "replicas": replicas,
                "labels": labels, "selector": selector,
                "containername": containername,
                "containerlabels": containerlabels,
                "env": env, "request_cpu": request_cpu,
                "request_memory": request_memory,
                "limit_cpu": limit_cpu,
                "limit_memory": limit_memory,
                "namespace": deployment.get("namespace", "default"),
                "instance_id": deployment.get("instance_id", "123h3g1hg_%s" % (random.randint(0, 30)))}

    def _fetch_deployment(self, deployments):
        info = {}
        instance_map = {}
        for deployment in deployments:
            name = deployment.get("name")
            if name in info.keys():
                info[name].append(deployment)
            else:
                info[name] = [deployment]

        result = []

        for deploymentname, deploy in info.items():
            uuid = deploy[0].get("id", None) or get_uuid()
            _info = {"uuid": uuid,
                     "name": deploymentname,
                     "kubernetes_url": deploy[0]["kubernetes_url"],
                     "kubernetes_token": deploy[0]["kubernetes_token"],
                     "kubernetes_ca": deploy[0]["kubernetes_ca"],
                     "apiversion": deploy[0]["apiversion"],
                     "selector": deploy[0]["selector"],
                     "labels": deploy[0]["labels"],
                     "namespace": deploy[0]["namespace"],
                     "replicas": deploy[0]["replicas"],
                     "image_tags": instance_map
                     }

            containers = []

            for container_info in deploy:
                build_info = {}
                build_info["image"] = container_info["image"]
                build_info["name"] = container_info["containername"]

                env = container_info["env"]
                env_info = [{"name": "creator", "value": "wecube_plugins_kubernetes"}]
                if env:
                    for key, value in env.items():
                        env_info.append({"name": key, "value": value})

                build_info["env"] = env_info
                build_info["ports"] = [{"containerPort": container_info["containerports"]}]
                build_info["resources"] = {"requests": {"cpu": container_info.get("request_cpu", 0.01),
                                                        "memory": str(
                                                            container_info.get("request_memory", "256")) + "Mi"},
                                           "limits": {"cpu": container_info.get("limit_cpu", 1),
                                                      "memory": str(container_info.get("limit_memory", "256")) + "Mi"}}

                containers.append(build_info)

            _info["containers"] = containers
            result.append(_info)

        return result

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
                    "name":"mysql-rc",
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

        metadata_lists = []
        for deployment in data:
            metadata_lists.append(self._format_data(deployment))

        create_datas = self._fetch_deployment(metadata_lists)
        success_deploy = []
        failed_deploy = []
        for create_data in create_datas:
            try:
                _create_res = self.resource.create_pod_containers(uuid=create_data["uuid"],
                                                                  kubernetes_url=create_data.get("kubernetes_url"),
                                                                  name=create_data.get("name"),
                                                                  containers=create_data.get("containers"),
                                                                  image_tags=create_data.get("image_tags", {}),
                                                                  kubernetes_token=create_data.get("kubernetes_token"),
                                                                  kubernetes_ca=create_data.get("kubernetes_ca"),
                                                                  apiversion=create_data.get("apiversion"),
                                                                  labels=create_data.get("labels"),
                                                                  replicas=create_data.get("replicas"),
                                                                  selector=create_data.get("selector"),
                                                                  namespace=create_data.get("namespace", "default"))
                success_deploy.append(create_data)
            except Exception, e:
                failed_deploy.append(create_data)

        time.sleep(2)
        result = []
        for deployment_info in success_deploy:
            _info_ = self.resource.detail(name=deployment_info["name"],
                                          kubernetes_url=deployment_info.get("kubernetes_url"),
                                          kubernetes_token=create_data.get("kubernetes_token"),
                                          kubernetes_ca=create_data.get("kubernetes_ca"),
                                          apiversion=create_data.get("apiversion"),
                                          namespace=create_data.get("namespace", "default"))

            pods = _info_["pods"]
            result = result + pods

        failed_name = []
        for failed in failed_deploy:
            failed_name.append(failed["name"])

        failed_name = ",".join(failed_name)

        if failed_deploy:
            raise exception_common.ResourceNotCompleteError(param="",
                                                            msg="deployment %s 部署失败" % failed_name,
                                                            return_data=result)

        print(format_json_dumps(result))

        return len(result), result


class RCIdController(BaseController):
    name = "RC.id"
    resource_describe = "RC"
    allow_methods = ("POST",)
    resource = RCApi()

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
        result = self.resource.describe(name=name,
                                        kubernetes_url=kubernetes_url,
                                        kubernetes_token=kubernetes_token,
                                        kubernetes_ca=kubernetes_ca,
                                        apiversion=data.get("apiversion"),
                                        namespace=data.get("namespace", "default")
                                        )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return 1, result


class RCUpdateController(BaseController):
    name = "RC"
    resource_describe = "RC"
    allow_methods = ("PATCH",)
    resource = RCApi()

    def update(self, request, data, **kwargs):
        validation.not_allowed_null(keys=["kubernetes_url", "name"],
                                    data=data)

        name = data["name"]
        validate_cluster_auth(data)
        validation.validate_string("kubernetes_url", data["kubernetes_url"])
        validate_cluster_info(data["kubernetes_url"])

        kubernetes_url = data.pop("kubernetes_url", None)
        kubernetes_token = data.pop("kubernetes_token", None)
        kubernetes_ca = data.pop("kubernetes_ca", None)

        result = self.resource.update(name=name, updatedata=data,
                                      kubernetes_url=kubernetes_url,
                                      kubernetes_token=kubernetes_token,
                                      kubernetes_ca=kubernetes_ca,
                                      apiversion=data.get("apiversion"),
                                      namespace=data.get("namespace", "default")
                                      )
        if not result:
            raise exception_common.ResourceNotFoundError()

        return 1, result


class RCDeleteController(BaseController):
    name = "RC"
    resource_describe = "RC"
    allow_methods = ("POST",)
    resource = RCApi()

    def _format_data(self, data):
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

        return {"kubernetes_url": kubernetes_url,
                "name": name,
                "kubernetes_token": kubernetes_token,
                "kubernetes_ca": kubernetes_ca,
                "namespace": data.get("namespace", "default"),
                "apiversion": data.get("apiversion")
                }

    def create(self, request, data, **kwargs):
        search_datas = []
        for info in data:
            search_datas.append(self._format_data(info))

        success = []
        failed = []
        for search_data in search_datas:
            result = self.resource.delete(name=search_data["name"],
                                          kubernetes_url=search_data["kubernetes_url"],
                                          kubernetes_token=search_data["kubernetes_token"],
                                          kubernetes_ca=search_data["kubernetes_ca"],
                                          apiversion=search_data.get("apiversion"),
                                          namespace=search_data.get("namespace", "default")
                                          )
            if result:
                _data = {"errorCode": 0, "errorMessage": "success", "name": search_data["name"]}
                success.append(_data)
            else:
                _data = {"errorCode": 1, "errorMessage": "删除失败", "name": search_data["name"]}
                failed.append(_data)

        failed_name = []
        return_data = success + failed
        for failed in failed:
            failed_name.append(failed["name"])

        failed_name = ",".join(failed_name)
        if failed:
            raise exception_common.ResourceOpearateNotSuccess(param="name",
                                                              msg="%s 删除失败" % failed_name,
                                                              return_data=return_data)

        return len(return_data), return_data
