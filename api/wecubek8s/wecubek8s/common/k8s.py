# coding=utf-8
# coding=utf-8

from __future__ import absolute_import
import logging
import json
import base64
import urllib3

from kubernetes import client
from kubernetes.client import exceptions as k8s_exceptions
from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import exceptions

urllib3.disable_warnings()
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
        self.networking_client = client.NetworkingV1Api(api_client)

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

    def get_node(self, name, **kwargs):
        return self._action_detail(self.core_client, 'read_node', name, **kwargs)

    def patch_node(self, name, body, **kwargs):
        return self._action(self.core_client, 'patch_node', name, body, **kwargs)

    # Namespace
    def create_namespace(self, body, **kwargs):
        return self._action(self.core_client, 'create_namespace', body, **kwargs)

    def update_namespace(self, name, body, **kwargs):
        return self._action(self.core_client, 'patch_namespace', name, body, **kwargs)

    def delete_namespace(self, name, **kwargs):
        return self._action(self.core_client, 'delete_namespace', name, **kwargs)

    def get_namespace(self, name, **kwargs):
        return self._action_detail(self.core_client, 'read_namespace', name, **kwargs)

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

    # StatefulSet
    def create_statefulset(self, namespace, body, **kwargs):
        return self._action(self.app_client, 'create_namespaced_stateful_set', namespace, body, **kwargs)

    def update_statefulset(self, name, namespace, body, **kwargs):
        return self._action(self.app_client, 'patch_namespaced_stateful_set', name, namespace, body, **kwargs)

    def delete_statefulset(self, name, namespace, **kwargs):
        return self._action(self.app_client, 'delete_namespaced_stateful_set', name, namespace, **kwargs)

    def get_statefulset(self, name, namespace, **kwargs):
        return self._action_detail(self.app_client, 'read_namespaced_stateful_set', name, namespace, **kwargs)

    def list_statefulset(self, namespace, **kwargs):
        return self._action(self.app_client, 'list_namespaced_stateful_set', namespace, **kwargs)

    def list_all_statefulset(self, **kwargs):
        return self._action(self.app_client, 'list_stateful_set_for_all_namespaces', **kwargs)

    # ReplcaSet
    def list_all_replica_set(self, **kwargs):
        return self._action(self.app_client, 'list_replica_set_for_all_namespaces', **kwargs)

    # Pod
    def list_pod(self, namespace, **kwargs):
        return self._action(self.core_client, 'list_namespaced_pod', namespace, **kwargs)
    
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
            'type': 'kubernetes.io/dockerconfigjson',
            'data': {
                '.dockerconfigjson': base64.b64encode((json.dumps(auth_data).encode('utf-8'))).decode()
            }
        }
        has_secret = self.get_secret(name, namespace)
        if has_secret is None:
            self.create_secret(namespace, body, **kwargs)
        else:
            self.update_secret(name, namespace, body)
        return True

    def ensure_namespace(self, name, **kwargs):
        body = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name}, 'labels': {}}
        has_namespace = self.get_namespace(name)
        if has_namespace is None:
            self.create_namespace(body, **kwargs)
        else:
            self.update_namespace(name, body)
        return True

    # Endpoint
    def create_endpoint(self, namespace, body, **kwargs):
        return self._action(self.core_client, 'create_namespaced_endpoints', namespace, body, **kwargs)

    def update_endpoint(self, name, namespace, body, **kwargs):
        return self._action(self.core_client, 'patch_namespaced_endpoints', name, namespace, body, **kwargs)

    def delete_endpoint(self, name, namespace, **kwargs):
        return self._action(self.core_client, 'delete_namespaced_endpoints', name, namespace, **kwargs)

    def get_endpoint(self, name, namespace, **kwargs):
        return self._action_detail(self.core_client, 'read_namespaced_endpoints', name, namespace, **kwargs)

    # NetworkPolicy
    def create_network_policy(self, namespace, body, **kwargs):
        return self._action(self.networking_client, 'create_namespaced_network_policy', namespace, body, **kwargs)

    def update_network_policy(self, name, namespace, body, **kwargs):
        return self._action(self.networking_client, 'patch_namespaced_network_policy', name, namespace, body, **kwargs)

    def delete_network_policy(self, name, namespace, **kwargs):
        return self._action(self.networking_client, 'delete_namespaced_network_policy', name, namespace, **kwargs)

    def get_network_policy(self, name, namespace, **kwargs):
        return self._action_detail(self.networking_client, 'read_namespaced_network_policy', name, namespace, **kwargs)