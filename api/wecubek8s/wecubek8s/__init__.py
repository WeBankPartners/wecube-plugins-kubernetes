# coding=utf-8

from __future__ import absolute_import

# 在导入任何其他模块之前配置 gevent
import sys
import os

# 使用 thread 解析器（稳定可靠）
os.environ.setdefault('GEVENT_RESOLVER', 'thread')

import gevent.monkey
gevent.monkey.patch_all()

import gevent
import gevent.threadpool

# 限制 gevent 的 threadpool 大小，防止线程耗尽
gevent.config.threadpool_size = 10
gevent.config.threadpool_idle = 2

print("[WECUBEK8S_INIT] Configuring gevent threadpool maxsize=10", file=sys.stderr, flush=True)
print(f"[WECUBEK8S_INIT] Using resolver: {os.environ.get('GEVENT_RESOLVER', 'thread')}", file=sys.stderr, flush=True)

# 获取当前 hub 并设置 threadpool
try:
    hub = gevent.get_hub()
    if not hasattr(hub, 'threadpool') or hub.threadpool is None:
        hub.threadpool = gevent.threadpool.ThreadPool(maxsize=10)
        print("[WECUBEK8S_INIT] Gevent threadpool set successfully", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[WECUBEK8S_INIT] Failed to set threadpool: {e}", file=sys.stderr, flush=True)
