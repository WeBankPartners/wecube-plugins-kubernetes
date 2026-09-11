# coding=utf-8

from __future__ import absolute_import
import datetime
import logging

from talos.core.i18n import _
from talos.core import utils
from talos.core import config
from talos.db import crud
from talos.utils import scoped_globals

from wecubek8s.db import models
from wecubek8s.common import utils as k8s_utils

CONF = config.CONF
LOG = logging.getLogger(__name__)


class MetaCRUD(crud.ResourceBase):
    _id_prefix = ''

    def _before_create(self, resource, validate):
        if 'id' not in resource:
            resource['id'] = utils.generate_prefix_uuid(self._id_prefix)
        resource['created_by'] = scoped_globals.GLOBALS.request.auth_user or None
        resource['created_time'] = datetime.datetime.now()

    def _before_update(self, rid, resource, validate):
        resource['updated_by'] = scoped_globals.GLOBALS.request.auth_user or None
        resource['updated_time'] = datetime.datetime.now()


class Cluster(MetaCRUD):
    orm_meta = models.Cluster
    _primary_keys = 'id'
    _default_order = ['-created_time']
    _id_prefix = 'cluster-'
    _encrypted_fields = ['token']
    
    def _try_decrypt_with_fallback(self, encrypted_value, ref):
        """
        尝试用多个可能的 guid 解密数据
        1. 首先尝试用正确的 cluster['id']
        2. 如果失败，尝试用 correlation_id（可能是旧数据）
        3. 如果还失败，返回 None 表示需要重新输入
        """
        # 尝试 1: 用正确的 cluster['id']
        try:
            return k8s_utils.platform_decrypt(encrypted_value, ref['id'], CONF.platform_encrypt_seed)
        except Exception as e:
            LOG.warning('Failed to decrypt with cluster id %s: %s', ref.get('id'), str(e))
        
        # 尝试 2: 用 correlation_id（可能是旧数据用这个加密的）
        if 'correlation_id' in ref and ref['correlation_id']:
            try:
                LOG.info('Trying to decrypt with correlation_id: %s', ref['correlation_id'])
                return k8s_utils.platform_decrypt(encrypted_value, ref['correlation_id'], CONF.platform_encrypt_seed)
            except Exception as e:
                LOG.warning('Failed to decrypt with correlation_id %s: %s', ref.get('correlation_id'), str(e))
        
        # 都失败了，返回 None
        LOG.error('Failed to decrypt field for cluster %s with all possible guids. Data needs to be re-entered.', 
                 ref.get('id'))
        return None

    def _before_create(self, resource, validate):
        super()._before_create(resource, validate)
        for field in self._encrypted_fields:
            LOG.info('Encrypting field %s for new cluster with guid: %s', field, resource.get('id'))
            resource[field] = k8s_utils.platform_encrypt(resource[field], resource['id'], CONF.platform_encrypt_seed)
            LOG.info('Successfully encrypted field %s', field)

    def _before_update(self, rid, resource, validate):
        super()._before_update(rid, resource, validate)
        for field in self._encrypted_fields:
            if field in resource:
                LOG.info('Encrypting field %s for cluster %s with guid: %s', field, rid, resource.get('id'))
                resource[field] = k8s_utils.platform_encrypt(resource[field], resource['id'],
                                                             CONF.platform_encrypt_seed)
                LOG.info('Successfully encrypted field %s', field)

    def list(self, filters=None, orders=None, offset=None, limit=None, hooks=None):
        refs = super().list(filters=filters, orders=orders, offset=offset, limit=limit, hooks=hooks)
        for ref in refs:
            for field in self._encrypted_fields:
                if field in ref and ref[field]:
                    decrypted_value = self._try_decrypt_with_fallback(ref[field], ref)
                    if decrypted_value is not None:
                        ref[field] = decrypted_value
                    else:
                        # 解密失败，设置为空字符串，要求用户重新输入
                        LOG.error('Cannot decrypt %s for cluster %s, setting to empty. Please re-enter the value.', 
                                 field, ref.get('id'))
                        ref[field] = ''
        return refs

    def get(self, rid):
        ref = super().get(rid)
        for field in self._encrypted_fields:
            if field in ref and ref[field]:
                decrypted_value = self._try_decrypt_with_fallback(ref[field], ref)
                if decrypted_value is not None:
                    ref[field] = decrypted_value
                else:
                    # 解密失败，设置为空字符串，要求用户重新输入
                    LOG.error('Cannot decrypt %s for cluster %s, setting to empty. Please re-enter the value.', 
                             field, ref.get('id'))
                    ref[field] = ''
        return ref
