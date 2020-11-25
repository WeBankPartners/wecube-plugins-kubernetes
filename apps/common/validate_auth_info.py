# _ coding:utf-8 _*_

from __future__ import (absolute_import, division, print_function, unicode_literals)

from core.local_exceptions import RequestValidateError
from core.local_exceptions import ValueValidateError


def validate_cluster_auth(data):
    if not data.get("kubernetes_url"):
        raise RequestValidateError(msg="缺少集群认证信息")


def validate_cluster_info(kubernetes_url):
    if not kubernetes_url.startswith("http"):
        raise ValueValidateError(param="kubernetes_url",
                                 msg="认证url格式为http/https, 不正确的url: %s" % kubernetes_url)
