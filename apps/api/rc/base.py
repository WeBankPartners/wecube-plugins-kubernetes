# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import json

import os

from apps.api.pod.base import PodApi
from apps.api.secret.base import SecretApi
from apps.background.lib.drivers.KubernetesDrivers import RCManager
from core import local_exceptions
from lib.json_helper import format_json_dumps
from lib.logs import logger
from lib.md5str import Md5str
from wecube_plugins_kubernetes.settings import KEY_BASE_PATH


class RCApi(object):
    def list(self, kubernetes_url, kubernetes_token=None,
             kubernetes_ca=None, apiversion=None,
             namespace=None, **kwargs):
        '''

        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :return:
        '''

        result = RCManager.list(url=kubernetes_url, token=kubernetes_token,
                                cafile=kubernetes_ca, version=apiversion,
                                namespace=namespace, **kwargs)
        return len(result), result

    def create(self, uuid, kubernetes_url, name,
               image, containerports,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, labels=None,
               replicas=None, selector=None,
               containername=None, containerlabels=None,
               env=None, request_cpu=None, request_memory=None,
               limit_cpu=None, limit_memory=None,
               namespace="default", **kwargs):
        '''

        :param uuid:
        :param kubernetes_url:
        :param name:
        :param image:
        :param containerports:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param labels:
        :param replicas:
        :param selector:
        :param containername:
        :param containerlabels:
        :param env:
        :param request_cpu:
        :param request_memory:
        :param limit_cpu:
        :param limit_memory:
        :param namespace:
        :param kwargs:
        :return:
        '''

        apiversion = apiversion or "v1"
        metadata = {'name': name}

        labels["uuid"] = uuid
        metadata["labels"] = labels

        containername = containername or name
        container_info = {"image": image, "name": containername}

        env_info = []
        if env:
            for key, value in env.items():
                env_info.append({"name": key, "value": value})

            container_info["env"] = env_info

        if request_cpu or request_memory or limit_cpu or limit_memory:
            resource_info = {}
            if request_memory or request_cpu:
                _info = {}
                if request_cpu:
                    _info["cpu"] = request_cpu
                if request_memory:
                    _info["memory"] = str(request_memory) + "Mi"
                resource_info["requests"] = _info

            if limit_cpu or limit_cpu:
                _info = {}
                if limit_cpu:
                    _info["cpu"] = limit_cpu
                if limit_memory:
                    _info["memory"] = str(limit_memory) + "Mi"

                resource_info["limits"] = _info

            container_info["resources"] = resource_info

        container_info["ports"] = [{"containerPort": int(containerports)}]

        create_data = {'apiVersion': apiversion,
                       'kind': 'ReplicationController',
                       'metadata': metadata,
                       'spec': {'replicas': replicas,
                                'selector': selector,
                                'template': {
                                    'spec': {'containers': [
                                        container_info
                                    ]},
                                    'metadata': {'labels': selector}}
                                }
                       }

        logger.info(json.dumps(create_data))

        return RCManager.create(uuid=uuid,
                                createdata=create_data,
                                url=kubernetes_url,
                                token=kubernetes_token,
                                cafile=kubernetes_ca,
                                version=apiversion,
                                namespace=namespace)

    def createsecret(self, server, username, password,
                     kubernetes_url, kubernetes_token=None,
                     kubernetes_ca=None, namespace="default"):
        '''
        :param server:
        :param username:
        :param password:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param namespace:
        :return:
        '''

        if server and username and password:
            secret_name = Md5str("%s_%s_%s" % (server, username, password))
            if os.path.exists(os.path.join(KEY_BASE_PATH, secret_name)):
                return secret_name
            SecretApi().create_docker_register(uuid=secret_name,
                                               kubernetes_url=kubernetes_url,
                                               name=secret_name,
                                               server=server,
                                               username=username,
                                               password=password,
                                               kubernetes_token=kubernetes_token,
                                               kubernetes_ca=kubernetes_ca,
                                               namespace=namespace)

            with open(os.path.join(KEY_BASE_PATH, secret_name), "wb+"):
                pass

            return secret_name

    def checksecret(self, secretname, kubernetes_url,
                    kubernetes_token=None, kubernetes_ca=None,
                    namespace="default"):
        '''

        :param secretname:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param namespace:
        :return:
        '''

        result = SecretApi().detail(name=secretname,
                                    kubernetes_url=kubernetes_url,
                                    kubernetes_token=kubernetes_token,
                                    kubernetes_ca=kubernetes_ca,
                                    namespace=namespace)

        return result

    def create_pod_containers(self, uuid, kubernetes_url, name,
                              containers=None, image_tags=None,
                              kubernetes_token=None, kubernetes_ca=None,
                              apiversion=None, labels=None,
                              replicas=None, selector=None,
                              imagePullSecrets=None, docker_password=None,
                              docker_username=None, docker_register_server=None,
                              namespace="default", **kwargs):

        apiversion = apiversion or "v1"
        metadata = {'name': name}

        image_tags = image_tags or {}
        labels.update(image_tags)

        labels["uuid"] = uuid
        metadata["labels"] = labels

        if imagePullSecrets:
            secretkey = self.checksecret(secretname=imagePullSecrets,
                                         kubernetes_url=kubernetes_url,
                                         kubernetes_token=kubernetes_token,
                                         kubernetes_ca=kubernetes_ca,
                                         namespace=namespace)
            if not secretkey:
                raise local_exceptions.ResourceValidateError("imagePullSecrets",
                                                             "secret 不存在")
        else:
            imagePullSecrets = self.createsecret(server=docker_register_server,
                                                 username=docker_username,
                                                 password=docker_password,
                                                 kubernetes_url=kubernetes_url,
                                                 kubernetes_token=kubernetes_token,
                                                 kubernetes_ca=kubernetes_ca,
                                                 namespace=namespace)

        spec_data = {'containers': containers}
        if imagePullSecrets:
            spec_data["imagePullSecrets"] = [{"name": imagePullSecrets}]

        create_data = {'apiVersion': apiversion,
                       'kind': 'ReplicationController',
                       'metadata': metadata,
                       'spec': {'replicas': replicas,
                                'selector': selector,
                                'template': {
                                    'spec': spec_data,
                                    'metadata': {'labels': selector}}
                                }
                       }

        logger.info(json.dumps(create_data))

        return RCManager.create(uuid=uuid,
                                createdata=create_data,
                                url=kubernetes_url,
                                token=kubernetes_token,
                                cafile=kubernetes_ca,
                                version=apiversion,
                                namespace=namespace)

    def delete(self, name, kubernetes_url, kubernetes_token=None,
               kubernetes_ca=None, apiversion=None, namespace="default", **kwargs):
        '''

        :param name:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        return RCManager.delete(name, url=kubernetes_url,
                                token=kubernetes_token,
                                cafile=kubernetes_ca,
                                version=apiversion,
                                namespace=namespace)

    def describe(self, name, kubernetes_url,
                 kubernetes_token=None, kubernetes_ca=None,
                 apiversion=None, namespace="default", **kwargs):
        '''

        :param name:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        result = RCManager.query(name,
                                 url=kubernetes_url,
                                 token=kubernetes_token,
                                 cafile=kubernetes_ca,
                                 version=apiversion,
                                 namespace=namespace)

        print(format_json_dumps(result))

        return result

    def _container_info(self, container, labels):
        _template = {}

        _template["image"] = container["image"]
        _template["container_spec_name"] = container["name"]
        _template["ports"] = container["ports"]
        _template["env"] = container["env"]
        _template["command"] = container["command"]
        _template["volume_mounts"] = container["volume_mounts"]
        _template["volume_devices"] = container["volume_devices"]

        image_id = None
        if labels:
            image_id = labels.get(container["image"])

        _template["image_id"] = image_id

        return _template

    def _selector_info(self, selector, kubernetes_url, kubernetes_token=None,
                       kubernetes_ca=None, apiversion=None, namespace=None):
        '''

        :param selector: {"key": "value"}
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :return:
        '''

        _info_ = []
        for key, value in selector.items():
            _info_.append("%s=%s" % (key, value))

        info = ",".join(_info_)

        apiversion = apiversion or "v1"
        pod_lists = PodApi().rc_pod_detail(kubernetes_url,
                                           label_selector=info,
                                           kubernetes_token=kubernetes_token,
                                           kubernetes_ca=kubernetes_ca,
                                           apiversion=apiversion,
                                           namespace=namespace)

        return pod_lists

    def __format_containers__(self, containers):
        '''

        :param containers:
        :return:
        '''

        result = []
        for container in containers:
            _info = {}
            _info["image"] = container["image"]
            _info["command"] = container["command"]
            _info["name"] = container["name"]
            _info["env"] = container["env"]
            _info["ports"] = container["ports"]
            _info["volume_mounts"] = container["volume_mounts"]
            _info["volume_devices"] = container["volume_devices"]
            result.append(_info)

        return result

    def detail(self, name, kubernetes_url,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, namespace="default", **kwargs):
        '''

        :param name:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        rc_info = RCManager.query(name,
                                  url=kubernetes_url,
                                  token=kubernetes_token,
                                  cafile=kubernetes_ca,
                                  version=apiversion,
                                  namespace=namespace)

        if not rc_info:
            return {}

        print(format_json_dumps(rc_info))
        template = {}
        template["replicas"] = rc_info["status"]["replicas"]
        template["ready_replicas"] = rc_info["status"]["ready_replicas"]
        template["name"] = rc_info["metadata"]["name"]
        template["labels"] = rc_info["metadata"]["labels"]
        template["namespace"] = rc_info["metadata"]["namespace"]
        template["uid"] = rc_info["metadata"]["uid"]
        template["created_time"] = rc_info["metadata"]["creation_timestamp"]
        template["selector"] = rc_info["spec"]["selector"]

        __template_spec__ = rc_info["spec"]["template"]
        template["volumes"] = __template_spec__["spec"]["volumes"]
        template["restart_policy"] = __template_spec__["spec"]["restart_policy"]
        template["ora_containers"] = self.__format_containers__(containers=__template_spec__["spec"]["containers"])

        pod_lists = self._selector_info(selector=rc_info["spec"]["selector"],
                                        kubernetes_url=kubernetes_url,
                                        kubernetes_token=kubernetes_token,
                                        kubernetes_ca=kubernetes_ca,
                                        apiversion=apiversion,
                                        namespace=namespace)

        template["pods"] = pod_lists
        return template

    def search_rc_pods(self, selector, kubernetes_url,
                       kubernetes_token=None, kubernetes_ca=None,
                       apiversion=None, namespace="default", **kwargs):
        '''

        :param name:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        return self._selector_info(selector=selector,
                                   kubernetes_url=kubernetes_url,
                                   kubernetes_token=kubernetes_token,
                                   kubernetes_ca=kubernetes_ca,
                                   apiversion=apiversion,
                                   namespace=namespace)

    def update(self, name, updatedata, kubernetes_url,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, namespace="default", **kwargs):

        '''

        :param name:
        :param updatedata:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        return RCManager.update(name, updatedata,
                                url=kubernetes_url,
                                token=kubernetes_token,
                                cafile=kubernetes_ca,
                                version=apiversion,
                                namespace=namespace
                                )
