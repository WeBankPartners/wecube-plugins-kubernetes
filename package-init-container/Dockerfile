# 基于 Alpine Linux，轻量级且包含必要的工具
# 支持通过构建参数指定基础镜像，解决镜像源访问问题
# 使用方法：docker build --build-arg BASE_IMAGE=alpine:3.18 .
# 可选镜像源：
# - 网易: hub-mirror.c.163.com/library/alpine:3.18
# - 阿里云: registry.cn-hangzhou.aliyuncs.com/library/alpine:3.18
# - 官方镜像: alpine:3.18
# 注意：如果本地已有镜像，直接使用镜像名（不带 registry 前缀）可以避免镜像加速器自动转换
ARG BASE_IMAGE=alpine:3.18
FROM ${BASE_IMAGE}

# 配置 Alpine 使用国内镜像源（加速 apk 包下载）
# 优先使用阿里云镜像源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

# 安装必要的工具：wget, curl, tar
# 这些工具用于下载和解压 package 文件
RUN apk add --no-cache \
    wget \
    curl \
    tar \
    bash \
    && rm -rf /var/cache/apk/*

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

