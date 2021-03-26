# coding=utf-8
# coding=utf-8

from __future__ import absolute_import
import logging
import json
import base64

from kubernetes import client
from kubernetes.client import exceptions as k8s_exceptions
from talos.core import config
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
    def __init__(self, auth) -> None:
        configuration = client.Configuration()
        auth(configuration)
        self.auth = auth
        api_client = client.ApiClient(configuration)
        self.core_client = client.CoreV1Api(api_client)
        self.app_client = client.AppsV1Api(api_client)

    def _action(self, client, func_name, *args, **kwargs):
        func = getattr(client, func_name)
        try:
            result = func(*args, **kwargs)
            return result
        except k8s_exceptions.ApiException as e:
            raise exceptions.K8sCallError(cluster=self.auth.api_server, msg=json.loads(e.body)['message'])

    def _action_detail(self, client, func_name, *args, **kwargs):
        func = getattr(client, func_name)
        try:
            result = func(*args, **kwargs)
            return result
        except k8s_exceptions.ApiException as e:
            if e.status == 404:
                return None
            raise exceptions.K8sCallError(cluster=self.auth.api_server, msg=json.loads(e.body)['message'])

    # Node
    def list_node(self, **kwargs):
        return self._action(self.core_client, 'list_node', **kwargs)

    # Namespace
    def list_namespace(self, **kwargs):
        return self._action(self.core_client, 'list_namespace', **kwargs)

    # Deployment
    def create_deployment(self, namespace, body, **kwargs):
        return self._action(self.app_client, 'create_namespaced_deployment', namespace, body, **kwargs)

    def update_deployment(self, name, namespace, body, **kwargs):
        return self._action(self.app_client, 'patch_namespaced_deployment', name, namespace, body, **kwargs)

    def delete_deployment(self, name, namespace, **kwargs):
        return self._action(self.app_client, 'delete_namespaced_deployment', name, namespace, **kwargs)

    def get_deployment(self, name, namespace, **kwargs):
        return self._action_detail(self.app_client, 'read_namespaced_deployment', name, namespace, **kwargs)

    def list_deployment(self, namespace, **kwargs):
        return self._action(self.app_client, 'list_namespaced_deployment', namespace, **kwargs)

    def list_all_deployment(self, **kwargs):
        return self._action(self.app_client, 'list_deployment_for_all_namespaces', **kwargs)

    # ReplcaSet
    def list_all_replica_set(self, **kwargs):
        return self._action(self.app_client, 'list_replica_set_for_all_namespaces', **kwargs)

    # Pod
    def list_all_pod(self, **kwargs):
        return self._action(self.core_client, 'list_pod_for_all_namespaces', **kwargs)

    # Service
    def create_service(self, namespace, body, **kwargs):
        return self._action(self.core_client, 'create_namespaced_service', namespace, body, **kwargs)

    def update_service(self, name, namespace, body, **kwargs):
        return self._action(self.core_client, 'patch_namespaced_service', name, namespace, body, **kwargs)

    def delete_service(self, name, namespace, **kwargs):
        return self._action(self.core_client, 'delete_namespaced_service', name, namespace, **kwargs)

    def get_service(self, name, namespace, **kwargs):
        return self._action_detail(self.core_client, 'read_namespaced_service', name, namespace, **kwargs)

    def list_service(self, namespace, **kwargs):
        return self._action(self.core_client, 'list_namespaced_service', namespace, **kwargs)

    def list_all_service(self, **kwargs):
        return self._action(self.core_client, 'list_service_for_all_namespaces', **kwargs)

    # Secret
    def create_secret(self, namespace, body, **kwargs):
        return self._action(self.core_client, 'create_namespaced_secret', namespace, body, **kwargs)

    def update_secret(self, name, namespace, body, **kwargs):
        return self._action(self.core_client, 'patch_namespaced_secret', name, namespace, body, **kwargs)

    def delete_secret(self, name, namespace, **kwargs):
        return self._action(self.core_client, 'delete_namespaced_secret', name, namespace, **kwargs)

    def get_secret(self, name, namespace, **kwargs):
        return self._action_detail(self.core_client, 'read_namespaced_secret', name, namespace, **kwargs)

    def list_secret(self, namespace, **kwargs):
        return self._action(self.core_client, 'list_namespaced_secret', namespace, **kwargs)

    def ensure_registry_secret(self, name, namespace, server, username, password, email=None, **kwargs):
        auth_data = {
            'auths': {
                server: {
                    "username": username,
                    "password": password,
                    "auth": base64.b64encode(("%s:%s" % (username, password)).encode('utf-8')).decode()
                }
            }
        }
        if email is not None:
            auth_data[server]['email'] = email

        body = {
            'apiVersion': 'v1',
            'kind': 'Secret',
            'metadata': {
                'name': name,
                'namespace': namespace
            },
            "type": "kubernetes.io/dockerconfigjson",
            "data": {
                ".dockerconfigjson": base64.b64encode((json.dumps(auth_data).encode('utf-8'))).decode()
            }
        }
        has_secret = self.get_secret(name, namespace)
        if has_secret is None:
            self.create_secret(namespace, body, **kwargs)
        else:
            self.update_secret(name, namespace, body)
        return True