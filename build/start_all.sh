#!/bin/sh
# 设置环境变量强制限制 gevent threadpool
export GEVENT_THREADPOOL=10
# 使用 thread 解析器（稳定可靠）
export GEVENT_RESOLVER=thread

# 创建日志目录
mkdir -p /var/log/wecubek8s

# 启动 scheduler 和 watcher（输出到日志文件）
echo "[START] Starting wecubek8s_scheduler..." >&2
nohup wecubek8s_scheduler >> /var/log/wecubek8s/scheduler.log 2>&1 &

echo "[START] Starting wecubek8s_watcher..." >&2
nohup wecubek8s_watcher >> /var/log/wecubek8s/watcher.log 2>&1 &

# wsgi api server
echo "[START] Starting gunicorn with gevent threadpool limit and thread resolver..." >&2
/usr/local/bin/gunicorn --config /etc/wecubek8s/gunicorn.py wecubek8s.server.wsgi_server:application
