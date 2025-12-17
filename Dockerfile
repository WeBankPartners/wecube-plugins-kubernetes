FROM ccr.ccs.tencentyun.com/webankpartners/python:3.8.20-slim-bullseye
LABEL maintainer = "Webank CTB Team"
# 使用腾讯云镜像源
RUN sed -i 's/deb.debian.org/mirrors.tencentyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/mirrors.tencentyun.com/g' /etc/apt/sources.list
COPY api/wecubek8s/requirements.txt /tmp/requirements.txt
COPY api/wecubek8s/dist/* /tmp/
# Install && Clean up
RUN apt update && apt-get -y install gcc python3-dev swig libssl-dev libev-dev make && \
    pip3 install -i http://mirrors.tencentyun.com/pypi/simple/ --trusted-host mirrors.tencentyun.com setuptools wheel && \
    pip3 install -i http://mirrors.tencentyun.com/pypi/simple/ --trusted-host mirrors.tencentyun.com --no-build-isolation -r /tmp/requirements.txt && \
    pip3 install /tmp/*.whl && \
    rm -rf /root/.cache && apt autoclean && \
    rm -rf /tmp/* /var/lib/apt/* /var/cache/* && \
    apt purge -y `cat /var/log/apt/history.log|grep 'Install: '|tail -1| sed 's/Install://'| sed 's/\ /\n/g' | sed '/(/d' | sed '/)/d' | sed ':l;N;s/\n/ /;b l'`
# Use app:app to run gunicorn
RUN mkdir -p /etc/wecubek8s/
RUN mkdir -p /var/log/wecubek8s/
RUN mkdir -p /data/wecubek8s/records
COPY api/wecubek8s/etc /etc/wecubek8s
# RUN adduser --disabled-password app
# RUN chown -R app:app /etc/wecubek8s/
# RUN chown -R app:app /var/log/wecubek8s/
# USER app

# 设置环境变量限制 gevent threadpool 大小和使用 thread 解析器
ENV GEVENT_THREADPOOL_SIZE=10
ENV GEVENT_RESOLVER=thread

COPY build/start_all.sh /scripts/start_all.sh
RUN chmod +x /scripts/start_all.sh
CMD ["/bin/sh","-c","/scripts/start_all.sh"]