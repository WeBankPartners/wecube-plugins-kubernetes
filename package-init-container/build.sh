#!/bin/bash
# 构建脚本 - 支持自动尝试多个镜像源并推送到私有仓库

set -e

# 默认值
IMAGE_NAME="${IMAGE_NAME:-package-init-container}"
# 默认使用固定版本 1.0.0，可通过环境变量 IMAGE_TAG 覆盖
# 例如：IMAGE_TAG=1.0.1 ./build.sh 或 IMAGE_TAG=1.0.0-$(date +%Y%m%d) ./build.sh
IMAGE_TAG="${IMAGE_TAG:-1.0.0}"
REGISTRY="${REGISTRY:-}"
# 是否自动尝试多个镜像源
AUTO_TRY_MIRRORS="${AUTO_TRY_MIRRORS:-true}"

# 私有仓库配置
# 使用 HTTP 协议，端口 8082（需要在 Docker 和 K8s 节点配置 insecure-registries）
PRIVATE_REGISTRY="${PRIVATE_REGISTRY:-***REMOVED***}" # dev环境私有仓库地址
# PRIVATE_REGISTRY="${PRIVATE_REGISTRY:-***REMOVED***}" # sit环境私有仓库地址


REGISTRY_USERNAME="${REGISTRY_USERNAME:-***REMOVED***}"
REGISTRY_PASSWORD="${REGISTRY_PASSWORD:-***REMOVED***@123}"
# 是否推送到私有仓库
PUSH_TO_REGISTRY="${PUSH_TO_REGISTRY:-true}"

# 如果指定了仓库地址，则添加到镜像名前
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
else
    FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"
fi

# 私有仓库的完整镜像名
PRIVATE_IMAGE_NAME="${PRIVATE_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

# 定义多个可用的镜像源（按优先级排序）
# 优先使用本地已有的镜像，直接使用镜像名（不带 registry 前缀）可以避免镜像加速器自动转换
MIRRORS=(
    "alpine:3.18"  # 优先使用本地镜像（如果存在），避免镜像加速器自动转换
    "docker.io/library/alpine:3.18"  # 备用：明确指定官方源
    "alpine:3.22"
    "docker.io/library/alpine:3.22"
    "registry.cn-hangzhou.aliyuncs.com/library/alpine:3.22"
    "docker.mirrors.ustc.edu.cn/library/alpine:3.22"
    "hub-mirror.c.163.com/library/alpine:3.22"
    "registry.docker-cn.com/library/alpine:3.22"
)

# 如果用户指定了 BASE_IMAGE，直接使用
if [ -n "$BASE_IMAGE" ]; then
    MIRRORS=("$BASE_IMAGE")
    AUTO_TRY_MIRRORS=false
fi

echo "=========================================="
echo "Building Package InitContainer Image"
echo "=========================================="
echo "Image: $FULL_IMAGE_NAME"
echo "=========================================="

# 本地镜像文件目录
BASE_IMAGES_DIR="base-images"

# 加载本地镜像文件（如果存在）
load_local_image_files() {
    if [ ! -d "$BASE_IMAGES_DIR" ]; then
        return 0
    fi
    
    echo ""
    echo "Checking for local image files in $BASE_IMAGES_DIR/..."
    local loaded=false
    
    # 查找所有 .tar 文件
    for tar_file in "$BASE_IMAGES_DIR"/*.tar; do
        if [ -f "$tar_file" ]; then
            echo "Found local image file: $tar_file"
            echo "Loading image from $tar_file..."
            if docker load -i "$tar_file" 2>&1; then
                echo "✓ Successfully loaded image from $tar_file"
                loaded=true
            else
                echo "✗ Failed to load image from $tar_file"
            fi
        fi
    done
    
    if [ "$loaded" = "true" ]; then
        echo ""
        echo "Local images loaded. Will use them for building."
    fi
}

# 加载本地镜像文件
load_local_image_files

# 检查本地镜像是否存在
check_local_image() {
    local image=$1
    # 如果镜像名不包含 registry 地址，检查本地是否存在
    if [[ ! "$image" =~ ^[^/]+\.(com|cn|org|io)/ ]]; then
        if docker inspect "$image" &>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# 构建函数
build_with_mirror() {
    local mirror=$1
    echo ""
    echo "Trying base image: $mirror"
    echo "----------------------------------------"
    
    # 检查本地是否有该镜像
    if docker inspect "$mirror" &>/dev/null; then
        echo "Local image found, will use local image to avoid mirror conversion"
        local build_image="$mirror"
        
        # 如果镜像名不包含 registry，给它打上 docker.io 标签以避免镜像加速器转换
        if [[ ! "$mirror" =~ ^[^/]+\.(com|cn|org|io|net)/ ]] && [[ ! "$mirror" =~ ^docker\.io/ ]]; then
            build_image="docker.io/library/$mirror"
            # 检查是否已经有这个标签，如果没有则创建
            if ! docker inspect "$build_image" &>/dev/null; then
                echo "Tagging local image as $build_image to avoid mirror conversion"
                docker tag "$mirror" "$build_image" 2>/dev/null || true
            fi
            echo "Using full registry path: $build_image (to avoid mirror conversion)"
        fi
        
        # 尝试构建
        if docker build --build-arg BASE_IMAGE="$build_image" -t "$FULL_IMAGE_NAME" . 2>&1; then
            echo ""
            echo "=========================================="
            echo "✓ Build completed successfully!"
            echo "=========================================="
            echo "Used base image: $build_image (local)"
            return 0
        else
            echo "Failed with full registry path, trying original image name..."
            # 如果使用完整路径失败，尝试使用原始镜像名
            if docker build --build-arg BASE_IMAGE="$mirror" -t "$FULL_IMAGE_NAME" . 2>&1; then
                echo ""
                echo "=========================================="
                echo "✓ Build completed successfully!"
                echo "=========================================="
                echo "Used base image: $mirror (local)"
                return 0
            else
                echo ""
                echo "✗ Failed with: $mirror"
                return 1
            fi
        fi
    else
        echo "Local image not found, will try to pull if needed"
        # 如果本地没有镜像，尝试拉取
        # 对于不带 registry 前缀的镜像名，Docker 可能会被镜像加速器转换
        # 但我们可以先尝试，如果失败会尝试下一个镜像源
        if docker build --build-arg BASE_IMAGE="$mirror" -t "$FULL_IMAGE_NAME" . 2>&1; then
            echo ""
            echo "=========================================="
            echo "✓ Build completed successfully!"
            echo "=========================================="
            echo "Used base image: $mirror"
            return 0
        else
            echo ""
            echo "✗ Failed with: $mirror"
            return 1
        fi
    fi
}

# 如果启用自动尝试，遍历所有镜像源
if [ "$AUTO_TRY_MIRRORS" = "true" ]; then
    BUILD_SUCCESS=false
    for mirror in "${MIRRORS[@]}"; do
        if build_with_mirror "$mirror"; then
            BUILD_SUCCESS=true
            break
        fi
        echo ""
        echo "Trying next mirror..."
        sleep 1
    done
    
    if [ "$BUILD_SUCCESS" = "false" ]; then
        echo ""
        echo "=========================================="
        echo "✗ All mirrors failed!"
        echo "=========================================="
        echo ""
        echo "Please try one of the following solutions:"
        echo ""
        echo "1. Configure Docker registry mirror:"
        echo "   Edit ~/.docker/daemon.json (macOS) or /etc/docker/daemon.json (Linux)"
        echo "   Add: { \"registry-mirrors\": [\"https://your-mirror-id.mirror.aliyuncs.com\"] }"
        echo "   Then restart Docker"
        echo ""
        echo "2. Manually pull the image first:"
        echo "   docker pull alpine:3.22"
        echo "   export BASE_IMAGE=alpine:3.22"
        echo "   ./build.sh"
        echo ""
        echo "3. Use a local image:"
        echo "   docker images | grep alpine"
        echo "   export BASE_IMAGE=<your-local-alpine-image>"
        echo "   ./build.sh"
        echo ""
        echo "4. Set AUTO_TRY_MIRRORS=false to disable auto-try:"
        echo "   export AUTO_TRY_MIRRORS=false"
        echo "   export BASE_IMAGE=your-preferred-mirror"
        echo "   ./build.sh"
        echo "=========================================="
        exit 1
    fi
else
    # 只尝试指定的镜像
    if [ -n "$BASE_IMAGE" ]; then
        if ! build_with_mirror "$BASE_IMAGE"; then
            exit 1
        fi
    else
        # 使用默认镜像
        if ! build_with_mirror "${MIRRORS[0]}"; then
            exit 1
        fi
    fi
fi

# 导出镜像为 tar 文件
TAR_FILE="${IMAGE_NAME}-${IMAGE_TAG}.tar"
echo ""
echo "=========================================="
echo "Exporting image to tar file..."
echo "=========================================="
echo "Exporting $FULL_IMAGE_NAME to $TAR_FILE..."

if docker save "$FULL_IMAGE_NAME" -o "$TAR_FILE"; then
    # 获取文件大小
    TAR_SIZE=$(du -h "$TAR_FILE" | cut -f1)
    echo ""
    echo "=========================================="
    echo "✓ Image exported successfully!"
    echo "=========================================="
    echo "Tar file: $TAR_FILE"
    echo "Size: $TAR_SIZE"
    echo "Location: $(pwd)/$TAR_FILE"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "✗ Failed to export image to tar file!"
    echo "=========================================="
    exit 1
fi

# 推送到私有仓库
if [ "$PUSH_TO_REGISTRY" = "true" ]; then
    echo ""
    echo "=========================================="
    echo "Pushing image to private registry..."
    echo "=========================================="
    echo "Registry: $PRIVATE_REGISTRY"
    echo "Image: $PRIVATE_IMAGE_NAME"
    echo ""
    
    # 登录到私有仓库
    echo "Logging in to registry..."
    if echo "$REGISTRY_PASSWORD" | docker login "$PRIVATE_REGISTRY" -u "$REGISTRY_USERNAME" --password-stdin; then
        echo "✓ Login successful!"
    else
        echo "✗ Failed to login to registry!"
        echo "You can manually push the image later with:"
        echo "  docker login $PRIVATE_REGISTRY -u $REGISTRY_USERNAME"
        echo "  docker tag $FULL_IMAGE_NAME $PRIVATE_IMAGE_NAME"
        echo "  docker push $PRIVATE_IMAGE_NAME"
        exit 1
    fi
    
    echo ""
    echo "Tagging image for private registry..."
    if docker tag "$FULL_IMAGE_NAME" "$PRIVATE_IMAGE_NAME"; then
        echo "✓ Image tagged successfully!"
    else
        echo "✗ Failed to tag image!"
        exit 1
    fi
    
    echo ""
    echo "Pushing image to registry..."
    if docker push "$PRIVATE_IMAGE_NAME"; then
        echo ""
        echo "=========================================="
        echo "✓ Image pushed successfully!"
        echo "=========================================="
        echo "Image: $PRIVATE_IMAGE_NAME"
        echo "Registry: $PRIVATE_REGISTRY"
        echo ""
        echo "You can now use this image in Kubernetes:"
        echo "  image: $PRIVATE_IMAGE_NAME"
        echo "=========================================="
    else
        echo ""
        echo "=========================================="
        echo "✗ Failed to push image to registry!"
        echo "=========================================="
        echo "You can manually push the image later with:"
        echo "  docker push $PRIVATE_IMAGE_NAME"
        exit 1
    fi
    
    # 登出
    docker logout "$PRIVATE_REGISTRY" 2>/dev/null || true
else
    echo ""
    echo "=========================================="
    echo "Skipping push to registry (PUSH_TO_REGISTRY=false)"
    echo "=========================================="
    echo ""
    echo "To push the image manually, run:"
    echo "  docker login $PRIVATE_REGISTRY -u $REGISTRY_USERNAME"
    echo "  docker tag $FULL_IMAGE_NAME $PRIVATE_IMAGE_NAME"
    echo "  docker push $PRIVATE_IMAGE_NAME"
fi

echo ""
echo "To load the tar file on another machine, run:"
echo "  docker load -i $TAR_FILE"
echo "=========================================="

