FROM python:2.7
LABEL maintainer = "Webank CTB Team"
# Install logrotate
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    mkdir -p /app/wecube-plugins-kubernetes

WORKDIR /app/wecube-plugins-kubernetes/

COPY . .

RUN ls -la && \
    pip install -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r /app/wecube-plugins-kubernetes/requirements.txt && \
    chmod +x /app/wecube-plugins-kubernetes/bin/*.sh

EXPOSE 8999
ENTRYPOINT ["/app/wecube-plugins-kubernetes/bin/start.sh"]