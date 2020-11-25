# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import base64
import json

from apps.background.lib.drivers.KubernetesDrivers import SecretManager
from lib.logs import logger


class SecretApi(object):
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

        result = SecretManager.list(url=kubernetes_url, token=kubernetes_token,
                                    cafile=kubernetes_ca, version=apiversion,
                                    namespace=namespace)
        return len(result), result

    def create(self, uuid, kubernetes_url, name,
               data=None, type=None,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, namespace="default", **kwargs):

        apiversion = apiversion or "v1"
        metadata = {'name': name}
        if namespace and namespace != "default":
            metadata["namespace"] = namespace

        data = data or {}
        type = type or "kubernetes.io/basic-auth"

        if type == "kubernetes.io/basic-auth":
            key = "stringData"
        else:
            key = "data"

        create_data = {'apiVersion': apiversion,
                       'kind': 'Secret',
                       'metadata': metadata,
                       key: data
                       }

        logger.info(json.dumps(create_data))

        return SecretManager.create(uuid=uuid,
                                    createdata=create_data,
                                    url=kubernetes_url,
                                    token=kubernetes_token,
                                    cafile=kubernetes_ca,
                                    version=apiversion,
                                    namespace=namespace)

    def create_docker_register(self, uuid, kubernetes_url, name,
                               server, username, password,
                               kubernetes_token=None, kubernetes_ca=None,
                               apiversion=None, namespace="default", **kwargs):

        apiversion = apiversion or "v1"
        metadata = {'name': name}
        if namespace and namespace != "default":
            metadata["namespace"] = namespace

        _token = {server: {"username": username,
                           "password": password,
                           "email": "example-kube-secret@example.com",
                           "auth": base64.b64encode("%s:%s" % (username,
                                                               password))}}

        create_data = {'apiVersion': apiversion,
                       'kind': 'Secret',
                       'metadata': metadata,
                       "type": "kubernetes.io/dockercfg",
                       "data": {".dockercfg": base64.b64encode(json.dumps(_token))}
                       }

        logger.info(json.dumps(create_data))
        return SecretManager.create(uuid=uuid,
                                    createdata=create_data,
                                    url=kubernetes_url,
                                    token=kubernetes_token,
                                    cafile=kubernetes_ca,
                                    version=apiversion,
                                    namespace=namespace)

    def delete(self, name, kubernetes_url,
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

        return SecretManager.delete(name, url=kubernetes_url,
                                    token=kubernetes_token,
                                    cafile=kubernetes_ca,
                                    version=apiversion,
                                    namespace=namespace)

    def show(self, name, kubernetes_url,
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

        return SecretManager.describe(name,
                                      url=kubernetes_url,
                                      token=kubernetes_token,
                                      cafile=kubernetes_ca,
                                      version=apiversion,
                                      namespace=namespace)

    def detail(self, name, kubernetes_url,
               kubernetes_token=None, kubernetes_ca=None,
               apiversion=None, namespace="default", **kwargs):
        '''
        not exception
        :param name:
        :param kubernetes_url:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
        :param namespace:
        :param kwargs:
        :return:
        '''

        return SecretManager.detail(name,
                                    url=kubernetes_url,
                                    token=kubernetes_token,
                                    cafile=kubernetes_ca,
                                    version=apiversion,
                                    namespace=namespace)
