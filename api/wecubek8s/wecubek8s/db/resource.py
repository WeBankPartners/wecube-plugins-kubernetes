# coding=utf-8

from __future__ import absolute_import
import datetime

from talos.core.i18n import _
from talos.db import crud
from talos.db import validator
from talos.utils import scoped_globals

from wecubek8s.common import exceptions
from wecubek8s.db import models
from wecubek8s.db import validator as my_validator


class MetaCRUD(crud.ResourceBase):
    def _before_create(self, resource, validate):
        resource['created_by'] = scoped_globals.GLOBALS.request.auth_user or None
        resource['created_time'] = datetime.datetime.now()

    def _before_update(self, rid, resource, validate):
        resource['updated_by'] = scoped_globals.GLOBALS.request.auth_user or None
        resource['updated_time'] = datetime.datetime.now()


