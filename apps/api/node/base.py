# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import json
from werkzeug.contrib.cache import SimpleCache
from apps.background.lib.drivers.KubernetesDrivers import NodeManager
from lib.json_helper import format_json_dumps

cache = SimpleCache(default_timeout=30)


class NodeApi(object):
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

        result = NodeManager.list(url=kubernetes_url, token=kubernetes_token,
                                  cafile=kubernetes_ca, version=apiversion,
                                  namespace=namespace)
        return len(result), result

    def descibe(self, name, kubernetes_url,
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

        return NodeManager.descibe(name,
                                   url=kubernetes_url,
                                   token=kubernetes_token,
                                   cafile=kubernetes_ca)

    def _get_hostname_(self, node_info):
        '''

        :param node_info:
        :return:
        '''

        address = node_info.get("addresses")
        for info in address:
            if info.get("type") == "Hostname":
                return info.get("address")

    def node_info(self, name, kubernetes_url,
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

        node_info = self.descibe(name, kubernetes_url,
                                 kubernetes_token=kubernetes_token, kubernetes_ca=kubernetes_ca,
                                 apiversion=apiversion, namespace=namespace)
        _cache_info = cache.get(key="node_%s" % name)
        if _cache_info:
            return json.loads(_cache_info)

        if node_info:
            __node_info__ = node_info["status"]["node_info"]
            __node_allocate__ = node_info["status"]["allocatable"]
            uuid = __node_info__.get("system_uuid")
            cpu = int(__node_allocate__.get("cpu"))
            __memory__ = __node_allocate__.get("memory").split("Ki")
            memory = int(__memory__[0]) / 1024
            kernel_version = __node_info__.get("kernel_version")
            hostname = self._get_hostname_(node_info=node_info["status"])
            name = node_info["metadata"]["name"]

            result = {"name": name, "hostname": hostname,
                      "cpu": cpu, "uuid": uuid,
                      "memory": memory,
                      "kernel_version": kernel_version,
                      }
        else:
            result = {}

        cache.set(key="node_%s" % name, value=format_json_dumps(result), timeout=30)
        return result
