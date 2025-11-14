# 快速开始指南

## 1. 构建镜像

```bash
cd package-init-container

# 方式1: 使用本地镜像文件（推荐，完全离线）
# 首先导出基础镜像（只需要执行一次）
./save-base-image.sh alpine:3.18
# 然后构建（会自动加载本地镜像文件）
./build.sh

# 方式2: 使用 build.sh 脚本（自动尝试多个镜像源）
./build.sh

# 方式3: 直接使用 docker build
docker build -t package-init-container:latest .

# 方式4: 指定仓库和标签
export REGISTRY=your-registry.com/wecube
export IMAGE_TAG=v1.0.0
./build.sh
```

**推荐使用方式1**：如果网络环境受限或遇到镜像加速器问题，使用本地镜像文件可以完全避免网络连接和授权问题。

## 2. 推送到镜像仓库

```bash
# 如果使用默认名称
docker push package-init-container:latest

# 如果指定了仓库
docker push your-registry.com/wecube/package-init-container:v1.0.0
```

## 3. 配置 WeCube K8s Plugin

在 `wecubek8s.conf` 配置文件中添加：

```ini
[variables]
init_container_image = your-registry.com/wecube/package-init-container:v1.0.0
```

## 4. 使用示例

### 通过 API 调用

```bash
curl -X POST http://your-api-server/kubernetes/v1/deployments/apply \
  -H "Content-Type: application/json" \
  -d '{
    "cluster": "my-cluster",
    "name": "my-app",
    "namespace": "default",
    "images": [{"name": "my-app", "ports": "8080"}],
    "packageUrl": "https://example.com/packages/my-app.tar",
    "replicas": "1"
  }'
```

### 验证

```bash
# 查看 Pod 状态
kubectl get pods -n default

# 查看 initContainer 日志
kubectl logs <pod-name> -c package-downloader

# 进入容器查看解压的文件
kubectl exec -it <pod-name> -c <main-container> -- ls -lah /shared-data/diff-var-files/
```

## 5. 测试镜像（本地测试）

```bash
# 运行容器测试
docker run --rm \
  -e PACKAGE_URL="https://example.com/test.tar" \
  -v /tmp/test-output:/shared-data/diff-var-files \
  package-init-container:latest

# 检查输出
ls -lah /tmp/test-output/
```

