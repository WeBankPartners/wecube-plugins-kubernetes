# _ coding:utf-8 _*_

from django.conf.urls import include, url
from .service_controller import ServiceListController
from .service_controller import ServiceAddController
from .service_controller import ServiceIdController
from .service_controller import ServiceDelIdController

urlpatterns = [
    # url(r'^$', ServiceController(), name='Service'),
    # url(r'^(?P<name>[\w-]+)$', ServiceIdController(), name='Service.id'),

    url(r'^add$', ServiceAddController()),
    url(r'^list$', ServiceListController()),
    url(r'^describe$', ServiceIdController()),
    # url(r'^update$', ServiceUpdateController()),
    url(r'^delete$', ServiceDelIdController()),
]
