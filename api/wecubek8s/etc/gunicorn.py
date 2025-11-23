# coding=utf-8

from __future__ import absolute_import

# ============================================================
# 关键修复：在最开始就配置 gevent，防止线程耗尽
# ============================================================
import sys
import os

# 强制使用 ares 或 dnspython 解析器，避免使用线程池解析 DNS
os.environ['GEVENT_RESOLVER'] = 'ares'

import gevent.monkey
gevent.monkey.patch_all()

import gevent
import gevent.threadpool

# 限制 threadpool 大小（多次设置确保生效）
gevent.config.threadpool_size = 10
gevent.config.threadpool_idle = 2

# 立即初始化 hub 并设置 threadpool
try:
    _hub = gevent.get_hub()
    _hub.threadpool = gevent.threadpool.ThreadPool(maxsize=10)
    print(f"[INIT] Gevent threadpool configured: maxsize=10", file=sys.stderr, flush=True)
    print(f"[INIT] Gevent resolver: {os.environ.get('GEVENT_RESOLVER', 'thread')}", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[INIT] Failed to configure threadpool: {e}", file=sys.stderr, flush=True)

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
worker_connections = 20

# 在每个 worker 进程启动后确认 threadpool 配置
def post_fork(server, worker):
    """在 worker 进程启动后执行，为该 worker 设置 threadpool 限制"""
    import sys
    import logging
    import gevent
    import gevent.threadpool
    
    log = logging.getLogger('gunicorn.error')
    
    # 打印到 stderr 确保能看到
    print(f"[POST_FORK] Worker {worker.pid} starting, configuring gevent threadpool...", file=sys.stderr, flush=True)
    log.info('Worker %s starting, configuring gevent threadpool...', worker.pid)
    
    # 为该 worker 设置 threadpool（强制设置）
    try:
        hub = gevent.get_hub()
        # 强制替换 threadpool
        hub.threadpool = gevent.threadpool.ThreadPool(maxsize=10)
        print(f"[POST_FORK] Worker {worker.pid}: gevent threadpool configured with maxsize=10", file=sys.stderr, flush=True)
        log.info('Worker %s: gevent threadpool configured with maxsize=10', worker.pid)
    except Exception as e:
        print(f"[POST_FORK] Worker {worker.pid}: Failed to configure threadpool: {e}", file=sys.stderr, flush=True)
        log.error('Worker %s: Failed to configure threadpool: %s', worker.pid, e)
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
