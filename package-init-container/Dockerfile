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
RUN pip3 install --no-cache-dir awscli

# 安装 MinIO Client（mc）作为备用方案
RUN wget -q https://dl.min.io/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc && \
    chmod +x /usr/local/bin/mc

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

