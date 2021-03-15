# coding=utf-8
# coding=utf-8

from __future__ import absolute_import
import logging
from os import name

from kubernetes import client
from talos.core import config
from talos.core import utils
from talos.core import exceptions as base_ex
from talos.core.i18n import _
from wecubek8s.common import exceptions

LOG = logging.getLogger(__name__)
CONF = config.CONF


class AuthToken:
    def __init__(self, api_server, token) -> None:
        self.api_server = api_server
        self.token = token

    def __call__(self, configuration) -> None:
        configuration.host = self.api_server
        configuration.verify_ssl = False
        configuration.api_key = {"authorization": "Bearer " + self.token}


class AuthUserPass:
    def __init__(self, api_server, username, password) -> None:
        self.api_server = api_server
        self.username = username
        self.password = password

    def __call__(self, configuration) -> None:
        raise NotImplementedError()


class Client:
    def __init__(self, auth, version='V1') -> None:
        # FIXME: unused version
        configuration = client.Configuration()
        auth(configuration)
        api_client = client.ApiClient(configuration)
        self.core_client = client.CoreV1Api(api_client)
        self.app_client = client.AppsV1Api(api_client)

    # deployment
    def create_deployment(self, namespace, body, **kwargs):
        return self.app_client.create_namespaced_deployment(namespace, body, **kwargs)

    def update_deployment(self, name, namespace, body, **kwargs):
        return self.app_client.patch_namespaced_deployment(name, namespace, body, **kwargs)

    def delete_deployment(self, name, namespace, **kwargs):
        return self.app_client.delete_namespaced_deployment(name, namespace, **kwargs)

    def get_deployment(self, name, namespace, **kwargs):
        return self.app_client.read_namespaced_deployment(name, namespace, **kwargs)

    def list_deployment(self, namespace, **kwargs):
        return self.app_client.list_namespaced_deployment(namespace, **kwargs)

    # service
    def create_service(self, namespace, body, **kwargs):
        return self.core_client.create_namespaced_service(namespace, body, **kwargs)

    def update_service(self, name, namespace, body, **kwargs):
        return self.core_client.patch_namespaced_service(name, namespace, body, **kwargs)

    def delete_service(self, name, namespace, **kwargs):
        return self.core_client.delete_namespaced_service(name, namespace, **kwargs)

    def get_service(self, name, namespace, **kwargs):
        return self.core_client.read_namespaced_service(name, namespace, **kwargs)

    def list_service(self, namespace, **kwargs):
        return self.core_client.list_namespaced_service(namespace, **kwargs)