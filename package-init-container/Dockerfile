# 基于 Alpine Linux，轻量级且包含必要的工具
# 直接使用 alpine:3.18，兼容老版本 Docker
# 如果需要使用其他镜像源，可以先手动 tag：
# docker tag <mirror-image> alpine:3.18
FROM alpine:3.18

# 配置 Alpine 使用腾讯云镜像源（内网可访问）
RUN echo "https://mirrors.tencent.com/alpine/v3.18/main" > /etc/apk/repositories && \
    echo "https://mirrors.tencent.com/alpine/v3.18/community" >> /etc/apk/repositories

# 安装必要的工具：wget, curl, tar, aws-cli, mc (MinIO Client)
# 这些工具用于下载和解压 package 文件
# aws-cli 和 mc 用于从 MinIO/S3 下载文件
# 使用 --timeout 参数避免长时间卡住
RUN apk add --no-cache --timeout 30 \
    wget \
    curl \
    tar \
    bash \
    python3 \
    py3-pip \
    && rm -rf /var/cache/apk/*

# 安装 AWS CLI（用于 MinIO/S3 下载）
# 优先使用腾讯云镜像加速安装
RUN pip3 install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple/ awscli && \
    aws --version

# 安装 MinIO Client（mc）作为备用方案
# 优先使用国内源，设置更短的超时时间避免卡死
# 注意：如果网络环境无法下载 mc，会跳过此步骤，仅使用 AWS CLI
RUN set -e; \
    echo "Downloading MinIO Client..."; \
    MC_DOWNLOADED=false; \
    # 尝试 1: 国内 CDN 镜像（最快）
    (wget --timeout=5 --tries=1 -q http://dl.minio.org.cn/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc 2>/dev/null && MC_DOWNLOADED=true && echo "Downloaded from dl.minio.org.cn") || \
    # 尝试 2: MinIO 官方源
    (wget --timeout=5 --tries=1 -q https://dl.min.io/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc 2>/dev/null && MC_DOWNLOADED=true && echo "Downloaded from dl.min.io") || \
    # 如果都失败，创建占位符
    (echo "Warning: Failed to download MinIO Client, will rely on AWS CLI only" && \
     echo '#!/bin/bash' > /usr/local/bin/mc && \
     echo 'echo "MinIO Client not available"' >> /usr/local/bin/mc && \
     echo 'exit 1' >> /usr/local/bin/mc); \
    chmod +x /usr/local/bin/mc || true; \
    /usr/local/bin/mc --version 2>/dev/null || echo "MC not installed, AWS CLI will be used"

# 创建目标目录
RUN mkdir -p /shared-data/diff-var-files

# 复制下载脚本
COPY download-package.sh /usr/local/bin/download-package.sh
RUN chmod +x /usr/local/bin/download-package.sh

# 设置工作目录
WORKDIR /shared-data/diff-var-files

# 默认入口点：执行下载脚本
# 脚本会从环境变量 PACKAGE_URL 读取下载地址
ENTRYPOINT ["/usr/local/bin/download-package.sh"]

