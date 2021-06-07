# coding=utf-8

from __future__ import absolute_import
import datetime

from talos.core.i18n import _
from talos.core import utils
from talos.core import config
from talos.db import crud
from talos.utils import scoped_globals

from wecubek8s.db import models
from wecubek8s.common import utils as k8s_utils

CONF = config.CONF


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

    def _before_create(self, resource, validate):
        super()._before_create(resource, validate)
        for field in self._encrypted_fields:
            resource[field] = k8s_utils.platform_encrypt(resource[field], resource['id'], CONF.platform_encrypt_seed)

    def _before_update(self, rid, resource, validate):
        super()._before_update(rid, resource, validate)
        for field in self._encrypted_fields:
            if field in resource:
                resource[field] = k8s_utils.platform_encrypt(resource[field], resource['id'],
                                                             CONF.platform_encrypt_seed)

    def list(self, filters=None, orders=None, offset=None, limit=None, hooks=None):
        refs = super().list(filters=filters, orders=orders, offset=offset, limit=limit, hooks=hooks)
        for ref in refs:
            for field in self._encrypted_fields:
                ref[field] = k8s_utils.platform_decrypt(ref[field], ref['id'], CONF.platform_encrypt_seed)
        return refs

    def get(self, rid):
        ref = super().get(rid)
        for field in self._encrypted_fields:
            ref[field] = k8s_utils.platform_decrypt(ref[field], ref['id'], CONF.platform_encrypt_seed)
        return ref
