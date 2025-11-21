# coding=utf-8

from __future__ import absolute_import

import os
import logging
from logging.handlers import WatchedFileHandler
import multiprocessing

from talos.core import config as __config

__config.setup(os.environ.get('WECUBEK8S_CONF', '/etc/wecubek8s/wecubek8s.conf'),
               dir_path=os.environ.get('WECUBEK8S_CONF_DIR', '/etc/wecubek8s/wecubek8s.conf.d'))
CONF = __config.CONF

name = CONF.locale_app
proc_name = CONF.locale_app
bind = '%s:%d' % (CONF.server.bind, CONF.server.port)
backlog = CONF.server.backlog
# 超时
timeout = 30
# 进程数 (优化：避免创建过多worker导致线程耗尽)
# 对于I/O密集型应用 + gevent异步模型，不需要太多worker
# 由于 gevent threadpool 限制，进一步减少 workers
workers = 2
# 指定每个进程开启的线程数
threads = 1
debug = False
daemon = False
# 日志级别，这个日志级别指的是错误日志的级别，而访问日志的级别无法设置
loglevel = CONF.log.level.lower()
# 访问日志文件的路径
accesslog = "/dev/null"
# 错误日志文件的路径
errorlog = "/dev/null"
acclog = logging.getLogger('gunicorn.access')
acclog.addHandler(WatchedFileHandler(CONF.log.gunicorn_access))
acclog.propagate = False
errlog = logging.getLogger('gunicorn.error')
errlog.addHandler(WatchedFileHandler(CONF.log.gunicorn_error))
errlog.propagate = False

# keyfile =
# certfile =
# ca_certs =
# chdir = '/home/user'
# sync/gevent/eventlet/tornado/gthread/gaiohttp
worker_class = 'gevent'
worker_connections = 20

# 配置 gevent 行为（解决 DNS 解析线程池耗尽问题）
def post_fork(server, worker):
    """在 worker 启动后执行的钩子"""
    from gevent import monkey
    # 确保 monkey patch 已应用
    monkey.patch_all()
    
    # 限制 gevent threadpool 的大小（默认是 10，可能会被无限创建）
    import gevent.threadpool
    # 为 DNS 解析器设置最大线程数
    gevent.get_hub().threadpool = gevent.threadpool.ThreadPool(maxsize=5)
# 到达max requests之后worker会重启
# max_requests = 0
# keepalive = 5
# reload = True
# %(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"
# access_log_format = CONF.log.format_string
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(L)s %(b)s "%(f)s" "%(a)s"'
# syslog_addr = udp://localhost:514
# HTTP URL长度限制
# limit_request_line = 4094
