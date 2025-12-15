# WeCube K8s Plugin RBAC 配置指南

## 📋 前置条件

在开始之前，请确保：

1. ✅ 您已经连接到 Kubernetes 集群
2. ✅ kubectl 已正确配置并可以访问集群
3. ✅ 您有足够的权限创建 ServiceAccount、ClusterRole 和 ClusterRoleBinding

### 验证 kubectl 连接

```bash
# 检查 kubectl 配置
kubectl cluster-info

# 查看当前上下文
kubectl config current-context

# 测试连接
kubectl get nodes
```

如果上述命令失败，请先配置您的 kubeconfig：

```bash
# 设置 kubeconfig（根据您的集群配置调整）
export KUBECONFIG=/path/to/your/kubeconfig
# 或者
kubectl config use-context <your-context-name>
```

---

## 🚀 快速开始（推荐方式）

### 方式 1: 使用自动化脚本

```bash
# 1. 给脚本添加执行权限
chmod +x apply-rbac.sh

# 2. 执行脚本
./apply-rbac.sh
```

脚本会自动完成以下操作：
- ✅ 应用 RBAC 配置
- ✅ 生成 ServiceAccount Token
- ✅ 验证所有权限
- ✅ 测试实际访问

---

## 📝 手动执行步骤

### 步骤 1: 应用 RBAC 配置

```bash
kubectl apply -f k8s-plugin-rbac.yaml
```

预期输出：
```
serviceaccount/wecube-k8s-plugin created
secret/wecube-k8s-plugin-token created
clusterrole.rbac.authorization.k8s.io/wecube-k8s-plugin-role created
clusterrolebinding.rbac.authorization.k8s.io/wecube-k8s-plugin-binding created
```

### 步骤 2: 等待 Secret 生成

```bash
# 等待几秒让 Secret 完全生成
sleep 5
```

### 步骤 3: 获取 Token

```bash
kubectl get secret wecube-k8s-plugin-token -n default \
  -o jsonpath='{.data.token}' | base64 -d > new-token.txt

# 查看 Token
cat new-token.txt
```

### 步骤 4: 验证基本权限

```bash
# 验证 namespaces 权限
kubectl auth can-i get namespaces \
  --as=system:serviceaccount:default:wecube-k8s-plugin

# 验证 deployments 权限
kubectl auth can-i create deployments -n default \
  --as=system:serviceaccount:default:wecube-k8s-plugin

# 验证 statefulsets 权限
kubectl auth can-i create statefulsets -n default \
  --as=system:serviceaccount:default:wecube-k8s-plugin
```

✅ 所有命令都应该返回 `yes`

### 步骤 5: 验证 Prometheus 权限（重要！）

这是解决您之前遇到的 `watch nodes` 权限问题的关键：

```bash
# 验证 nodes watch 权限（Prometheus 需要）
kubectl auth can-i watch nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin

# 验证 nodes list 权限
kubectl auth can-i list nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin

# 验证 nodes get 权限
kubectl auth can-i get nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin

# 验证 endpoints 权限
kubectl auth can-i list endpoints \
  --as=system:serviceaccount:default:wecube-k8s-plugin
```

✅ 所有命令都应该返回 `yes`

### 步骤 6: 测试实际访问

```bash
# 使用生成的 Token 访问集群
kubectl get nodes --token=$(cat new-token.txt)

# 测试访问 endpoints
kubectl get endpoints --all-namespaces --token=$(cat new-token.txt)
```

---

## ✅ 权限清单

此 RBAC 配置包含以下权限：

### 基础资源权限
- ✅ **Namespaces**: get, list, watch, create, update, patch, delete
- ✅ **Deployments**: get, list, watch, create, update, patch, delete
- ✅ **StatefulSets**: get, list, watch, create, update, patch, delete
- ✅ **Pods**: get, list, watch, create, update, patch, delete
- ✅ **Services**: get, list, watch, create, update, patch, delete
- ✅ **ConfigMaps**: get, list, watch, create, update, patch, delete
- ✅ **Secrets**: get, list, watch, create, update, patch, delete
- ✅ **PersistentVolumeClaims**: get, list, watch, create, update, patch, delete

### Prometheus 所需权限（新增）
- ✅ **Nodes**: get, list, watch
- ✅ **Endpoints**: get, list, watch
- ✅ **Pods/log**: get, list
- ✅ **Nodes/metrics, Nodes/stats, Nodes/proxy**: get, list

---

## 🔧 故障排查

### 问题 1: Secret 没有生成

```bash
# 检查 Secret 是否存在
kubectl get secret wecube-k8s-plugin-token -n default

# 如果不存在，手动创建
kubectl delete secret wecube-k8s-plugin-token -n default
kubectl apply -f k8s-plugin-rbac.yaml
```

### 问题 2: Token 为空

```bash
# 等待更长时间
sleep 10

# 重新获取
kubectl get secret wecube-k8s-plugin-token -n default \
  -o jsonpath='{.data.token}' | base64 -d > new-token.txt
```

### 问题 3: 权限验证失败

```bash
# 检查 ClusterRoleBinding
kubectl get clusterrolebinding wecube-k8s-plugin-binding -o yaml

# 重新应用配置
kubectl delete -f k8s-plugin-rbac.yaml
kubectl apply -f k8s-plugin-rbac.yaml
```

### 问题 4: Prometheus 仍然报权限错误

```bash
# 验证具体的权限
kubectl auth can-i watch nodes \
  --as=system:serviceaccount:default:wecube-k8s-plugin -v=8

# 查看详细的 RBAC 规则
kubectl describe clusterrole wecube-k8s-plugin-role
```

---

## 🔄 更新权限

如果需要添加更多权限，编辑 `k8s-plugin-rbac.yaml` 文件，然后重新应用：

```bash
kubectl apply -f k8s-plugin-rbac.yaml
```

不需要重新生成 Token，现有的 Token 会自动继承新权限。

---

## 🗑️ 清理资源

如果需要删除所有创建的资源：

```bash
kubectl delete -f k8s-plugin-rbac.yaml
```

---

## 📞 需要帮助？

如果遇到问题：

1. 检查 kubectl 版本: `kubectl version`
2. 查看集群状态: `kubectl cluster-info`
3. 检查当前用户权限: `kubectl auth can-i create clusterrole`
4. 查看日志: `kubectl logs -n default <pod-name>`

---

## 📄 生成的文件

- `k8s-plugin-rbac.yaml` - RBAC 配置文件
- `apply-rbac.sh` - 自动化部署脚本
- `new-token.txt` - 生成的 ServiceAccount Token
- `README-RBAC-Setup.md` - 本文档

---

**最后更新**: 2025-12-10  
**版本**: 1.0.0



