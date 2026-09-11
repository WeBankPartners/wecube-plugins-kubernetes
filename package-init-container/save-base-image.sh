#!/bin/bash
# 导出基础镜像为 tar 文件的辅助脚本
# 使用方法：./save-base-image.sh alpine:3.18

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <image:tag>"
    echo "Example: $0 alpine:3.18"
    echo ""
    echo "This script will:"
    echo "  1. Check if the image exists locally"
    echo "  2. If not, try to pull it"
    echo "  3. Export the image to base-images/<image-name>-<tag>.tar"
    exit 1
fi

IMAGE="$1"
BASE_IMAGES_DIR="base-images"

# 解析镜像名和标签
if [[ "$IMAGE" =~ : ]]; then
    IMAGE_NAME=$(echo "$IMAGE" | cut -d: -f1 | tr '/' '_' | tr ':' '_')
    IMAGE_TAG=$(echo "$IMAGE" | cut -d: -f2)
    OUTPUT_FILE="$BASE_IMAGES_DIR/${IMAGE_NAME}-${IMAGE_TAG}.tar"
else
    IMAGE_NAME=$(echo "$IMAGE" | tr '/' '_')
    OUTPUT_FILE="$BASE_IMAGES_DIR/${IMAGE_NAME}-latest.tar"
fi

# 创建目录
mkdir -p "$BASE_IMAGES_DIR"

echo "=========================================="
echo "Exporting Base Image"
echo "=========================================="
echo "Image: $IMAGE"
echo "Output: $OUTPUT_FILE"
echo "=========================================="

# 检查本地是否有镜像
if ! docker inspect "$IMAGE" &>/dev/null; then
    echo ""
    echo "Image not found locally, trying to pull..."
    if ! docker pull "$IMAGE"; then
        echo "✗ Failed to pull image: $IMAGE"
        echo "Please make sure you have access to the registry or the image exists."
        exit 1
    fi
    echo "✓ Image pulled successfully"
fi

echo ""
echo "Exporting image to $OUTPUT_FILE..."
if docker save "$IMAGE" -o "$OUTPUT_FILE"; then
    # 获取文件大小
    FILE_SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
    echo ""
    echo "=========================================="
    echo "✓ Image exported successfully!"
    echo "=========================================="
    echo "File: $OUTPUT_FILE"
    echo "Size: $FILE_SIZE"
    echo ""
    echo "Now you can build using:"
    echo "  ./build.sh"
    echo ""
    echo "The build script will automatically load this image file."
    echo "=========================================="
else
    echo ""
    echo "✗ Failed to export image"
    exit 1
fi



