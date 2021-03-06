# coding=utf-8
"""
wecubek8s.common.wecmdb
~~~~~~~~~~~~~~~~~~~~~~

本模块提供项目WeCMDB Client

"""
import logging

from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import exceptions
from wecubek8s.common import utils

LOG = logging.getLogger(__name__)
CONF = config.CONF


class EntityClient(utils.ClientMixin):
    def __init__(self, server, token=None):
        self.server = server.rstrip('/')
        self.token = token or utils.get_token()

    @staticmethod
    def build_query_url(package, entity):
        return '/%s/entities/%s/query' % (package, entity)

    def retrieve(self, package, entity, query):
        url = self.server + self.build_query_url(package, entity)
        return self.post(url, query)


class WeCMDBClient(utils.ClientMixin):
    """WeCMDB Client"""
    def __init__(self, server, token=None):
        self.server = server.rstrip('/')
        self.token = token or utils.get_token()

    @staticmethod
    def build_retrieve_url(citype):
        return '/wecmdb/api/v2/ci/%s/retrieve' % citype

    @staticmethod
    def build_create_url(citype):
        return '/wecmdb/api/v2/ci/%s/create' % citype

    @staticmethod
    def build_update_url(citype):
        return '/wecmdb/api/v2/ci/%s/update' % citype

    @staticmethod
    def build_delete_url(citype):
        return '/wecmdb/api/v2/ci/%s/delete' % citype

    @staticmethod
    def build_version_tree_url(citype_from, citype_to, version):
        return '/wecmdb/api/v2/ci/from/%s/to/%s/versions/%s/retrieve' % (citype_from, citype_to, version)

    @staticmethod
    def build_connector_url():
        return '/wecmdb/api/v2/static-data/special-connector'

    @staticmethod
    def build_citype_url():
        return '/wecmdb/api/v2/ciTypes/retrieve'

    @staticmethod
    def build_citype_attrs_url():
        return '/wecmdb/api/v2/ciTypeAttrs/retrieve'

    @staticmethod
    def build_state_operation_url():
        return '/wecmdb/api/v2/ci/state/operate'

    @staticmethod
    def build_enumcode_url():
        return '/wecmdb/api/v2/enum/codes/retrieve'

    def check_response(self, resp_json):
        if resp_json['statusCode'] != 'OK':
            # 当创建/更新条目错误，且仅有一个错误时，返回内部错误信息
            if isinstance(resp_json.get('data', None), list) and len(resp_json['data']) == 1:
                if 'errorMessage' in resp_json['data'][0]:
                    raise exceptions.PluginError(message=resp_json['data'][0]['errorMessage'])
            raise exceptions.PluginError(message=resp_json['statusMessage'])

    def special_connector(self):
        url = self.server + self.build_connector_url()
        return self.get(url)

    def citypes(self, data):
        url = self.server + self.build_citype_url()
        return self.post(url, data)

    def citype_attrs(self, data):
        url = self.server + self.build_citype_attrs_url()
        return self.post(url, data)

    def state_operation(self, operation, data):
        url = self.server + self.build_state_operation_url()
        return self.post(url, data, param={'operation': operation})

    def enumcodes(self, data):
        url = self.server + self.build_enumcode_url()
        return self.post(url, data)

    def version_tree(self, citype_from, citype_to, version, query):
        url = self.server + self.build_version_tree_url(citype_from, citype_to, version)
        return self.post(url, query)

    def create(self, citype, data):
        url = self.server + self.build_create_url(citype)
        return self.post(url, data)

    def update(self, citype, data):
        url = self.server + self.build_update_url(citype)
        return self.post(url, data)

    def retrieve(self, citype, query):
        url = self.server + self.build_retrieve_url(citype)
        return self.post(url, query)

    def delete(self, citype, data):
        url = self.server + self.build_delete_url(citype)
        return self.post(url, data)
