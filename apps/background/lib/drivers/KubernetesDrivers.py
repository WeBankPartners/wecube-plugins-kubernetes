# coding:utf-8

from __future__ import (absolute_import, division, print_function, unicode_literals)

import traceback

import os
from kubernetes import client
from kubernetes.client import api_client
from kubernetes.client.apis import core_v1_api
from apps.common.toyaml import dict_to_yamlfile
from core import local_exceptions
from lib.logs import logger
from lib.md5str import Md5str
from wecube_plugins_kubernetes.settings import CAFILE_PATH
from wecube_plugins_kubernetes.settings import YAML_TMP_PATH

if not os.path.exists(CAFILE_PATH):
    os.makedirs(CAFILE_PATH)

if not os.path.exists(YAML_TMP_PATH):
    os.makedirs(YAML_TMP_PATH)


def check_or_create_pem(cafile):
    camd5 = Md5str(cafile)
    pempath = os.path.join(CAFILE_PATH, camd5 + ".pem")
    if not os.path.exists(pempath):
        with open(pempath, "wb+") as file:
            file.write(cafile)
            file.flush()

    return pempath


class K8sBaseClient(object):
    def __init__(self, url, token=None, cafile=None):
        self.token = token
        self.k8s_url = url
        self.cafile = cafile
        self.verify_https = False
        if self.k8s_url.startswith("https") and cafile:
            self.verify_https = True

    def _auth_http_api(self):
        configuration = client.Configuration()
        configuration.host = self.k8s_url
        if self.token:
            configuration.api_key = {"authorization": "Bearer " + self.token}

        if self.cafile:
            configuration.ssl_ca_cert = check_or_create_pem(self.cafile)
        configuration.verify_ssl = self.verify_https

        return api_client.ApiClient(configuration=configuration)

    def _auth_https_api(self):
        configuration = client.Configuration()
        configuration.host = self.k8s_url
        if self.token:
            configuration.api_key = {"authorization": "Bearer " + self.token}

        return api_client.ApiClient(configuration=configuration)

    def func_client(self):
        raise NotImplementedError("not define")

    def client(self):
        try:
            return self.func_client()
        except NotImplementedError, e:
            raise NotImplementedError("not define")
        except Exception, e:
            logger.info(e.message)
            logger.info(traceback.format_exc())
            raise local_exceptions.AuthFailedError("kubernetes 认证失败")


class K8sCoreClient(K8sBaseClient):
    '''
    CoreV1Api
    '''

    def func_client(self):
        if self.k8s_url.startswith("https"):
            return core_v1_api.CoreV1Api(self._auth_https_api())
        return core_v1_api.CoreV1Api(self._auth_http_api())


class K8sAppsClient(K8sBaseClient):
    '''
    AppsV1Api
    '''

    def func_client(self):
        if self.k8s_url.startswith("https"):
            return client.AppsV1Api(self._auth_https_api())
        return client.AppsV1Api(self._auth_http_api())


class K8sExtensionsV1beta1Client(K8sBaseClient):
    '''
    ExtensionsV1beta1Api
    '''

    def func_client(self):
        if self.k8s_url.startswith("https"):
            return client.ExtensionsV1beta1Api(self._auth_https_api())
        return client.ExtensionsV1beta1Api(self._auth_http_api())


class K8sAppsV1beta1ApiClient(K8sBaseClient):
    '''
    AppsV1beta1Api
    '''

    def func_client(self):
        if self.k8s_url.startswith("https"):
            return client.AppsV1beta1Api(self._auth_https_api())
        return client.AppsV1beta1Api(self._auth_http_api())


class PodManager(object):
    @classmethod
    def client(cls, url, token=None, cafile=None, version=None):
        _client = K8sCoreClient(url=url, token=token, cafile=cafile)
        return _client.client()

    @classmethod
    def list(cls, url, token=None, cafile=None,
             version=None, namespace=None, **kwargs):
        '''

        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :param kwargs:
        :return:
        '''

        client = cls.client(url=url, token=token, cafile=cafile, version=version)

        try:
            if namespace:
                resp = client.list_namespaced_pod(namespace=namespace, **kwargs)
            else:
                resp = client.list_pod_for_all_namespaces(**kwargs)

            _tmp = resp.to_dict().items()
            result = _tmp[0][1]
            return result
        except Exception, e:
            logger.info(e.message)
            logger.info(traceback.format_exc())
            return []

    @classmethod
    def descibe(cls, name, url, token=None, cafile=None,
                version=None, namespace='default'):

        try:
            apiclient = cls.client(url=url, token=token,
                                   cafile=cafile, version=version)

            resp = apiclient.read_namespaced_pod(name, namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            logger.info("query pod %s failed" % (name))
            return {}


class RCManager(object):
    @classmethod
    def client(cls, url, token=None, cafile=None, version=None):
        _client = K8sCoreClient(url=url, token=token, cafile=cafile)
        return _client.client()

    @classmethod
    def list(cls, url, token=None, cafile=None,
             version=None, namespace=None, **kwargs):
        '''

        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :param kwargs:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        try:
            if namespace:
                resp = apiclient.list_namespaced_replication_controller(namespace=namespace, **kwargs)
            else:
                resp = apiclient.list_replication_controller_for_all_namespaces()

            _tmp = resp.to_dict().items()
            result = _tmp[0][1]
            return result
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return []

    @classmethod
    def create(cls, uuid, createdata,
               url, token=None, cafile=None,
               version=None, namespace="default"):
        '''

        :param uuid:
        :param createdata:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        filepath = os.path.join(YAML_TMP_PATH, "%s_rc.yaml" % uuid)
        dict_to_yamlfile(data=createdata, filepath=filepath)

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        try:
            resp = apiclient.create_namespaced_replication_controller(body=createdata, namespace=namespace)
            return resp.to_dict()
        except client.ApiException, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            if e.status == 409:
                return {"status": 409}
            return {}
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return {}

    @classmethod
    def query(cls, name, url, token=None, cafile=None,
              version=None, namespace="default"):
        try:
            return cls.describe(name=name, url=url, token=token,
                                cafile=cafile, version=version,
                                namespace=namespace)
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            logger.info("query rc %s error" % (name))
            return {}

    @classmethod
    def describe(cls, name, url, token=None, cafile=None,
                 version=None, namespace="default"):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        resp = apiclient.read_namespaced_replication_controller(name, namespace)
        return resp.to_dict()

    @classmethod
    def update(cls, name, updatedata, url, token=None, cafile=None,
               version=None, namespace="default"):
        '''

        :param apiclient:
        :param depname:
        :param updatedata:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        updateobject = cls.query(apiclient, name, namespace)
        if not updateobject:
            raise local_exceptions.ResourceNotFoundError("rc %s not found" % name)

        resp = apiclient.patch_namespaced_replication_controller(name=name,
                                                                 namespace=namespace,
                                                                 body=updateobject)

        return resp.metadata

    @classmethod
    def delete(cls, name, url, token=None, cafile=None,
               version=None, namespace="default"):
        '''

        :param apiclient:
        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        depobject = cls.query(name, url, token=token, cafile=cafile,
                              version=version, namespace=namespace)

        if not depobject:
            return 0

        resp = apiclient.delete_namespaced_replication_controller(name=name,
                                                                  namespace=namespace)
        return resp.to_dict()

    @classmethod
    def rollingUpdate(cls):
        pass


class DeploymentManager(object):
    @classmethod
    def client(cls, url, token=None, cafile=None, version=None):
        if version == "extensions/v1beta1":
            _client = K8sExtensionsV1beta1Client(url=url, token=token, cafile=cafile)
            return _client.client()

        _client = K8sAppsClient(url=url, token=token, cafile=cafile)
        return _client.client()

    @classmethod
    def list(cls, url, token=None, cafile=None, version=None, namespace=None, **kwargs):
        '''
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :param kwargs:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        try:
            namespace = kwargs.pop("namespace", None)
            if namespace:
                resp = apiclient.list_namespaced_deployment(namespace=namespace)
            else:
                resp = apiclient.list_deployment_for_all_namespaces()

            _tmp = resp.to_dict().items()
            result = _tmp[0][1]
            return result
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return []

    @classmethod
    def create(cls, uuid, createdata, url, token=None,
               cafile=None, version=None, namespace="default"):
        '''

        :param uuid:
        :param createdata:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        if not isinstance(createdata, dict):
            raise ValueError("data must be json")

        filepath = os.path.join(YAML_TMP_PATH, "%s_deployment.yaml" % uuid)
        dict_to_yamlfile(data=createdata, filepath=filepath)

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        try:
            resp = apiclient.create_namespaced_deployment(body=createdata, namespace=namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return {}

    @classmethod
    def query(cls, depname, url, token=None, cafile=None, version=None, namespace="default"):
        '''
        :param depname:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        try:
            resp = cls.describe(depname, url=url, token=token,
                                cafile=cafile, version=version,
                                namespace=namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            logger.info("query deployment %s not found" % (depname))
            return {}

    @classmethod
    def describe(cls, depname, url, token=None, cafile=None, version=None, namespace=None):
        '''

        :param depname:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        return apiclient.read_namespaced_deployment(depname, namespace)

    @classmethod
    def update(cls, depname, updatedata, url,
               token=None, cafile=None, version=None,
               namespace="default"):
        '''

        :param depname:
        :param updatedata:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        updateobject = cls.query(depname, url, token=token, cafile=cafile,
                                 version=version, namespace=namespace)
        if not updateobject:
            raise local_exceptions.ResourceNotFoundError("deployment %s not found" % depname)

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        resp = apiclient.patch_namespaced_deployment(name=depname,
                                                     namespace=namespace,
                                                     body=updateobject)

        return resp.to_dict()

    @classmethod
    def delete(cls, depname, url, token=None, cafile=None, version=None, namespace="default"):
        '''

        :param depname:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        depobject = cls.query(depname, url, token=token,
                              cafile=cafile, version=version,
                              namespace=namespace)
        if not depobject:
            raise local_exceptions.ResourceNotFoundError("deployment %s not found" % depname)

        resp = apiclient.delete_namespaced_deployment(name=depname,
                                                      namespace=namespace)
        return resp.to_dict()


class ServiceManager(object):
    @classmethod
    def client(cls, url, token=None, cafile=None, version=None):
        _client = K8sCoreClient(url=url, token=token, cafile=cafile)
        return _client.client()

    @classmethod
    def list(cls, url, token=None, cafile=None, version=None, namespace=None):

        '''
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        try:
            if namespace:
                resp = apiclient.list_namespaced_service(namespace=namespace)
            else:
                resp = apiclient.list_service_for_all_namespaces()

            _tmp = resp.to_dict().items()
            result = _tmp[0][1]
            return result
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return []

    @classmethod
    def create(cls, uuid, createdata, url,
               token=None, cafile=None,
               version=None, namespace="default"):
        '''

        :param uuid:
        :param createdata:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        if not isinstance(createdata, dict):
            raise ValueError("data must be json")

        filepath = os.path.join(YAML_TMP_PATH, "%s_service.yaml" % uuid)
        dict_to_yamlfile(data=createdata, filepath=filepath)

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        try:
            resp = apiclient.create_namespaced_service(body=createdata, namespace=namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return {}

    @classmethod
    def query(cls, name, url, token=None, cafile=None, version=None, namespace="default"):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        try:
            resp = cls.describe(name, url, token=token, cafile=cafile,
                                version=version, namespace=namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            logger.info("query service %s" % (name))
            return {}

    @classmethod
    def describe(cls, name, url, token=None, cafile=None, version=None, namespace="default"):
        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        return apiclient.read_namespaced_service(name, namespace)

    @classmethod
    def delete(cls, name, url, token=None, cafile=None, version=None, namespace="default"):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''
        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        _obj = cls.query(name, url, token=token,
                         cafile=cafile, version=version,
                         namespace=namespace)

        if not _obj:
            raise local_exceptions.ResourceNotFoundError("service %s not found" % name)

        resp = apiclient.delete_namespaced_service(name=name,
                                                   namespace=namespace)
        return resp.to_dict()


class SecretManager(object):
    @classmethod
    def client(cls, url, token=None, cafile=None, version=None):
        _client = K8sCoreClient(url=url, token=token, cafile=cafile)
        return _client.client()

    @classmethod
    def list(cls, url, token=None, cafile=None, version=None, namespace=None):

        '''
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        try:
            if namespace:
                resp = apiclient.list_namespaced_secret(namespace=namespace)
            else:
                resp = apiclient.list_secret_for_all_namespaces()

            _tmp = resp.to_dict().items()
            result = _tmp[0][1]
            return result
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return []

    @classmethod
    def create(cls, uuid, createdata, url,
               token=None, cafile=None,
               version=None, namespace="default"):
        '''

        :param uuid:
        :param createdata:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''

        if not isinstance(createdata, dict):
            raise ValueError("data must be json")

        filepath = os.path.join(YAML_TMP_PATH, "%s_secret.yaml" % uuid)
        dict_to_yamlfile(data=createdata, filepath=filepath)

        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
        try:
            resp = apiclient.create_namespaced_secret(body=createdata, namespace=namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            return {}

    @classmethod
    def detail(cls, name, url, token=None, cafile=None, version=None, namespace="default"):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''
        try:
            apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
            resp = apiclient.read_namespaced_secret(name, namespace)
            return resp.to_dict()
        except Exception, e:
            return {}

    @classmethod
    def describe(cls, name, url, token=None, cafile=None, version=None, namespace="default"):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''
        try:
            apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)
            resp = apiclient.read_namespaced_secret(name, namespace)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            logger.info("query secret %s" % (name))
            return {}

    @classmethod
    def delete(cls, name, url, token=None, cafile=None, version=None, namespace="default"):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :param version:
        :param namespace:
        :return:
        '''
        apiclient = cls.client(url=url, token=token, cafile=cafile, version=version)

        _obj = cls.describe(name, url, token=token,
                            cafile=cafile, version=version,
                            namespace=namespace)

        if not _obj:
            raise local_exceptions.ResourceNotFoundError("secret %s not found" % name)

        resp = apiclient.delete_namespaced_secret(name=name,
                                                  namespace=namespace)
        return resp.to_dict()


class NodeManager(object):
    @classmethod
    def client(cls, url, token=None, cafile=None, version=None):
        _client = K8sCoreClient(url=url, token=token, cafile=cafile)
        return _client.client()

    @classmethod
    def list(cls, url, token=None, cafile=None, **kwargs):
        '''

        :param url:
        :param token:
        :param cafile:
        :param kwargs:
        :return:
        '''

        client = cls.client(url=url, token=token, cafile=cafile)
        try:
            resp = client.list_node()
            _tmp = resp.to_dict().items()
            result = _tmp[0][1]
            return result
        except Exception, e:
            logger.info(e.message)
            logger.info(traceback.format_exc())
            return []

    @classmethod
    def descibe(cls, name, url, token=None, cafile=None):
        '''

        :param name:
        :param url:
        :param token:
        :param cafile:
        :return:
        '''

        try:
            apiclient = cls.client(url=url, token=token, cafile=cafile)
            resp = apiclient.read_node(name)
            return resp.to_dict()
        except Exception, e:
            logger.info(e)
            logger.info(traceback.format_exc())
            logger.info("query node %s" % (name))
            return {}


class DiskManager(object):
    @classmethod
    def create(cls):
        raise NotImplementedError("not define")

    @classmethod
    def delete(cls):
        raise NotImplementedError("not define")

    @classmethod
    def attach(cls):
        raise NotImplementedError("not define")

    @classmethod
    def detach(cls):
        raise NotImplementedError("not define")


class NameSpaceManager(object):
    @classmethod
    def list(cls):
        raise NotImplementedError("not define")

    @classmethod
    def create(cls):
        raise NotImplementedError("not define")
