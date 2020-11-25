# _ coding:utf-8 _*_

from django.conf.urls import include, url
# from .Secret_controller import SecretController
# from .Secret_controller import SecretIdController
from .Secret_controller import SecretListController
from .Secret_controller import SecretAddController
from .Secret_controller import SecretIdController
from .Secret_controller import SecretDeleteController

urlpatterns = [
    url(r'^add$', SecretAddController()),
    url(r'^list$', SecretListController()),
    url(r'^describe$', SecretIdController()),
    url(r'^delete$', SecretDeleteController()),
]
