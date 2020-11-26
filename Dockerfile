FROM python:2.7
LABEL maintainer = "Webank CTB Team"
# Install logrotate
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    mkdir -p /app/wecube-plugins-kubernetes

COPY ./* /app/wecube-plugins-kubernetes/

RUN pip install -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r /tmp/requirements.txt && \
    chmod +x /app/wecube-plugins-kubernetes/bin/*.sh

EXPOSE 8999
CMD ["/bin/sh","-c","/app/wecube-plugins-kubernetes/bin/start.sh"]