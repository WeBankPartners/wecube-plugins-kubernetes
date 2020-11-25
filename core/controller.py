# _*_ coding:utf-8 _*_


from __future__ import (absolute_import, division, print_function, unicode_literals)

from .response_hooks import ResponseController


class BaseController(ResponseController):
    name = None
    resource = None
    allow_methods = ('GET', 'POST', 'PATCH', 'DELETE')

    def __call__(self, request, **kwargs):
        return self.request_response(request=request, **kwargs)

