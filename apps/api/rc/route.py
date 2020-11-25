# _ coding:utf-8 _*_

from django.conf.urls import include, url
# from .rc_controller import RCController
# from .rc_controller import RCIdController
from .rc_controller import RCListController
from .rc_controller import RCAddController
from .rc_controller import RCCreateController
from .rc_controller import RCIdController
from .rc_controller import RCUpdateController
from .rc_controller import RCDeleteController

urlpatterns = [
    # url(r'^$', RCController(), name='rc'),
    # url(r'^(?P<name>[\w-]+)$', RCIdController(), name='rc.id'),

    url(r'^add$', RCAddController()),
    url(r'^create$', RCCreateController()),
    url(r'^list$', RCListController()),
    url(r'^describe$', RCIdController()),
    url(r'^update$', RCUpdateController()),
    url(r'^delete$', RCDeleteController()),
]
