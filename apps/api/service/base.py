# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import json

from apps.background.lib.drivers.KubernetesDrivers import ServiceManager
from core.validation import validate_ipaddress
from lib.logs import logger


class ServiceApi(object):
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

        result = ServiceManager.list(url=kubernetes_url,
                                     token=kubernetes_token,
                                     cafile=kubernetes_ca,
                                     version=apiversion,
                                     namespace=namespace)
        return len(result), result

    def create(self, uuid, name, nodeport,
               serviceport, containerport, kubernetes_url,
               type=None, kubernetes_token=None,
               kubernetes_ca=None, apiversion=None,
               labels=None, selector=None,
               clusterIP=None, namespace="default"):
        '''
        :param uuid:
        :param name:
        :param nodeport:
        :param serviceport:
        :param containerport:
        :param kubernetes_url:
        :param type:
        :param kubernetes_token:
        :param kubernetes_ca:
        :param apiversion:
              1.6版本之前 apiVsersion：extensions/v1beta1
              1.6版本到1.9版本之间：apps/v1beta1
              1.9版本之后:apps/v1
        :param labels:
        :param selector:
        :param clusterIP:
        :param namespace:
        :return:
        '''

        authinfo = {"url": kubernetes_url, "token": kubernetes_token,
                    "cafile": kubernetes_ca}

        apiversion = apiversion or "v1"
        metadata = {"name": name}

        labels["uuid"] = uuid
        metadata["labels"] = labels

        type = type or "NodePort"

        spec_info = {"type": type, "selector": selector}

        if nodeport:
            spec_port = {"port": serviceport,
                         "targetPort": containerport, "nodePort": nodeport}
        else:
            spec_port = {"port": serviceport, "targetPort": containerport}

        spec_info["ports"] = spec_port

        if clusterIP:
            validate_ipaddress(clusterIP)
            spec_info["clusterIP"] = clusterIP

        create_data = {'apiVersion': apiversion,
                       'kind': 'Service',
                       'metadata': metadata,
                       'spec': spec_info
                       }

        logger.info(json.dumps(create_data))
        result = ServiceManager.create(uuid, createdata=create_data,
                                       url=kubernetes_url,
                                       token=kubernetes_token,
                                       cafile=kubernetes_ca,
                                       version=apiversion,
                                       namespace=namespace)
        return result

    def delete(self, name, kubernetes_url,
               kubernetes_token=None,
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

        return ServiceManager.delete(name, url=kubernetes_url,
                                     token=kubernetes_token,
                                     cafile=kubernetes_ca,
                                     version=apiversion,
                                     namespace=namespace)

    def show(self, name, kubernetes_url,
             kubernetes_token=None,
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

        return ServiceManager.query(name, url=kubernetes_url,
                                    token=kubernetes_token,
                                    cafile=kubernetes_ca,
                                    version=apiversion,
                                    namespace=namespace)
