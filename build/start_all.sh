#!/bin/sh
# log rotate
nohup wecubek8s_scheduler > /dev/null 2>&1 &
# wsgi api server
/usr/local/bin/gunicorn --config /etc/wecubek8s/gunicorn.py wecubek8s.server.wsgi_server:application
