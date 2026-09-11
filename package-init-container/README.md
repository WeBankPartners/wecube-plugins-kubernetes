# Package InitContainer 镜像

这个目录包含用于构建 Package InitContainer 镜像的所有文件。该镜像用于在 Kubernetes Pod 启动前下载和解压 package 文件。

## 功能说明

该 InitContainer 镜像的主要功能：
1. 从指定的 URL 下载 tar 格式的 package 文件
2. 将文件解压到 `/shared-data/diff-var-files/` 目录
3. 该目录会被挂载为共享 volume，供主容器使用

## 构建镜像

### 使用构建脚本（推荐）

构建脚本会自动尝试多个镜像源，并支持使用本地镜像文件，**构建成功后会自动推送到私有仓库**：

```bash
cd package-init-container
./build.sh
```

**默认配置：**
- 私有仓库：`***REMOVED***`
- 用户名：`***REMOVED***`
- 密码：`***REMOVED***@123`
- 镜像名：`***REMOVED***/package-init-container:1.0.0`

构建完成后，镜像会自动推送到私有仓库，你可以在 Kubernetes 中直接使用。

### 使用本地镜像文件（完全离线，推荐）

如果网络环境受限或镜像加速器有问题，可以将基础镜像导出为 tar 文件，放在本地使用：

```bash
# 1. 导出基础镜像（只需要执行一次）
./save-base-image.sh alpine:3.18

# 2. 构建（会自动加载本地镜像文件）
./build.sh
```

镜像文件会保存在 `base-images/` 目录下，构建脚本会自动检测并加载。

**优点：**
- ✅ 完全离线构建，不依赖网络
- ✅ 避免镜像加速器转换问题
- ✅ 避免授权失败问题
- ✅ 构建速度更快

### 基本构建

```bash
cd package-init-container
docker build -t package-init-container:latest .
```

### 自定义私有仓库配置

如果需要使用不同的私有仓库，可以通过环境变量覆盖默认配置：

```bash
# 自定义私有仓库地址
PRIVATE_REGISTRY="your-registry.com:5000" \
REGISTRY_USERNAME="your-username" \
REGISTRY_PASSWORD="your-password" \
./build.sh
```

### 禁用自动推送

如果不想自动推送到私有仓库，可以禁用：

```bash
# 只构建，不推送
PUSH_TO_REGISTRY=false ./build.sh
```

### 手动构建和推送

如果需要完全手动控制：

```bash
# 1. 构建镜像
docker build -t package-init-container:1.0.0 .

# 2. 打标签
docker tag package-init-container:1.0.0 ***REMOVED***/package-init-container:1.0.0

# 3. 登录私有仓库
docker login ***REMOVED*** -u ***REMOVED***

# 4. 推送
docker push ***REMOVED***/package-init-container:1.0.0
```

## 使用方法

### 在 Kubernetes 中使用

该镜像通过环境变量 `PACKAGE_URL` 接收要下载的 package 地址。

#### 示例 1: 在 Deployment 中使用

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      initContainers:
      - name: package-downloader
        image: ***REMOVED***/package-init-container:1.0.0
        env:
        - name: PACKAGE_URL
          value: "https://example.com/packages/my-app.tar"
        volumeMounts:
        - name: package-shared-volume
          mountPath: /shared-data/diff-var-files
      containers:
      - name: app
        image: your-app:latest
        volumeMounts:
        - name: package-shared-volume
          mountPath: /shared-data/diff-var-files
          readOnly: true
      volumes:
      - name: package-shared-volume
        emptyDir: {}
      imagePullSecrets:
      - name: registry-secret
```

**注意**：如果使用私有仓库，需要创建 imagePullSecret：

```bash
kubectl create secret docker-registry registry-secret \
  --docker-server=***REMOVED*** \
  --docker-username=***REMOVED*** \
  --docker-password=***REMOVED***@123
```

#### 示例 2: 通过 API 调用

当调用 `/kubernetes/v1/deployments/apply` 接口时，在请求体中包含 `packageUrl` 字段：

```json
{
  "cluster": "my-cluster",
  "name": "my-app",
  "namespace": "default",
  "images": [{"name": "my-app", "ports": "8080"}],
  "packageUrl": "https://example.com/packages/my-app.tar",
  ...
}
```

系统会自动：
1. 创建 initContainer，使用配置的 `init_container_image`
2. 设置 `PACKAGE_URL` 环境变量
3. 挂载共享 volume
4. 将共享 volume 挂载到所有主容器（只读）

## 配置

### 在 WeCube K8s Plugin 中配置镜像地址

在配置文件 `wecubek8s.conf` 中设置：

```ini
[variables]
init_container_image = your-registry/package-init-container:v1.0.0
```

## 镜像特点

- **轻量级**: 基于 Alpine Linux，镜像体积小
- **工具齐全**: 包含 wget、curl、tar 等必要工具
- **错误处理**: 脚本包含完整的错误检查和日志输出
- **兼容性**: 支持 wget 和 curl，自动回退

## 文件说明

- `Dockerfile`: 镜像构建文件
- `download-package.sh`: 下载和解压脚本
- `build.sh`: 智能构建脚本，支持多镜像源和本地镜像文件
- `save-base-image.sh`: 导出基础镜像为 tar 文件的辅助脚本
- `README.md`: 本说明文档
- `.dockerignore`: Docker 构建时忽略的文件
- `base-images/`: 本地镜像文件目录（不会被提交到 git）

## 故障排查

### 镜像无法拉取
- 检查镜像仓库地址是否正确
- 确认网络连接和认证信息
- 检查镜像标签是否存在

### 下载失败
- 检查 `PACKAGE_URL` 环境变量是否正确设置
- 确认 URL 可访问（网络连通性）
- 查看 Pod 日志：`kubectl logs <pod-name> -c package-downloader`

### 解压失败
- 确认下载的文件是有效的 tar 格式
- 检查文件是否完整下载
- 查看 initContainer 日志获取详细错误信息

## 版本历史

- v1.0.0: 初始版本，支持下载和解压 tar 包

