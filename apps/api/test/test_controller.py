# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

from core.controller import BaseController


class TestController(BaseController):
    name = "test"
    resource_describe = "测试示例"
    allow_methods = ('GET', "POST")
    resource = None

    def list(self, request, data, **kwargs):
        return 0, []

    def create(self, request, data, **kwargs):
        return 1, "qe7638736718321"



class TestIdController(BaseController):
    name = "test.id"
    resource_describe = "测试示例"
    allow_methods = ('GET', "PATCH", 'DELETE')
    resource = None

    def show(self, request, data, **kwargs):
        return {}

    def update(self, request, data, **kwargs):
        return 1, {}

    def delete(self, request, data, **kwargs):
        return 1