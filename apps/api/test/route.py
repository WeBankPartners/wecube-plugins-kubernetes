# _ coding:utf-8 _*_

from django.conf.urls import include, url
from test_controller import TestController, TestIdController


urlpatterns = [
    url(r'^test$', TestController(), name='test.mananger'),
    url(r'^test/(?P<rid>[\w-]+)$', TestIdController(), name='test.id.mananger')
]
