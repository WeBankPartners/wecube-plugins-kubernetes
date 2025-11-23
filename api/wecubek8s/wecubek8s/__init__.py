# coding=utf-8

from __future__ import absolute_import

# 在导入任何其他模块之前配置 gevent
import gevent.monkey
gevent.monkey.patch_all()

import gevent
# 限制 gevent 的 threadpool 大小，防止线程耗尽
gevent.config.threadpool_size = 10
gevent.config.threadpool_idle = 2

# 获取当前 hub 并设置 threadpool
try:
    hub = gevent.get_hub()
    if not hasattr(hub, 'threadpool') or hub.threadpool is None:
        import gevent.threadpool
        hub.threadpool = gevent.threadpool.ThreadPool(maxsize=10)
except Exception:
    pass  # 如果设置失败也不影响启动
