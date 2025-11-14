#!/bin/bash
# Kubernetes 节点 HTTP 私有仓库配置脚本
# 在每个 K8s 节点上执行此脚本

set -e

REGISTRY="***REMOVED***"

echo "=========================================="
echo "Configuring Kubernetes Node for HTTP Registry"
echo "=========================================="
echo "Registry: $REGISTRY"
echo ""

# 检测容器运行时
if command -v docker &> /dev/null && [ -d /etc/docker ]; then
    echo "Detected: Docker runtime"
    echo "----------------------------------------"
    
    # 备份配置
    if [ -f /etc/docker/daemon.json ]; then
        sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.backup.$(date +%Y%m%d%H%M%S)
        echo "✓ Backed up existing config"
    fi
    
    # 创建或更新配置
    if [ ! -f /etc/docker/daemon.json ]; then
        echo '{}' | sudo tee /etc/docker/daemon.json > /dev/null
    fi
    
    # 使用 python 处理 JSON（兼容性更好）
    python3 <<EOF
import json
config_file = '/etc/docker/daemon.json'
with open(config_file, 'r') as f:
    config = json.load(f)
if 'insecure-registries' not in config:
    config['insecure-registries'] = []
if '$REGISTRY' not in config['insecure-registries']:
    config['insecure-registries'].append('$REGISTRY')
with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)
EOF
    
    echo "✓ Updated Docker configuration"
    cat /etc/docker/daemon.json
    
    # 重启 Docker
    echo ""
    echo "Restarting Docker..."
    sudo systemctl restart docker
    sleep 5
    
    echo "✓ Docker restarted"
    docker info | grep -A 5 "Insecure Registries" || echo "Config applied"
    
elif command -v crictl &> /dev/null && [ -d /etc/containerd ]; then
    echo "Detected: containerd runtime"
    echo "----------------------------------------"
    
    # 创建配置目录
    sudo mkdir -p /etc/containerd/certs.d/$REGISTRY
    
    # 创建 hosts.toml
    sudo tee /etc/containerd/certs.d/$REGISTRY/hosts.toml > /dev/null <<EOFCONFIG
server = "http://$REGISTRY"

[host."http://$REGISTRY"]
  capabilities = ["pull", "resolve", "push"]
  skip_verify = true
EOFCONFIG
    
    echo "✓ Created containerd configuration"
    cat /etc/containerd/certs.d/$REGISTRY/hosts.toml
    
    # 重启 containerd
    echo ""
    echo "Restarting containerd..."
    sudo systemctl restart containerd
    sleep 5
    
    echo "✓ containerd restarted"
    
else
    echo "✗ Could not detect container runtime (Docker or containerd)"
    echo "Please configure manually"
    exit 1
fi

echo ""
echo "=========================================="
echo "✓ Configuration completed successfully!"
echo "=========================================="
echo ""
echo "You can now pull images from: $REGISTRY"
echo "Example:"
echo "  docker pull $REGISTRY/package-init-container:1.0.0"
echo "  # or"
echo "  sudo crictl pull $REGISTRY/package-init-container:1.0.0"

