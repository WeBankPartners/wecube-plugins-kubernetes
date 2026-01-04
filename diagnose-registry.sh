#!/bin/bash

#####################################################
# HTTP 仓库诊断脚本
# 用于排查为什么无法拉取镜像
#####################################################

REGISTRY="192.168.150.6:30816"
TEST_IMAGE="$REGISTRY/library/package-init-container:1.0.0"
CONFIG_PATH="/etc/containerd/certs.d"

# 仓库认证信息
REGISTRY_USERNAME="admin"
REGISTRY_PASSWORD="Passw0rd@123"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}✓${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
section() {
    echo ""
    echo "=========================================="
    echo "$1"
    echo "=========================================="
}

section "HTTP 仓库连接诊断"
echo "仓库: $REGISTRY"
echo "测试镜像: $TEST_IMAGE"
echo ""

# 检查 1: 网络连通性
section "检查 1: 网络连通性测试"
echo "测试 TCP 连接到 $REGISTRY ..."
if timeout 5 bash -c "echo > /dev/tcp/192.168.150.6/30816" 2>/dev/null; then
    info "TCP 连接成功"
else
    error "TCP 连接失败，无法连接到仓库"
fi

echo ""
echo "测试 HTTP 连接（不带认证）..."
HTTP_RESPONSE=$(timeout 5 curl -s -o /dev/null -w "%{http_code}" "http://$REGISTRY/v2/" --connect-timeout 3 --max-time 5 2>/dev/null || echo "000")
if [ "$HTTP_RESPONSE" = "200" ]; then
    info "HTTP 连接成功（仓库不需要认证）"
elif [ "$HTTP_RESPONSE" = "401" ]; then
    warn "仓库需要认证（HTTP 401）"
    echo ""
    echo "测试 HTTP 连接（带认证）..."
    HTTP_RESPONSE_AUTH=$(timeout 5 curl -s -o /dev/null -w "%{http_code}" -u "$REGISTRY_USERNAME:$REGISTRY_PASSWORD" "http://$REGISTRY/v2/" --connect-timeout 3 --max-time 5 2>/dev/null || echo "000")
    if [ "$HTTP_RESPONSE_AUTH" = "200" ]; then
        info "HTTP 认证成功（HTTP 200）"
    elif [ "$HTTP_RESPONSE_AUTH" = "401" ]; then
        error "HTTP 认证失败（用户名或密码错误）"
    elif [ "$HTTP_RESPONSE_AUTH" = "000" ]; then
        error "HTTP 请求超时或失败"
    else
        warn "HTTP 返回: $HTTP_RESPONSE_AUTH"
    fi
elif [ "$HTTP_RESPONSE" = "000" ]; then
    error "HTTP 连接失败或超时，无法访问仓库"
else
    warn "HTTP 返回: $HTTP_RESPONSE"
fi

# 检查 2: 仓库 API 测试
section "检查 2: 仓库 API 测试"
echo "测试 Docker Registry V2 API（先不带认证）..."
V2_RESPONSE=$(timeout 5 curl -s "http://$REGISTRY/v2/" --connect-timeout 3 --max-time 5 2>/dev/null || echo "TIMEOUT")
if [ "$V2_RESPONSE" = "TIMEOUT" ]; then
    error "API 请求超时"
else
    echo "API 响应（不带认证）: $V2_RESPONSE"
    if echo "$V2_RESPONSE" | grep -q "{}"; then
        info "仓库 API 正常响应（不需要认证）"
    elif echo "$V2_RESPONSE" | grep -q "401\|unauthorized"; then
        warn "仓库需要认证，尝试带认证访问..."
        V2_RESPONSE_AUTH=$(timeout 5 curl -s -u "$REGISTRY_USERNAME:$REGISTRY_PASSWORD" "http://$REGISTRY/v2/" --connect-timeout 3 --max-time 5 2>/dev/null || echo "TIMEOUT")
        if [ "$V2_RESPONSE_AUTH" = "TIMEOUT" ]; then
            error "带认证的 API 请求超时"
        else
            echo "API 响应（带认证）: $V2_RESPONSE_AUTH"
            if echo "$V2_RESPONSE_AUTH" | grep -q "{}"; then
                info "仓库 API 认证成功"
            else
                warn "认证后响应异常"
            fi
        fi
    else
        warn "仓库 API 响应异常"
    fi
fi

# 检查 3: 镜像是否存在
section "检查 3: 检查镜像是否存在"
echo "查询镜像仓库: library/package-init-container（先不带认证）"
MANIFEST=$(timeout 5 curl -s "http://$REGISTRY/v2/library/package-init-container/tags/list" --connect-timeout 3 --max-time 5 2>/dev/null || echo "TIMEOUT")
if [ "$MANIFEST" = "TIMEOUT" ]; then
    error "查询镜像标签超时"
else
    echo "响应（不带认证）: $MANIFEST"
    if echo "$MANIFEST" | grep -q "1.0.0"; then
        info "镜像 1.0.0 标签存在（不需要认证）"
    elif echo "$MANIFEST" | grep -q "401\|unauthorized"; then
        warn "需要认证，尝试带认证访问..."
        MANIFEST_AUTH=$(timeout 5 curl -s -u "$REGISTRY_USERNAME:$REGISTRY_PASSWORD" "http://$REGISTRY/v2/library/package-init-container/tags/list" --connect-timeout 3 --max-time 5 2>/dev/null || echo "TIMEOUT")
        if [ "$MANIFEST_AUTH" = "TIMEOUT" ]; then
            error "带认证查询超时"
        else
            echo "响应（带认证）: $MANIFEST_AUTH"
            if echo "$MANIFEST_AUTH" | grep -q "1.0.0"; then
                info "镜像 1.0.0 标签存在（认证成功）"
            elif echo "$MANIFEST_AUTH" | grep -q "tags"; then
                warn "镜像存在但可能没有 1.0.0 标签"
                echo "可用标签: $MANIFEST_AUTH"
            else
                error "镜像不存在或认证失败"
            fi
        fi
    elif echo "$MANIFEST" | grep -q "tags"; then
        warn "镜像存在但可能没有 1.0.0 标签"
        echo "可用标签: $MANIFEST"
    else
        error "镜像不存在或无法访问"
    fi
fi

# 检查 4: containerd 配置
section "检查 4: containerd 配置检查"
echo "检查 containerd 主配置..."
if grep -q "config_path.*=" /etc/containerd/config.toml; then
    CONFIG_PATH_VALUE=$(grep "config_path" /etc/containerd/config.toml | grep -v "^#" | head -1)
    info "config_path 已配置: $CONFIG_PATH_VALUE"
else
    error "config_path 未配置！containerd 不会读取 certs.d 目录"
fi

echo ""
echo "检查 hosts.toml 配置..."
HOSTS_FILE="$CONFIG_PATH/$REGISTRY/hosts.toml"
if [ -f "$HOSTS_FILE" ]; then
    info "hosts.toml 存在: $HOSTS_FILE"
    echo "配置内容:"
    cat "$HOSTS_FILE"
else
    error "hosts.toml 不存在: $HOSTS_FILE"
fi

# 检查 5: crictl 配置
section "检查 5: crictl 配置检查"
if [ -f /etc/crictl.yaml ]; then
    echo "crictl 配置:"
    cat /etc/crictl.yaml
else
    warn "crictl.yaml 不存在"
fi

# 检查 6: 验证认证信息是否有效
section "检查 6: 验证认证信息"
echo "生成 base64 编码的认证信息用于测试..."
AUTH_BASE64=$(echo -n "$REGISTRY_USERNAME:$REGISTRY_PASSWORD" | base64 | tr -d '\n')
info "认证信息已编码: $AUTH_BASE64"

echo ""
echo "测试访问镜像 manifest（不带认证）..."
MANIFEST_TEST=$(timeout 5 curl -s -w "\nHTTP_CODE:%{http_code}" \
    "http://$REGISTRY/v2/library/package-init-container/manifests/1.0.0" \
    --connect-timeout 3 --max-time 5 2>/dev/null || echo "TIMEOUT")

if [ "$MANIFEST_TEST" = "TIMEOUT" ]; then
    error "请求超时"
else
    HTTP_CODE=$(echo "$MANIFEST_TEST" | grep "HTTP_CODE:" | cut -d: -f2)
    if [ "$HTTP_CODE" = "200" ]; then
        info "可以成功访问镜像 manifest（不需要认证）"
    elif [ "$HTTP_CODE" = "401" ]; then
        warn "需要认证，测试使用认证信息..."
        MANIFEST_AUTH=$(timeout 5 curl -s -w "\nHTTP_CODE:%{http_code}" \
            -H "Authorization: Basic $AUTH_BASE64" \
            "http://$REGISTRY/v2/library/package-init-container/manifests/1.0.0" \
            --connect-timeout 3 --max-time 5 2>/dev/null || echo "TIMEOUT")
        
        if [ "$MANIFEST_AUTH" = "TIMEOUT" ]; then
            error "带认证的请求超时"
        else
            HTTP_CODE_AUTH=$(echo "$MANIFEST_AUTH" | grep "HTTP_CODE:" | cut -d: -f2)
            if [ "$HTTP_CODE_AUTH" = "200" ]; then
                info "使用认证信息可以成功访问镜像 manifest ✅"
            elif [ "$HTTP_CODE_AUTH" = "401" ]; then
                error "认证失败（401），用户名或密码不正确 ❌"
            elif [ "$HTTP_CODE_AUTH" = "404" ]; then
                warn "认证成功但镜像不存在（404）"
            else
                warn "HTTP 状态码: $HTTP_CODE_AUTH"
            fi
        fi
    elif [ "$HTTP_CODE" = "404" ]; then
        warn "镜像不存在（404）"
    else
        warn "HTTP 状态码: $HTTP_CODE"
    fi
fi

section "检查 7: 尝试拉取镜像（只测试，不修改配置）"
echo "尝试拉取镜像（显示详细错误）..."
echo "命令: crictl pull $TEST_IMAGE"
echo ""
crictl pull "$TEST_IMAGE" 2>&1 | tee /tmp/crictl-pull-error.log
PULL_EXIT_CODE=${PIPESTATUS[0]}

echo ""
if [ $PULL_EXIT_CODE -eq 0 ]; then
    info "镜像拉取成功！✅"
else
    error "镜像拉取失败（退出码: $PULL_EXIT_CODE）"
    echo ""
    echo "错误日志已保存到: /tmp/crictl-pull-error.log"
fi

# 检查 8: containerd 日志中的相关错误
section "检查 8: containerd 日志分析"
echo "查找最近的镜像拉取相关日志..."
journalctl -u containerd --since "5 minutes ago" --no-pager 2>/dev/null | grep -i "pull\|registry\|$REGISTRY\|auth" | tail -20

# 总结
section "诊断总结"
echo ""
warn "如果拉取失败，常见原因："
echo "  1. 认证失败 - 用户名或密码不正确"
echo "  2. 镜像不存在 - 检查仓库中是否真的有这个镜像"
echo "  3. 网络不通 - 检查防火墙、路由"
echo "  4. containerd 未配置 config_path - 需要在 config.toml 中启用"
echo "  5. 配置未生效 - 需要重启 containerd"
echo ""

info "推荐操作："
echo ""
echo "  1. 手动配置 containerd 认证（如果需要）："
echo ""
AUTH_BASE64_DISPLAY=$(echo -n "$REGISTRY_USERNAME:$REGISTRY_PASSWORD" | base64 | tr -d '\n')
echo "     创建认证配置文件："
echo "     sudo mkdir -p /etc/containerd/certs.d/$REGISTRY"
echo ""
echo "     创建配置文件 /etc/containerd/certs.d/$REGISTRY/hosts.toml："
echo "     ---"
echo "     server = \"http://$REGISTRY\""
echo ""
echo "     [host.\"http://$REGISTRY\"]"
echo "       capabilities = [\"pull\", \"resolve\", \"push\"]"
echo "       skip_verify = true"
echo ""
echo "     [host.\"http://$REGISTRY\".header]"
echo "       authorization = \"Basic $AUTH_BASE64_DISPLAY\""
echo "     ---"
echo ""
echo "     然后重启 containerd:"
echo "     sudo systemctl restart containerd"
echo ""
echo "  2. 确认镜像存在（带认证）："
echo "     curl -u $REGISTRY_USERNAME:$REGISTRY_PASSWORD http://$REGISTRY/v2/library/package-init-container/tags/list"
echo ""
echo "  3. 查看所有可用镜像："
echo "     curl -u $REGISTRY_USERNAME:$REGISTRY_PASSWORD http://$REGISTRY/v2/_catalog"
echo ""
echo "  4. 当前测试的认证信息："
echo "     用户名: $REGISTRY_USERNAME"
echo "     密码: $REGISTRY_PASSWORD"
echo "     Base64: $AUTH_BASE64_DISPLAY"
echo ""

