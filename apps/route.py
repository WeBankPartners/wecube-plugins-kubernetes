#_ coding:utf-8 _*_

from django.conf.urls import include, url


urlpatterns = [
    url(r'^service/', include('apps.api.service.route', namespace='service')),
    url(r'^deployment/', include('apps.api.deployment.route', namespace='deployment')),
    url(r'^secret/', include('apps.api.secret.route', namespace='secret')),
    url(r'^pod/', include('apps.api.pod.route', namespace='pod')),
    url(r'^rc/', include('apps.api.rc.route', namespace='rc')),
]