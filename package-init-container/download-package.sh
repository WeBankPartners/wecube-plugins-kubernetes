#!/bin/bash
set -e

# 从环境变量获取 package URL 和认证信息
PACKAGE_URL="${PACKAGE_URL:-}"
PACKAGE_USERNAME="${PACKAGE_USERNAME:-}"
PACKAGE_PASSWORD="${PACKAGE_PASSWORD:-}"

if [ -z "$PACKAGE_URL" ]; then
    echo "Error: PACKAGE_URL environment variable is not set"
    exit 1
fi

echo "=========================================="
echo "Package Downloader InitContainer"
echo "=========================================="
echo "Downloading package from: $PACKAGE_URL"
echo "Target directory: /shared-data/diff-var-files"
if [ -n "$PACKAGE_USERNAME" ]; then
    echo "Authentication: Enabled (username: $PACKAGE_USERNAME)"
else
    echo "Authentication: Disabled (anonymous download)"
fi
echo "=========================================="

# 确保目标目录存在
cd /shared-data/diff-var-files

# 下载 tar 包（带重试机制）
echo "Step 1: Downloading package..."

# 最大重试次数
MAX_RETRIES=3
RETRY_DELAY=5

# 检测 URL 类型：MinIO/S3 或普通 HTTP
detect_url_type() {
    local url="$1"
    # 检测是否是 MinIO/S3 URL（端口 9000 或包含 s3/minio 关键字）
    if echo "$url" | grep -qE ':(9000|9001)/|s3\.|minio\.|amazonaws\.com'; then
        echo "s3"
    else
        echo "http"
    fi
}

# MinIO/S3 下载函数
download_from_s3() {
    local url="$1"
    local output="$2"
    local retry_count=0
    
    # 解析 MinIO URL: http://host:port/bucket/path/to/file
    local endpoint_url=""
    local bucket=""
    local object_key=""
    
    if [[ "$url" =~ ^(https?://[^/]+)/([^/]+)/(.+)$ ]]; then
        endpoint_url="${BASH_REMATCH[1]}"
        bucket="${BASH_REMATCH[2]}"
        object_key="${BASH_REMATCH[3]}"
    else
        echo "Error: Cannot parse MinIO/S3 URL: $url"
        return 1
    fi
    
    echo "Detected MinIO/S3 storage:"
    echo "  Endpoint: $endpoint_url"
    echo "  Bucket: $bucket"
    echo "  Object: $object_key"
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        echo "Download attempt $((retry_count + 1))/$MAX_RETRIES..."
        
        # 方法 1: 尝试使用 aws-cli
        if command -v aws > /dev/null 2>&1; then
            echo "Using AWS CLI to download from MinIO..."
            echo "AWS CLI version: $(aws --version 2>&1)"
            if [ -n "$PACKAGE_USERNAME" ] && [ -n "$PACKAGE_PASSWORD" ]; then
                export AWS_ACCESS_KEY_ID="$PACKAGE_USERNAME"
                export AWS_SECRET_ACCESS_KEY="$PACKAGE_PASSWORD"
                
                echo "Executing: aws s3 cp --endpoint-url=$endpoint_url s3://${bucket}/${object_key} $output"
                if aws s3 cp --endpoint-url="$endpoint_url" "s3://${bucket}/${object_key}" "$output" 2>&1; then
                    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
                    echo "Download successful via AWS CLI!"
                    return 0
                else
                    echo "AWS CLI Error details:"
                    aws s3 cp --endpoint-url="$endpoint_url" "s3://${bucket}/${object_key}" "$output" 2>&1 || true
                fi
                unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
            else
                echo "Warning: No credentials provided for MinIO/S3"
            fi
            echo "AWS CLI download failed"
        else
            echo "AWS CLI not found in container"
        fi
        
        # 方法 2: 尝试使用 mc (MinIO Client)
        if command -v mc > /dev/null 2>&1; then
            echo "Using MinIO Client (mc) to download..."
            echo "MinIO Client version: $(mc --version 2>&1)"
            if [ -n "$PACKAGE_USERNAME" ] && [ -n "$PACKAGE_PASSWORD" ]; then
                # 配置 mc alias（使用临时别名避免冲突）
                local alias_name="temp-minio-$$"
                echo "Configuring mc alias: $alias_name -> $endpoint_url"
                if mc alias set "$alias_name" "$endpoint_url" "$PACKAGE_USERNAME" "$PACKAGE_PASSWORD" 2>&1; then
                    echo "Executing: mc cp ${alias_name}/${bucket}/${object_key} $output"
                    if mc cp "${alias_name}/${bucket}/${object_key}" "$output" 2>&1; then
                        mc alias remove "$alias_name" 2>/dev/null || true
                        echo "Download successful via MinIO Client!"
                        return 0
                    else
                        echo "MinIO Client Error details:"
                        mc cp "${alias_name}/${bucket}/${object_key}" "$output" 2>&1 || true
                    fi
                    mc alias remove "$alias_name" 2>/dev/null || true
                else
                    echo "Failed to set mc alias. Error:"
                    mc alias set "$alias_name" "$endpoint_url" "$PACKAGE_USERNAME" "$PACKAGE_PASSWORD" 2>&1 || true
                fi
            fi
            echo "MinIO Client download failed"
        else
            echo "MinIO Client (mc) not found in container"
        fi
        
        # 方法 3: 尝试使用 s3cmd
        if command -v s3cmd > /dev/null 2>&1; then
            echo "Using s3cmd to download..."
            if [ -n "$PACKAGE_USERNAME" ] && [ -n "$PACKAGE_PASSWORD" ]; then
                # 创建临时配置文件
                local s3cfg="/tmp/s3cfg-$$"
                cat > "$s3cfg" << EOF
[default]
access_key = $PACKAGE_USERNAME
secret_key = $PACKAGE_PASSWORD
host_base = ${endpoint_url#http://}
host_base = ${host_base#https://}
host_bucket = %(bucket)s.${host_base}
use_https = False
EOF
                if s3cmd -c "$s3cfg" --host="$endpoint_url" get "s3://${bucket}/${object_key}" "$output" 2>&1; then
                    rm -f "$s3cfg"
                    echo "Download successful via s3cmd!"
                    return 0
                fi
                rm -f "$s3cfg"
            fi
            echo "s3cmd download failed"
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            echo "Retrying in ${RETRY_DELAY} seconds..."
            sleep $RETRY_DELAY
        fi
    done
    
    echo "Error: All MinIO/S3 download methods failed"
    return 1
}

# HTTP/HTTPS 下载函数（原有逻辑）
download_from_http() {
    local url="$1"
    local output="$2"
    local retry_count=0
    
    # 构建认证参数
    local auth_param=""
    if [ -n "$PACKAGE_USERNAME" ] && [ -n "$PACKAGE_PASSWORD" ]; then
        auth_param="$PACKAGE_USERNAME:$PACKAGE_PASSWORD"
    fi
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        echo "Download attempt $((retry_count + 1))/$MAX_RETRIES..."
        
        # 首先检查 URL 是否可访问
        if command -v curl > /dev/null 2>&1; then
            echo "Checking URL accessibility..."
            if [ -n "$auth_param" ]; then
                http_code=$(curl -s -o /dev/null -w "%{http_code}" -u "$auth_param" "$url" || echo "000")
            else
                http_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || echo "000")
            fi
            echo "HTTP status code: $http_code"
            
            if [ "$http_code" = "401" ]; then
                echo "Error: 401 Unauthorized - Authentication failed"
                echo "Please check username and password"
                exit 1
            elif [ "$http_code" = "403" ]; then
                echo "Error: 403 Forbidden - Access denied"
                exit 1
            elif [ "$http_code" = "404" ]; then
                echo "Error: 404 Not Found - The package file does not exist"
                echo "URL: $url"
                exit 1
            elif [ "$http_code" = "000" ]; then
                echo "Warning: Cannot connect to server, will retry..."
            fi
        fi
        
        # 尝试使用 wget 下载
        if command -v wget > /dev/null 2>&1; then
            echo "Using wget to download..."
            if [ -n "$auth_param" ]; then
                if wget -q --show-progress --user="$PACKAGE_USERNAME" --password="$PACKAGE_PASSWORD" -O "$output" "$url"; then
                    echo "Download successful!"
                    return 0
                fi
            else
                if wget -q --show-progress -O "$output" "$url"; then
                    echo "Download successful!"
                    return 0
                fi
            fi
            echo "wget failed"
        fi
        
        # 尝试使用 curl 下载
        if command -v curl > /dev/null 2>&1; then
            echo "Using curl to download..."
            if [ -n "$auth_param" ]; then
                if curl -f -L -S --retry 2 --retry-delay 3 -u "$auth_param" -o "$output" "$url"; then
                    echo "Download successful!"
                    return 0
                fi
            else
                if curl -f -L -S --retry 2 --retry-delay 3 -o "$output" "$url"; then
                    echo "Download successful!"
                    return 0
                fi
            fi
            echo "curl failed"
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            echo "Retrying in ${RETRY_DELAY} seconds..."
            sleep $RETRY_DELAY
        fi
    done
    
    echo "Error: Failed to download package after $MAX_RETRIES attempts"
    return 1
}

download_with_retry() {
    local url="$1"
    local output="$2"
    local url_type=$(detect_url_type "$url")
    
    echo "URL Type: $url_type"
    
    if [ "$url_type" = "s3" ]; then
        download_from_s3 "$url" "$output"
    else
        download_from_http "$url" "$output"
    fi
}

# 执行下载
if ! download_with_retry "$PACKAGE_URL" "package.tar"; then
    echo ""
    echo "=========================================="
    echo "DOWNLOAD FAILED - TROUBLESHOOTING GUIDE"
    echo "=========================================="
    echo "Package URL: $PACKAGE_URL"
    echo ""
    echo "Common solutions:"
    echo "1. Check if the file exists on the storage server"
    echo "2. Verify authentication credentials are correct"
    echo "3. Check if the URL has expired (pre-signed URLs)"
    echo "4. Verify network connectivity from Pod to storage server"
    echo "5. Verify MinIO/S3 bucket has appropriate permissions"
    echo "6. Check storage server logs for access denied reasons"
    echo "=========================================="
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

