# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import json
import os
from apps.api.secret.base import SecretApi
from apps.background.lib.drivers.KubernetesDrivers import DeploymentManager
from core import local_exceptions
from lib.logs import logger
from lib.md5str import Md5str
from wecube_plugins_kubernetes.settings import KEY_BASE_PATH

if not KEY_BASE_PATH:
    if not os.path.exists(KEY_BASE_PATH):
        os.mkdir(KEY_BASE_PATH)


class DeploymentApi(object):
    def list(self, kubernetes_url, kubernetes_token=None,
             kubernetes_ca=None, apiversion=None,
             namespace="default", **kwargs):
        '''
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        result = DeploymentManager.list(url=kubernetes_url,
                                        token=kubernetes_token,
                                        cafile=kubernetes_ca,
                                        version=apiversion,
                                        namespace=namespace)
        return len(result), result

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

    def create(self, uuid, kubernetes_url, name, image, containerports,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, labels=None, replicas=None,
               containername=None, containerlabels=None, selector=None,
               env=None, request_cpu=None, request_memory=None,
               limit_cpu=None, limit_memory=None,
               namespace="default", docker_password=None,
               docker_username=None, docker_register_server=None,
               imagePullSecrets=None, **kwargs):
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
        :param containername:
        :param containerlabels:
        :param selector:
        :param env:
        :param request_cpu:
        :param request_memory:
        :param limit_cpu:
        :param limit_memory:
        :param namespace:
        :param kwargs:
        :return:
        '''

        apiversion = apiversion or "extensions/v1beta1"
        metadata = {'name': name}

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

        spec_data = {'containers': [container_info]}
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
        result = DeploymentManager.create(uuid,
                                          createdata=create_data,
                                          url=kubernetes_url,
                                          token=kubernetes_token,
                                          cafile=kubernetes_ca,
                                          version=apiversion,
                                          namespace=namespace)
        return result

    def show(self, name, kubernetes_url, kubernetes_token=None,
             kubernetes_ca=None, apiversion=None,
             namespace="default", **kwargs):
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

        return DeploymentManager.query(name,
                                       url=kubernetes_url,
                                       token=kubernetes_token,
                                       cafile=kubernetes_ca,
                                       version=apiversion,
                                       namespace=namespace)

    def update(self, name, updatedata, kubernetes_url,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, namespace="default", **kwargs):

        result = DeploymentManager.update(name, updatedata,
                                          url=kubernetes_url,
                                          token=kubernetes_token,
                                          cafile=kubernetes_ca,
                                          version=apiversion,
                                          namespace=namespace
                                          )
        return result

    def delete(self, name, kubernetes_url,
               kubernetes_token=None,
               kubernetes_ca=None,
               apiversion=None,
               namespace="default", **kwargs):

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

        result = DeploymentManager.delete(name, url=kubernetes_url,
                                          token=kubernetes_token,
                                          cafile=kubernetes_ca,
                                          version=apiversion,
                                          namespace=namespace)
        return result
