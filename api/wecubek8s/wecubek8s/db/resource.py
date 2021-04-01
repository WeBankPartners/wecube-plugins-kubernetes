# coding=utf-8

from __future__ import absolute_import
import datetime

from talos.core.i18n import _
from talos.core import utils
from talos.db import crud
from talos.utils import scoped_globals

from wecubek8s.db import models


class MetaCRUD(crud.ResourceBase):
    _id_prefix = ''

    def _before_create(self, resource, validate):
        resource['id'] = utils.generate_prefix_uuid(self._id_prefix)
        resource['created_by'] = scoped_globals.GLOBALS.request.auth_user or None
        resource['created_time'] = datetime.datetime.now()

    def _before_update(self, rid, resource, validate):
        resource['updated_by'] = scoped_globals.GLOBALS.request.auth_user or None
        resource['updated_time'] = datetime.datetime.now()


class Cluster(MetaCRUD):
    # TODO: encrypt token
    orm_meta = models.Cluster
    _primary_keys = 'id'
    _default_order = ['-created_time']
    _id_prefix = 'cluster-'
