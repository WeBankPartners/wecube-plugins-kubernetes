#!/bin/bash
# 配置 containerd 允许 HTTP 私有仓库
# 在每个 K8s 节点上执行此脚本

REGISTRY="192.168.150.6:30816"

echo "================================================"
echo "配置 containerd 允许 HTTP 仓库: $REGISTRY"
echo "节点: $(hostname)"
echo "时间: $(date)"
echo "================================================"

# 备份现有配置
BACKUP_FILE="/etc/containerd/config.toml.bak-$(date +%Y%m%d-%H%M%S)"
echo "备份配置文件到: $BACKUP_FILE"
cp /etc/containerd/config.toml "$BACKUP_FILE"

# 检查是否已经配置
if grep -q "registry.mirrors.\"$REGISTRY\"" /etc/containerd/config.toml; then
    echo "⚠️  配置已存在，跳过添加"
else
    echo "添加私有仓库配置..."
    # 添加配置到文件末尾
    cat >> /etc/containerd/config.toml << CONF

# ====================================================
# 私有仓库 HTTP 配置 - 由脚本自动添加
# 添加时间: $(date)
# ====================================================
[plugins."io.containerd.grpc.v1.cri".registry.mirrors."$REGISTRY"]
  endpoint = ["http://$REGISTRY"]

[plugins."io.containerd.grpc.v1.cri".registry.configs."$REGISTRY".tls]
  insecure_skip_verify = true
CONF
    
    echo "✓ 配置已添加"
fi

# 显示添加的配置
echo ""
echo "当前私有仓库配置："
grep -A3 "registry.mirrors.\"$REGISTRY\"" /etc/containerd/config.toml || echo "未找到配置"

# 重启 containerd
echo ""
echo "重启 containerd 服务..."
systemctl restart containerd

# 等待服务启动
sleep 5

# 验证服务状态
if systemctl is-active --quiet containerd; then
    echo "✓ containerd 服务运行正常"
else
    echo "✗ containerd 服务启动失败！"
    systemctl status containerd --no-pager
    exit 1
fi

# 测试镜像拉取
echo ""
echo "测试镜像拉取..."
if crictl pull "$REGISTRY/library/package-init-container:1.0.0" 2>&1 | head -20; then
    echo ""
    echo "✓ 镜像拉取成功！"
    echo "✓ 节点 $(hostname) 配置完成"
else
    echo ""
    echo "⚠️  镜像拉取失败，但配置已应用"
    echo "可能的原因："
    echo "  1. 镜像不存在于仓库"
    echo "  2. 仓库认证问题"
    echo "  3. 网络问题"
fi

echo ""
echo "================================================"
echo "配置完成"
echo "================================================"

