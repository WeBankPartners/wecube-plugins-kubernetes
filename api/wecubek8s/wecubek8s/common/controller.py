# coding=utf-8

from __future__ import absolute_import

import logging

import falcon
from talos.common.controller import CollectionController
from talos.common.controller import ItemController
from talos.common.controller import Controller as BaseController
from talos.core import exceptions as base_ex
from talos.core import utils
from talos.core.i18n import _
from talos.db import crud
from talos.db import validator

from wecubek8s.common import exceptions

LOG = logging.getLogger(__name__)


class Controller(BaseController):
    def on_post(self, req, resp, **kwargs):
        self._validate_method(req)
        self._validate_data(req)
        data = req.json
        resp.json = {'code': 200, 'status': 'OK', 'data': self.create(req, data, **kwargs), 'message': 'success'}
        resp.status = falcon.HTTP_200

    def create(self, req, data, **kwargs):
        return self.make_resource(req).create(data, **kwargs)


class Collection(CollectionController):
    def on_get(self, req, resp, **kwargs):
        self._validate_method(req)
        refs = []
        count = 0
        criteria = self._build_criteria(req)
        if criteria:
            refs = self.list(req, criteria, **kwargs)
            count = self.count(req, criteria, results=refs, **kwargs)
        resp.json = {'code': 200, 'status': 'OK', 'data': {'count': count, 'data': refs}, 'message': 'success'}

    def on_post(self, req, resp, **kwargs):
        self._validate_method(req)
        self._validate_data(req)
        datas = req.json
        if not utils.is_list_type(datas):
            raise exceptions.PluginError(_('data must be list type'))
        rets = []
        ex_rets = []
        for idx, data in enumerate(datas):
            try:
                rets.append(self.create(req, data, **kwargs))
            except base_ex.Error as e:
                ex_rets.append({'index': idx + 1, 'message': str(e)})
        if len(ex_rets):
            raise exceptions.BatchPartialError(num=len(ex_rets), action='create', exception_data={'data': ex_rets})
        resp.json = {'code': 200, 'status': 'OK', 'data': rets, 'message': 'success'}
        resp.status = falcon.HTTP_200

    def on_patch(self, req, resp, **kwargs):
        self._validate_method(req)
        self._validate_data(req)
        datas = req.json
        if not utils.is_list_type(datas):
            raise exceptions.PluginError(_('data must be list type'))
        rets = []
        ex_rets = []
        for idx, data in enumerate(datas):
            try:
                res_instance = self.make_resource(req)
                if res_instance.primary_keys not in data:
                    raise exceptions.FieldRequired(attribute=res_instance.primary_keys)
                rid = data.pop(res_instance.primary_keys)
                before_update, after_update = self.update(req, data, rid=rid)
                if after_update is None:
                    raise exceptions.NotFoundError(resource='%s[%s]' % (self.resource.__name__, rid))
                rets.append(after_update)
            except base_ex.Error as e:
                ex_rets.append({'index': idx + 1, 'message': str(e)})
        if len(ex_rets):
            raise exceptions.BatchPartialError(num=len(ex_rets), action='update', exception_data={'data': ex_rets})
        resp.json = {'code': 200, 'status': 'OK', 'data': rets, 'message': 'success'}
        resp.status = falcon.HTTP_200

    def update(self, req, data, **kwargs):
        rid = kwargs.pop('rid')
        return self.make_resource(req).update(rid, data)

    def on_delete(self, req, resp, **kwargs):
        self._validate_method(req)
        self._validate_data(req)
        datas = req.json
        if not utils.is_list_type(datas):
            raise exceptions.PluginError(_('data must be list type'))
        rets = []
        ex_rets = []
        for idx, data in enumerate(datas):
            try:
                res_instance = self.make_resource(req)
                ref_count, ref_details = self.delete(req, rid=data)
                rets.append(ref_details[0])
            except base_ex.Error as e:
                ex_rets.append({'index': idx + 1, 'message': str(e)})
        if len(ex_rets):
            raise exceptions.BatchPartialError(num=len(ex_rets), action='delete', exception_data={'data': ex_rets})
        resp.json = {'code': 200, 'status': 'OK', 'data': rets, 'message': 'success'}
        resp.status = falcon.HTTP_200

    def delete(self, req, **kwargs):
        return self.make_resource(req).delete(**kwargs)


class Item(ItemController):
    def on_get(self, req, resp, **kwargs):
        self._validate_method(req)
        ref = self.get(req, **kwargs)
        if ref is not None:
            resp.json = {'code': 200, 'status': 'OK', 'data': ref, 'message': 'success'}
        else:
            raise exceptions.NotFoundError(resource='%s[%s]' % (self.resource.__name__, kwargs.get('rid', '-')))

    def on_patch(self, req, resp, **kwargs):
        self._validate_method(req)
        self._validate_data(req)
        data = req.json
        if data is not None and not isinstance(data, dict):
            raise exceptions.PluginError(_('data must be dict type'))
        ref_before, ref_after = self.update(req, data, **kwargs)
        if ref_after is not None:
            resp.json = {'code': 200, 'status': 'OK', 'data': ref_after, 'message': 'success'}
        else:
            raise exceptions.NotFoundError(resource='%s[%s]' % (self.resource.__name__, kwargs.get('rid', '-')))

    def on_delete(self, req, resp, **kwargs):
        self._validate_method(req)
        ref, details = self.delete(req, **kwargs)
        if ref:
            resp.json = {'code': 200, 'status': 'OK', 'data': {'count': ref, 'data': details}, 'message': 'success'}
        else:
            raise exceptions.NotFoundError(resource='%s[%s]' % (self.resource.__name__, kwargs.get('rid', '-')))


class Plugin(BaseController):
    allow_methods = ('POST', )
    _param_rules = [
        crud.ColumnValidator(field='requestId',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='operator',
                             rule=validator.LengthValidator(1, 255),
                             validate_on=['check:O'],
                             nullable=True),
        crud.ColumnValidator(field='inputs',
                             rule=validator.TypeValidator(list),
                             validate_on=['check:M'],
                             nullable=False),
    ]

    def __init__(self, action=None) -> None:
        super().__init__()
        self._default_action = action or 'process'

    def on_post(self, req, resp, **kwargs):
        self._validate_method(req)
        self._validate_data(req)
        resp.json = self.process_post(req, req.json, **kwargs)
        resp.status = falcon.HTTP_200

    def validate_item(self, item_index, item):
        # do return crud.ColumnValidator.get_clean_data(rules, item, 'check')
        return item

    def process(self, reqid, operator, item_index, item, **kwargs):
        raise NotImplementedError()

    def process_post(self, req, data, **kwargs):
        result = {'resultCode': '0', 'resultMessage': 'success', 'results': {'outputs': []}}
        is_item_error = False
        error_indexes = []
        try:
            clean_data = crud.ColumnValidator.get_clean_data(self._param_rules, data, 'check')
            reqid = clean_data.get('requestId', None) or 'N/A'
            operator = clean_data.get('operator', None) or 'N/A'
            for idx, item in enumerate(clean_data['inputs']):
                single_result = {
                    'callbackParameter': item.get('callbackParameter', None),
                    'errorCode': '0',
                    'errorMessage': 'success'
                }
                try:
                    validate_item_func = getattr(self, 'validate_item_' + self._default_action, self.validate_item)
                    clean_item = validate_item_func(idx, item)
                    process_func = getattr(self, self._default_action, self.process)
                    process_result = process_func(reqid, operator, idx, clean_item, **kwargs)
                    if process_result:
                        single_result.update(process_result)
                    result['results']['outputs'].append(single_result)
                except Exception as e:
                    LOG.exception(e)
                    single_result['errorCode'] = '1'
                    single_result['errorMessage'] = str(e)
                    result['results']['outputs'].append(single_result)
                    is_item_error = True
                    error_indexes.append(str(idx + 1))
        except Exception as e:
            LOG.exception(e)
            result['resultCode'] = '1'
            result['resultMessage'] = str(e)
        if is_item_error:
            result['resultCode'] = '1'
            result['resultMessage'] = _('Fail to process [%(num)s] record, detail error in the data block') % dict(
                num=','.join(error_indexes))
        return result