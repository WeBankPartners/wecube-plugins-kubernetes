# DaemonSet 接口使用指南

## 📋 实现概述

已成功实现 Kubernetes DaemonSet 接口，支持在每个节点上自动部署一个 Pod 副本。适用于日志收集、监控 Agent、网络插件等节点级服务。

## 🎯 实现的功能

### ✅ 已完成的修改

1. **`const.py`**: 添加 `DAEMONSET_ID_TAG` 常量
2. **`rules.py`**: 添加 `daemonset_rules` 验证规则（不含 replicas 和 affinity）
3. **`controller.py`**: 添加 `DaemonSet` Controller 类
4. **`api.py`**: 实现 DaemonSet 核心逻辑（创建、更新、删除）
5. **`route.py`**: 添加 DaemonSet 路由
6. **`k8s.py`**: 添加 DaemonSet 相关的 K8s API 调用方法

---

## 🔧 API 端点

### 1. 创建/更新 DaemonSet

**URL**: `POST /kubernetes/v1/daemonsets/apply`

**请求体示例 - 基础用法**:

```json
{
  "cluster": "my-cluster",
  "correlation_id": "daemonset-node-exporter-001",
  "name": "node-exporter",
  "namespace": "monitoring",
  "image_name": "prom/node-exporter:latest",
  "image_port": "9100",
  "cpu": "100m",
  "memory": "128Mi"
}
```

**请求体示例 - 完整配置**:

```json
{
  "cluster": "production-cluster",
  "correlation_id": "daemonset-filebeat-001",
  "name": "filebeat-logger",
  "namespace": "logging",
  "image_name": "elastic/filebeat:7.17.0",
  "image_port": "",
  "cpu": "200m",
  "memory": "256Mi",
  "tags": [
    {"name": "app", "value": "filebeat"},
    {"name": "tier", "value": "logging"}
  ],
  "pod_tags": [
    {"name": "component", "value": "log-collector"}
  ],
  "envs": [
    {
      "name": "ELASTICSEARCH_HOST",
      "value": "elasticsearch.logging.svc.cluster.local",
      "valueFrom": "value"
    },
    {
      "name": "ELASTICSEARCH_PORT",
      "value": "9200",
      "valueFrom": "value"
    }
  ],
  "volumes": [
    {
      "name": "varlog",
      "mountPath": "/var/log",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {
        "path": "/var/log",
        "type": "Directory"
      }
    },
    {
      "name": "varlibdockercontainers",
      "mountPath": "/var/lib/docker/containers",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {
        "path": "/var/lib/docker/containers",
        "type": "Directory"
      }
    }
  ],
  "node_selector": {
    "kubernetes.io/os": "linux",
    "logging": "enabled"
  },
  "tolerations": [
    {
      "key": "node-role.kubernetes.io/master",
      "operator": "Exists",
      "effect": "NoSchedule"
    },
    {
      "key": "node-role.kubernetes.io/control-plane",
      "operator": "Exists",
      "effect": "NoSchedule"
    }
  ],
  "process_name": "filebeat",
  "process_keyword": "filebeat"
}
```

**响应示例**:

```json
{
  "correlation_id": "daemonset-filebeat-001",
  "name": "filebeat-logger",
  "namespace": "logging",
  "desired_number_scheduled": 5,
  "current_number_scheduled": 5,
  "number_ready": 5,
  "number_available": 5
}
```

---

### 2. 删除 DaemonSet

**URL**: `POST /kubernetes/v1/daemonsets/destroy`

**请求体示例**:

```json
{
  "cluster": "my-cluster",
  "name": "node-exporter",
  "namespace": "monitoring"
}
```

**响应示例**:

```json
{
  "name": "node-exporter",
  "namespace": "monitoring",
  "status": "deleted"
}
```

---

## 📊 字段说明

### 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `cluster` | string | 集群名称 |
| `correlation_id` | string | 关联 ID（唯一标识） |
| `name` | string | DaemonSet 名称 |
| `image_name` | string | 镜像名称（会自动拼接私有仓库地址） |

### 可选字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `namespace` | string | `default` | K8s 命名空间 |
| `image_port` | string | - | 容器端口（逗号分隔，如 "80,443"） |
| `cpu` | string | - | CPU 限制（如 "100m", "0.5", "2"） |
| `memory` | string | - | 内存限制（如 "128Mi", "1Gi"） |
| `tags` | array | - | DaemonSet 标签 |
| `pod_tags` | array | - | Pod 标签 |
| `envs` | array | - | 环境变量 |
| `volumes` | array | - | 卷挂载 |
| `node_selector` | object | - | 节点选择器（限制部署到特定节点） |
| `tolerations` | array | - | 容忍度（允许部署到有污点的节点） |
| `process_name` | string | - | 进程名称（用于健康检查） |
| `process_keyword` | string | - | 进程关键字（用于健康检查） |

---

## 🎯 典型使用场景

### 场景 1: 部署 Prometheus Node Exporter（节点监控）

```json
{
  "cluster": "prod-cluster",
  "correlation_id": "ds-node-exporter-prod",
  "name": "node-exporter",
  "namespace": "monitoring",
  "image_name": "prom/node-exporter:v1.6.1",
  "image_port": "9100",
  "cpu": "100m",
  "memory": "128Mi",
  "envs": [
    {
      "name": "PATH",
      "value": "/proc",
      "valueFrom": "value"
    }
  ],
  "volumes": [
    {
      "name": "proc",
      "mountPath": "/host/proc",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {"path": "/proc", "type": "Directory"}
    },
    {
      "name": "sys",
      "mountPath": "/host/sys",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {"path": "/sys", "type": "Directory"}
    }
  ],
  "node_selector": {
    "kubernetes.io/os": "linux"
  },
  "tolerations": [
    {
      "key": "node-role.kubernetes.io/master",
      "operator": "Exists",
      "effect": "NoSchedule"
    }
  ]
}
```

### 场景 2: 部署 Filebeat（日志收集）

```json
{
  "cluster": "prod-cluster",
  "correlation_id": "ds-filebeat-prod",
  "name": "filebeat",
  "namespace": "logging",
  "image_name": "elastic/filebeat:7.17.0",
  "cpu": "200m",
  "memory": "256Mi",
  "envs": [
    {
      "name": "ELASTICSEARCH_HOST",
      "value": "elasticsearch.logging:9200",
      "valueFrom": "value"
    }
  ],
  "volumes": [
    {
      "name": "varlog",
      "mountPath": "/var/log",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {"path": "/var/log", "type": "Directory"}
    },
    {
      "name": "containers",
      "mountPath": "/var/lib/docker/containers",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {"path": "/var/lib/docker/containers", "type": "Directory"}
    },
    {
      "name": "config",
      "mountPath": "/usr/share/filebeat/filebeat.yml",
      "readOnly": true,
      "type": "configMap",
      "typeSpec": {
        "name": "filebeat-config",
        "items": [{"key": "filebeat.yml", "path": "filebeat.yml"}]
      }
    }
  ]
}
```

### 场景 3: 部署 Falco（安全监控）

```json
{
  "cluster": "prod-cluster",
  "correlation_id": "ds-falco-security",
  "name": "falco",
  "namespace": "security",
  "image_name": "falcosecurity/falco:0.35.1",
  "cpu": "100m",
  "memory": "512Mi",
  "volumes": [
    {
      "name": "docker-socket",
      "mountPath": "/host/var/run/docker.sock",
      "type": "hostPath",
      "typeSpec": {"path": "/var/run/docker.sock", "type": "Socket"}
    },
    {
      "name": "dev",
      "mountPath": "/host/dev",
      "type": "hostPath",
      "typeSpec": {"path": "/dev", "type": "Directory"}
    },
    {
      "name": "proc",
      "mountPath": "/host/proc",
      "readOnly": true,
      "type": "hostPath",
      "typeSpec": {"path": "/proc", "type": "Directory"}
    }
  ],
  "tolerations": [
    {
      "key": "node-role.kubernetes.io/master",
      "operator": "Exists",
      "effect": "NoSchedule"
    }
  ]
}
```

---

## 🔍 DaemonSet vs StatefulSet vs Deployment

| 特性 | **DaemonSet** | **StatefulSet** | **Deployment** |
|------|---------------|-----------------|----------------|
| **部署策略** | 每节点一个 Pod | 固定副本数，有序部署 | 固定副本数，无序部署 |
| **Pod 数量** | 等于节点数（自动） | 手动指定 replicas | 手动指定 replicas |
| **Pod 标识** | 无稳定标识 | 有序号标识（0,1,2...） | 无稳定标识 |
| **网络标识** | 无固定 DNS | 固定 DNS 名称 | 无固定 DNS |
| **存储** | 通常用 hostPath | 独立 PVC | 共享或无状态 |
| **调度** | 必须每个节点 | Scheduler 决定 | Scheduler 决定 |
| **扩缩容** | 随节点自动增减 | 手动修改 replicas | 手动修改 replicas |
| **适用场景** | 节点级服务（监控、日志） | 有状态应用（数据库） | 无状态应用（Web 服务） |

---

## 🔐 镜像拉取凭据说明

**重要**：镜像拉取的用户名和密码不需要在请求参数中传入，而是从数据库的 `cluster_info` 表中自动读取：

- `image_pull_username`：从 `cluster_info.image_pull_username` 读取
- `image_pull_password`：从 `cluster_info.image_pull_password` 读取
- `private_registry`：从 `cluster_info.private_registry` 读取（私有镜像仓库地址）

如果您的镜像存储在私有仓库中，请确保在集群配置中正确设置了这些字段。系统会自动：
1. 将私有仓库地址拼接到镜像名称前面（如：`registry.example.com/image-name`）
2. 使用配置的用户名和密码创建 ImagePullSecret
3. 将 Secret 添加到 DaemonSet 的 Pod 模板中

---

## 🚨 注意事项

1. **节点选择器 (`node_selector`)**：
   - 使用节点选择器可以限制 DaemonSet 只部署到特定节点
   - 如果没有符合条件的节点，Pod 不会被调度

2. **容忍度 (`tolerations`)**：
   - Master 节点默认有污点（taint），普通 Pod 无法调度
   - 如果需要在 Master 节点上运行 DaemonSet，必须添加容忍度

3. **hostPath 卷**：
   - DaemonSet 经常需要访问节点资源（如 /proc、/var/log）
   - 使用 hostPath 时要注意安全性和权限

4. **更新策略**：
   - 默认使用 `RollingUpdate`，一次更新一个节点
   - `maxUnavailable: 1` 确保逐个节点滚动更新

5. **资源限制**：
   - 建议为 DaemonSet 设置合理的 CPU/内存限制
   - 避免影响节点上其他 Pod 的运行

---

## 🧪 测试建议

### 测试步骤

1. **创建 DaemonSet**：
   ```bash
   curl -X POST http://your-api/kubernetes/v1/daemonsets/apply \
     -H "Content-Type: application/json" \
     -d @daemonset-apply.json
   ```

2. **验证部署状态**：
   ```bash
   kubectl get daemonsets -n monitoring
   kubectl get pods -n monitoring -l wecube-pod-auto-tag=node-exporter
   ```

3. **检查 Pod 分布**：
   ```bash
   kubectl get pods -n monitoring -o wide
   # 应该看到每个节点上都有一个 Pod
   ```

4. **查看 Pod 日志**：
   ```bash
   kubectl logs -n monitoring -l wecube-pod-auto-tag=node-exporter --tail=100
   ```

5. **删除 DaemonSet**：
   ```bash
   curl -X POST http://your-api/kubernetes/v1/daemonsets/destroy \
     -H "Content-Type: application/json" \
     -d @daemonset-destroy.json
   ```

---

## 📚 相关文档

- [Kubernetes DaemonSet 官方文档](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/)
- [节点选择器文档](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
- [污点和容忍度文档](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)

---

## ✅ 实现清单

- ✅ DaemonSet 创建/更新
- ✅ DaemonSet 删除
- ✅ 镜像拉取凭据支持
- ✅ 环境变量注入（包括 Downward API）
- ✅ 卷挂载（hostPath、configMap、secret 等）
- ✅ 节点选择器（node_selector）
- ✅ 容忍度（tolerations）
- ✅ 资源限制（CPU/内存）
- ✅ 健康检查探针（liveness probe）
- ✅ 标签和选择器
- ✅ 滚动更新策略

---

**文档版本**: 1.0  
**创建日期**: 2026-01-05  
**作者**: AI Assistant

