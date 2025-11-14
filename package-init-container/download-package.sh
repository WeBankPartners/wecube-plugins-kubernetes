#!/bin/bash
set -e

# 从环境变量获取 package URL
PACKAGE_URL="${PACKAGE_URL:-}"

if [ -z "$PACKAGE_URL" ]; then
    echo "Error: PACKAGE_URL environment variable is not set"
    exit 1
fi

echo "=========================================="
echo "Package Downloader InitContainer"
echo "=========================================="
echo "Downloading package from: $PACKAGE_URL"
echo "Target directory: /shared-data/diff-var-files"
echo "=========================================="

# 确保目标目录存在
cd /shared-data/diff-var-files

# 下载 tar 包
echo "Step 1: Downloading package..."
if command -v wget > /dev/null 2>&1; then
    echo "Using wget to download..."
    wget -q --show-progress -O package.tar "$PACKAGE_URL" || {
        echo "wget failed, trying curl..."
        curl -f -L -o package.tar "$PACKAGE_URL" || {
            echo "Error: Failed to download package"
            exit 1
        }
    }
elif command -v curl > /dev/null 2>&1; then
    echo "Using curl to download..."
    curl -f -L -o package.tar "$PACKAGE_URL" || {
        echo "Error: Failed to download package"
        exit 1
    }
else
    echo "Error: Neither wget nor curl is available"
    exit 1
fi

# 验证下载的文件是否存在且不为空
if [ ! -f package.tar ] || [ ! -s package.tar ]; then
    echo "Error: Downloaded file is empty or does not exist"
    exit 1
fi

echo "Step 2: Verifying package file..."
file_size=$(stat -c%s package.tar 2>/dev/null || stat -f%z package.tar 2>/dev/null || echo "0")
echo "Package file size: ${file_size} bytes"

# 解压 tar 包
echo "Step 3: Extracting package..."
tar -xf package.tar || {
    echo "Error: Failed to extract package"
    exit 1
}

# 清理 tar 文件
echo "Step 4: Cleaning up..."
rm -f package.tar

# 列出解压后的文件（用于调试）
echo "Step 5: Listing extracted files..."
ls -lah /shared-data/diff-var-files/ || true

echo "=========================================="
echo "Package downloaded and extracted successfully!"
echo "=========================================="

