#!/bin/bash

# ============================================
# 将本地 tar 镜像包推送到远程私有仓库
# ============================================

set -e  # 遇到错误立即退出

# 私有仓库配置（直接写死）
PRIVATE_REGISTRY="***REMOVED***"
REGISTRY_USERNAME="***REMOVED***"
REGISTRY_PASSWORD="***REMOVED***@123"

# 镜像信息
IMAGE_NAME="package-init-container"
IMAGE_TAG="1.0.0"
TAR_FILE="${IMAGE_NAME}-${IMAGE_TAG}.tar"

# 本地镜像名（从 tar 加载后的名称）
LOCAL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

# 远程镜像名（带仓库前缀）
REMOTE_IMAGE="${PRIVATE_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "=========================================="
echo "Push Image to Private Registry"
echo "=========================================="
echo "Script: $(basename $0)"
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
echo ""

# 检查 tar 文件是否存在
if [ ! -f "$TAR_FILE" ]; then
    echo "✗ Error: Tar file not found: $TAR_FILE"
    echo ""
    echo "Please make sure the tar file exists in current directory:"
    echo "  $(pwd)/$TAR_FILE"
    echo ""
    echo "You can generate it by running:"
    echo "  ./build.sh"
    exit 1
fi

# 获取 tar 文件大小
TAR_SIZE=$(du -h "$TAR_FILE" | cut -f1)
echo "✓ Found tar file: $TAR_FILE ($TAR_SIZE)"
echo ""

# 加载镜像
echo "=========================================="
echo "Loading image from tar file..."
echo "=========================================="
echo "Loading $TAR_FILE..."
echo ""

if docker load -i "$TAR_FILE"; then
    echo ""
    echo "✓ Image loaded successfully!"
else
    echo ""
    echo "✗ Failed to load image from tar file!"
    exit 1
fi

echo ""

# 查看加载的镜像
echo "=========================================="
echo "Verifying loaded image..."
echo "=========================================="
docker images | grep "$IMAGE_NAME" | grep "$IMAGE_TAG" || {
    echo "✗ Image not found after loading!"
    echo "Expected image: $LOCAL_IMAGE"
    exit 1
}
echo ""

# 登录到私有仓库
echo "=========================================="
echo "Logging in to private registry..."
echo "=========================================="
echo "Registry: $PRIVATE_REGISTRY"
echo "Username: $REGISTRY_USERNAME"
echo ""

if echo "$REGISTRY_PASSWORD" | docker login "$PRIVATE_REGISTRY" -u "$REGISTRY_USERNAME" --password-stdin > /dev/null 2>&1; then
    echo "✓ Login successful!"
else
    echo "✗ Failed to login to registry!"
    echo ""
    echo "Please check:"
    echo "  1. Registry address: $PRIVATE_REGISTRY"
    echo "  2. Username/Password: $REGISTRY_USERNAME / ***"
    echo "  3. Network connectivity: curl http://$PRIVATE_REGISTRY/"
    echo "  4. Docker insecure-registries configuration"
    echo ""
    echo "To configure insecure-registries, add to /etc/docker/daemon.json:"
    echo '  {'
    echo '    "insecure-registries": ["'$PRIVATE_REGISTRY'"]'
    echo '  }'
    echo ""
    echo "Then restart Docker: sudo systemctl restart docker"
    exit 1
fi

echo ""

# 标记镜像
echo "=========================================="
echo "Tagging image for private registry..."
echo "=========================================="
echo "Source: $LOCAL_IMAGE"
echo "Target: $REMOTE_IMAGE"
echo ""

if docker tag "$LOCAL_IMAGE" "$REMOTE_IMAGE"; then
    echo "✓ Image tagged successfully!"
else
    echo "✗ Failed to tag image!"
    exit 1
fi

echo ""

# 推送镜像
echo "=========================================="
echo "Pushing image to registry..."
echo "=========================================="
echo "Image: $REMOTE_IMAGE"
echo "Registry: $PRIVATE_REGISTRY"
echo ""
echo "This may take a few minutes..."
echo ""

if docker push "$REMOTE_IMAGE"; then
    echo ""
    echo "=========================================="
    echo "✓ SUCCESS!"
    echo "=========================================="
    echo "Image pushed successfully to private registry!"
    echo ""
    echo "Image Details:"
    echo "  - Remote Image: $REMOTE_IMAGE"
    echo "  - Registry: $PRIVATE_REGISTRY"
    echo "  - Tag: $IMAGE_TAG"
    echo ""
    echo "You can now use this image in Kubernetes:"
    echo "  ---"
    echo "  apiVersion: v1"
    echo "  kind: Pod"
    echo "  metadata:"
    echo "    name: test-pod"
    echo "  spec:"
    echo "    initContainers:"
    echo "    - name: package-init"
    echo "      image: $REMOTE_IMAGE"
    echo "  ---"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "✗ FAILED!"
    echo "=========================================="
    echo "Failed to push image to registry!"
    echo ""
    echo "Common issues:"
    echo "  1. Network connectivity problem"
    echo "  2. Authentication failed"
    echo "  3. Insufficient permissions"
    echo "  4. Registry storage full"
    echo ""
    echo "You can try manually:"
    echo "  docker push $REMOTE_IMAGE"
    exit 1
fi

# 登出
echo ""
echo "Logging out from registry..."
docker logout "$PRIVATE_REGISTRY" > /dev/null 2>&1 || true
echo "✓ Logged out"

echo ""
echo "=========================================="
echo "Script completed at $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

