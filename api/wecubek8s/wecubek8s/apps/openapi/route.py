# coding=utf-8

from __future__ import absolute_import

from wecubek8s.apps.openapi import controller


def add_routes(api):
    api.add_route('/wecubek8s/apispec', controller.Apispec())
    api.add_route('/wecubek8s/redoc', controller.Redoc())
    api.add_route('/wecubek8s/swagger', controller.Swagger())
