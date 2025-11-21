# coding=utf-8

from __future__ import absolute_import

import os
import logging
from logging.handlers import WatchedFileHandler

from talos.core import config as __config

__config.setup(os.environ.get('WECUBEK8S_CONF', '/etc/wecubek8s/wecubek8s.conf'),
               dir_path=os.environ.get('WECUBEK8S_CONF_DIR', '/etc/wecubek8s/wecubek8s.conf.d'))
CONF = __config.CONF

name = CONF.locale_app
proc_name = CONF.locale_app
bind = '%s:%d' % (CONF.server.bind, CONF.server.port)
backlog = CONF.server.backlog
# 超时（增加以避免长时间操作被中断）
timeout = 60
# 进程数（单个 worker + gevent 异步可处理大量并发）
workers = 1
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
# worker 类型：gevent 异步模型
worker_class = 'gevent'
# 每个 worker 的并发连接数（单 worker 配置较大值以提高并发能力）
worker_connections = 50

# 在 master 进程启动时配置 gevent（最早的配置点）
def on_starting(server):
    """在 gunicorn master 进程启动时执行，配置全局 gevent 行为"""
    import logging
    log = logging.getLogger('gunicorn.error')
    log.info('Configuring gevent threadpool before any workers start...')
    
    # 导入并配置 gevent
    import gevent.monkey
    gevent.monkey.patch_all()
    
    import gevent
    # 设置全局 threadpool 大小限制（防止线程耗尽）
    gevent.config.threadpool_size = 5
    log.info('Global gevent threadpool size limited to 5')

# 在每个 worker 进程启动后再次确保配置生效
def post_fork(server, worker):
    """在 worker 进程启动后执行，为该 worker 设置 threadpool 限制"""
    import logging
    log = logging.getLogger('gunicorn.error')
    
    import gevent
    import gevent.threadpool
    
    # 为该 worker 设置 threadpool（双重保险）
    hub = gevent.get_hub()
    hub.threadpool = gevent.threadpool.ThreadPool(maxsize=5)
    
    log.info('Worker %s: gevent threadpool limited to 5 threads', worker.pid)
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
