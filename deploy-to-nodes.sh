#!/bin/bash
# 批量部署配置到所有 K8s 节点

# ⚠️ 请修改为你的实际节点 IP 地址
NODES=(
    "192.168.1.11"  # Worker Node 1
    "192.168.1.12"  # Worker Node 2
    "192.168.1.13"  # Worker Node 3
)

# SSH 用户（通常是 root 或有 sudo 权限的用户）
SSH_USER="root"

# 脚本路径
SCRIPT_PATH="./k8s-node-setup.sh"

echo "=========================================="
echo "批量部署 K8s 节点配置"
echo "=========================================="
echo "节点数量: ${#NODES[@]}"
echo "脚本: $SCRIPT_PATH"
echo ""

for NODE in "${NODES[@]}"; do
    echo "----------------------------------------"
    echo "配置节点: $NODE"
    echo "----------------------------------------"
    
    # 1. 复制脚本到节点
    echo "1. 上传脚本..."
    scp "$SCRIPT_PATH" "$SSH_USER@$NODE:/tmp/k8s-node-setup.sh"
    
    if [ $? -ne 0 ]; then
        echo "✗ 上传失败，跳过节点 $NODE"
        continue
    fi
    
    # 2. 执行脚本
    echo "2. 执行配置脚本..."
    ssh "$SSH_USER@$NODE" "sudo bash /tmp/k8s-node-setup.sh"
    
    if [ $? -eq 0 ]; then
        echo "✓ 节点 $NODE 配置成功"
    else
        echo "✗ 节点 $NODE 配置失败"
    fi
    
    echo ""
done

echo "=========================================="
echo "部署完成"
echo "=========================================="
echo ""
echo "验证配置："
echo "  ssh $SSH_USER@NODE_IP"
echo "  docker info | grep -A 5 'Insecure Registries'"

