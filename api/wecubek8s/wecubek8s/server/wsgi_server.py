# coding=utf-8
"""
wecubek8s.server.wsgi_server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

本模块提供wsgi启动能力

"""

from __future__ import absolute_import

import os
import json
from talos.server import base
from talos.core import utils
from talos.middlewares import lazy_init
from talos.middlewares import json_translator
from talos.middlewares import limiter
from talos.middlewares import globalvars

from wecubek8s.middlewares import auth
from wecubek8s.middlewares import permission
from wecubek8s.middlewares import language
from wecubek8s.server import base as wecubek8s_base


def error_serializer(req, resp, exception):
    representation = exception.to_dict()
    # replace code with internal application code
    if 'error_code' in representation:
        representation['code'] = representation.pop('error_code')
    representation['status'] = 'ERROR'
    representation['data'] = representation.get('data', None)
    representation['message'] = representation.pop('description', '')
    resp.body = json.dumps(representation, cls=utils.ComplexEncoder)
    resp.content_type = 'application/json'


application = base.initialize_server('wecubek8s',
                                     os.environ.get('WECUBEK8S_CONF', '/etc/wecubek8s/wecubek8s.conf'),
                                     conf_dir=os.environ.get('WECUBEK8S_CONF_DIR', '/etc/wecubek8s/wecubek8s.conf.d'),
                                     middlewares=[
                                         language.Language(),
                                         globalvars.GlobalVars(),
                                         json_translator.JSONTranslator(),
                                         lazy_init.LazyInit(limiter.Limiter),
                                         auth.JWTAuth(),
                                         permission.Permission()
                                     ],
                                     override_middlewares=True)
application.set_error_serializer(error_serializer)
application.req_options.auto_parse_qs_csv = True
