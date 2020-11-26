# _*_ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

import json
import traceback
from django.http import HttpResponse
from django.http import HttpResponseNotAllowed
from core import local_exceptions as exception_common
from core.validation import validate_column_line
from core.validation import validate_resource_id
from lib.classtools import get_all_class_for_module
from lib.json_helper import format_json_dumps
from lib.logs import logger
from lib.uuid_util import get_uuid

content_type = 'application/json,charset=utf-8'
exception_common_classes = get_all_class_for_module(exception_common)


def format_string(data):
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = format_json_dumps(value)
        else:
            result[key] = str(value)

    return result


def format_response(count, msg):
    if isinstance(msg, list):
        result = []
        for res in msg:
            _res = {"errorCode": 0, "errorMessage": ""}
            _res.update(res)
            result.append(format_string(_res))
    else:
        _res = {"errorCode": 0, "errorMessage": ""}
        _res.update(msg)
        result = [format_string(_res)]

    return format_json_dumps({"resultCode": 0,
                              "resultMessage": "success",
                              "results": {
                                  "outputs": result
                              }})


class HooksHanderBase(object):
    resource = None

    def run_get(self, request, **kwargs):
        data = request.GET
        data = data.dict()
        if len(request.META.get("QUERY_STRING", "")) > 2048:
            raise exception_common.DataToolangError(msg="请求URL过长")
        count, res = self.list(request, data, **kwargs)
        return format_response(count, res)

    def run_id_get(self, request, **kwargs):
        data = request.GET
        data = data.dict()
        if len(request.META.get("QUERY_STRING", "")) > 2048:
            raise exception_common.DataToolangError(msg="请求URL过长")
        rid = kwargs.get("rid", "")
        if rid:
            validate_resource_id(rid)
        res = self.show(request, data, **kwargs)
        if not res:
            raise exception_common.ResourceNotFoundError()
        return format_response(1, res)

    def run_post(self, request, **kwargs):
        data = request.body
        try:
            data = json.loads(data)
        except:
            raise exception_common.RequestValidateError("请求参数不为json")
        if isinstance(data, list):
            for item in data:
                for cid, value in item.items():
                    validate_column_line(cid)
        elif isinstance(data, dict):
            for cid, value in data.items():
                validate_column_line(cid)
        else:
            raise exception_common.RequestValidateError("未知请求数据类型")

        count, res = self.create(request, data, **kwargs)
        return format_response(count, res)

    def run_delete(self, request, **kwargs):
        data = request.GET
        data = data.dict()
        rid = kwargs.get("rid", "")
        if rid:
            validate_resource_id(rid)
        count, res = self.delete(request, data, **kwargs)
        if not res:
            raise exception_common.ResourceNotFoundError()
        return format_response(count, res)

    def run_patch(self, request, **kwargs):
        data = request.body
        try:
            data = json.loads(data)
        except:
            raise exception_common.RequestValidateError("请求参数不为json")
        rid = kwargs.get("rid", "")
        if rid:
            validate_resource_id(rid)
        for cid, value in data.items():
            validate_column_line(cid)
        count, res = self.update(request, data, **kwargs)
        if not res:
            raise exception_common.ResourceNotFoundError()

        return format_response(count, res)

    def list(self, request, data, **kwargs):
        return self.resource.list(filter=data, **kwargs)

    def show(self, request, data, **kwargs):
        rid = kwargs.pop("rid", None)
        return self.resource.show(rid)

    def create(self, request, data, **kwargs):
        return self.resource.create(data)

    def delete(self, request, data, **kwargs):
        rid = kwargs.pop("rid", None)
        return self.resource.delete(rid, where_and=data)

    def update(self, request, data, **kwargs):
        rid = kwargs.pop("rid", None)
        return self.resource.update(rid, data, where_and=kwargs)


class ReqHanderBase(HooksHanderBase):
    resource = None

    def handler_http(self, request, **kwargs):
        method = request.method.upper()
        if method == "GET":
            return self.run_get(request, **kwargs)
        elif method == "POST":
            return self.run_post(request, **kwargs)
        elif method == "DELETE":
            return self.run_delete(request, **kwargs)
        elif method == "PATCH":
            return self.run_patch(request, **kwargs)
        else:
            raise exception_common.HttpMethodsNotAllowed("(GET,POST, PATCH,DELETE)")


class ResponseBase(object):
    name = None
    allow_methods = tuple()
    requestId = ""

    def auth_method(self, request):
        method = request.method.upper()
        if method in self.allow_methods:
            return True
        else:
            return False

    def format_err(self, errcode, errtype, errinfo, return_data=None):
        if isinstance(errinfo, Exception):
            errorMessage = "type: %s, info: %s" % (errtype, errinfo.message)
        else:
            errorMessage = "type: %s, info: %s" % (errtype, errinfo)

        return_data = return_data or {"errorCode": errcode, "errorMessage": errorMessage}
        msg = {"resultCode": errcode,
               "resultMessage": errorMessage,
               "results": {
                   "outputs": [
                       return_data
                   ]
               }}

        return json.dumps(msg, ensure_ascii=False)

    def _trace_req(self, request):
        try:
            data = request.body if request.method.upper() in ['POST', 'PATCH'] else request.GET
            if isinstance(data, (dict, list)):
                data = format_json_dumps(data)
            logger.info("[%s] [RE] - %s %s %s " % (self.requestId, request.method.upper(), request.path, data))
        except:
            logger.info(traceback.format_exc())

    def trace_log(self, request, msg):
        try:
            if isinstance(msg, (dict, list)):
                msg = format_json_dumps(msg)

            logger.info("[%s] [RP] - %s %s %s" % (self.requestId, request.method.upper(), request.path, msg))
        except:
            logger.info(traceback.format_exc())

    def request_response(self, request, **kwargs):
        method = request.method
        if method == "OPTIONS":
            return HttpResponse(str(self.allow_methods))
        else:
            if self.auth_method(request):
                self.requestId = "req_%s" % get_uuid()
                self._trace_req(request)
                res = self._request_response(request, method, **kwargs)
                res.setdefault("ReqID", self.requestId)
                try:
                    _traceres = res.content.decode("utf-8")
                except:
                    _traceres = res.content
                self.trace_log(request, msg=(str(res.status_code) + " data: %s " % _traceres))
                return res
            else:
                errmsg = self.format_err(405, "HttpMethodsNotAllowed", self.allow_methods)
                return HttpResponseNotAllowed(self.allow_methods, content=errmsg, content_type=content_type)

    def _request_response(self, request, method, **kwargs):
        pass

    def exception_response(self, e):
        if e.__class__.__name__ in ['UnicodeDecodeError']:
            status_code = 400
            errmsg = self.format_err(400, "DataError", "字符错误， 原因：请使用UTF-8编码")
            response_res = HttpResponse(status=status_code, content=errmsg, content_type=content_type)
        elif e.__class__.__name__ in ['ValueError', 'TypeError', "KeyError"]:
            status_code = 400
            errmsg = self.format_err(400, "ValueError", "字符错误， 原因：%s" % e.message)
            response_res = HttpResponse(status=status_code, content=errmsg, content_type=content_type)
        elif e.__class__.__name__ in ['ResourceNotCompleteError', "ResourceNotSearchError"]:
            errmsg = self.format_err(e.status_code, e.__class__.__name__, e.message, return_data=e.return_data)
            response_res = HttpResponse(status=e.status_code, content=errmsg, content_type=content_type)
        elif e.__class__.__name__ in ['AuthFailedError']:
            status_code = 401
            errmsg = self.format_err(401, "UserAuthError", e)
            response_res = HttpResponse(status=status_code, content=errmsg, content_type=content_type)
        elif e.__class__.__name__ in ['AllowedForbidden', 'RequestDataTooBig', 'DataToolangError']:
            status_code = 403
            errmsg = self.format_err(403, "AccessNotAllowed", e)
            response_res = HttpResponse(status=status_code, content=errmsg, content_type=content_type)
        elif e.__class__.__name__ in ['ResourceNotFoundError']:
            status_code = 404
            errmsg = self.format_err(status_code, "ResourceNotFoundError", "ResourceNotFoundError")
            response_res = HttpResponse(status=status_code, content=errmsg, content_type=content_type)
        elif e.__class__.__name__ in exception_common_classes:
            errmsg = self.format_err(e.status_code, e.__class__.__name__, e)
            response_res = HttpResponse(status=e.status_code, content=errmsg, content_type=content_type)
        else:
            status_code = 500
            errmsg = self.format_err(status_code, "SericeError", "服务器遇到异常")
            response_res = HttpResponse(status=status_code, content=errmsg, content_type=content_type)
        return response_res


class ResponseController(ResponseBase, ReqHanderBase):
    def _request_response(self, request, method, **kwargs):
        try:
            msg = self.handler_http(request=request, **kwargs)
            res = HttpResponse(content=msg, status=200, content_type=content_type)
        except Exception, e:
            logger.info(traceback.format_exc())
            logger.info(e.message)
            res = self.exception_response(e)
        return res
