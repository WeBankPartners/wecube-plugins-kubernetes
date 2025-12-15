#!/bin/bash

# WeCube K8s Plugin RBAC 配置和 Token 生成脚本
# ===================================================

set -e  # 遇到错误立即退出

echo "🚀 开始配置 WeCube K8s Plugin RBAC..."
echo ""

# 1. 应用 RBAC 配置
echo "📝 步骤 1: 应用 RBAC 配置文件..."
kubectl apply -f k8s-plugin-rbac.yaml
echo "✅ RBAC 配置已应用"
echo ""

# 2. 等待 Secret 生成
echo "⏳ 步骤 2: 等待 Secret 生成..."
sleep 5
echo "✅ 等待完成"
echo ""

# 3. 获取新的 Token
echo "🔑 步骤 3: 获取新的 Token..."
kubectl get secret wecube-k8s-plugin-token -n default \
  -o jsonpath='{.data.token}' | base64 -d > new-token.txt
echo "✅ Token 已保存到 new-token.txt"
echo ""

# 4. 验证基本权限
echo "🔍 步骤 4: 验证基本权限..."
echo ""

echo "检查 namespaces 权限:"
kubectl auth can-i get namespaces \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo "检查 deployments 权限:"
kubectl auth can-i create deployments -n default \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo "检查 statefulsets 权限:"
kubectl auth can-i create statefulsets -n default \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo ""
echo "🔍 步骤 5: 验证 Prometheus 所需权限..."
echo ""

echo "检查 nodes watch 权限 (Prometheus 需要):"
kubectl auth can-i watch nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo "检查 nodes list 权限:"
kubectl auth can-i list nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo "检查 nodes get 权限:"
kubectl auth can-i get nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo "检查 endpoints list 权限:"
kubectl auth can-i list endpoints \
  --as=system:serviceaccount:default:wecube-k8s-plugin

echo ""
echo "🧪 步骤 6: 测试实际访问..."
echo ""

echo "使用 Token 获取 nodes 列表:"
kubectl get nodes --token=$(cat new-token.txt) 2>&1 | head -n 5

echo ""
echo "================================================================"
echo "✅ 配置完成！"
echo "================================================================"
echo ""
echo "📄 Token 文件位置: ./new-token.txt"
echo ""
echo "📋 查看完整 Token:"
echo "   cat new-token.txt"
echo ""
echo "🔧 如需重新生成 Token，请再次运行此脚本"
echo "================================================================"



