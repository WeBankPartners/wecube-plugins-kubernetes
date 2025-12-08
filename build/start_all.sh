#!/bin/sh
# 设置环境变量强制限制 gevent threadpool
export GEVENT_THREADPOOL=10
# 使用 thread 解析器（稳定可靠）
export GEVENT_RESOLVER=thread

# log rotate
nohup wecubek8s_scheduler > /dev/null 2>&1 &
nohup wecubek8s_watcher > /dev/null 2>&1 &

# wsgi api server
echo "[START] Starting gunicorn with gevent threadpool limit and thread resolver..." >&2
/usr/local/bin/gunicorn --config /etc/wecubek8s/gunicorn.py wecubek8s.server.wsgi_server:application
