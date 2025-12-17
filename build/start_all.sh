#!/bin/sh
# 启动脚本 - 修复版本
# 确保环境变量被正确导出和验证

echo "================================================" >&2
echo "[START] WeCube Kubernetes Plugin Starting..." >&2
echo "================================================" >&2

# 验证必需的数据库环境变量
echo "[START] Verifying database environment variables..." >&2
if [ -z "$KUBERNETES_DB_USERNAME" ]; then
    echo "[ERROR] KUBERNETES_DB_USERNAME not set!" >&2
    exit 1
fi
if [ -z "$KUBERNETES_DB_HOSTIP" ]; then
    echo "[ERROR] KUBERNETES_DB_HOSTIP not set!" >&2
    exit 1
fi
if [ -z "$KUBERNETES_DB_SCHEMA" ]; then
    echo "[ERROR] KUBERNETES_DB_SCHEMA not set!" >&2
    exit 1
fi

echo "[START] Database configuration:" >&2
echo "  Username: ${KUBERNETES_DB_USERNAME}" >&2
echo "  Host: ${KUBERNETES_DB_HOSTIP}:${KUBERNETES_DB_HOSTPORT}" >&2
echo "  Schema: ${KUBERNETES_DB_SCHEMA}" >&2

# 显式导出环境变量（确保子进程能够继承）
export KUBERNETES_DB_USERNAME
export KUBERNETES_DB_PASSWORD
export KUBERNETES_DB_HOSTIP
export KUBERNETES_DB_HOSTPORT
export KUBERNETES_DB_SCHEMA

# 其他可能需要的环境变量
export GATEWAY_URL
export JWT_SIGNING_KEY
export SUB_SYSTEM_CODE
export SUB_SYSTEM_KEY
export TZ
export ENCRYPT_SEED
export NOTIFY_POD_ADDED
export NOTIFY_POD_DELETED
export KUBERNETES_LOG_LEVEL

# 设置 gevent 环境变量
export GEVENT_THREADPOOL_SIZE=10
export GEVENT_RESOLVER=thread

echo "[START] gevent configuration:" >&2
echo "  GEVENT_THREADPOOL_SIZE=${GEVENT_THREADPOOL_SIZE}" >&2
echo "  GEVENT_RESOLVER=${GEVENT_RESOLVER}" >&2

# 创建日志目录
mkdir -p /var/log/wecubek8s

# 启动 scheduler（输出到日志文件）
echo "[START] Starting wecubek8s_scheduler..." >&2
nohup wecubek8s_scheduler >> /var/log/wecubek8s/scheduler.log 2>&1 &
SCHEDULER_PID=$!
echo "[START] Scheduler started with PID: $SCHEDULER_PID" >&2

# 延迟启动 watcher（给 API 服务器时间初始化数据库连接池）
echo "[START] Waiting 3 seconds before starting watcher..." >&2
sleep 3

# 启动 watcher（输出到日志文件）
echo "[START] Starting wecubek8s_watcher with inherited environment..." >&2
nohup wecubek8s_watcher >> /var/log/wecubek8s/watcher.log 2>&1 &
WATCHER_PID=$!
echo "[START] Watcher started with PID: $WATCHER_PID" >&2

# 启动 wsgi api server（前台运行，保持容器alive）
echo "[START] Starting gunicorn API server..." >&2
echo "================================================" >&2
/usr/local/bin/gunicorn --config /etc/wecubek8s/gunicorn.py wecubek8s.server.wsgi_server:application
