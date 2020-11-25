# _ coding:utf-8 _*_

from django.conf.urls import include, url
# from .Deployment_controller import DeploymentController
# from .Deployment_controller import DeploymentIdController
from .deployment_controller import DeploymentListController
from .deployment_controller import DeploymentAddController
from .deployment_controller import DeploymentIdController
from .deployment_controller import DeploymentUpdateIdController
from .deployment_controller import DeploymentDeleteIdController

urlpatterns = [
    # url(r'^$', DeploymentController(), name='Deployment'),
    # url(r'^(?P<name>[\w-]+)$', DeploymentIdController(), name='Deployment.id'),

    url(r'^add$', DeploymentAddController()),
    url(r'^list$', DeploymentListController()),
    url(r'^describe$', DeploymentIdController()),
    url(r'^update$', DeploymentUpdateIdController()),
    url(r'^delete$', DeploymentDeleteIdController()),
]