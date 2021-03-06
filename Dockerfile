FROM python:3.7-slim
LABEL maintainer = "Webank CTB Team"
# Install logrotate
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list
RUN sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list
COPY api/wecubek8s/requirements.txt /tmp/requirements.txt
COPY api/wecubek8s/dist/* /tmp/
# Install && Clean up
RUN apt update && apt-get -y install gcc python3-dev swig libssl-dev && \
    pip3 install -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r /tmp/requirements.txt && \
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
COPY build/start_all.sh /scripts/start_all.sh
RUN chmod +x /scripts/start_all.sh
CMD ["/bin/sh","-c","/scripts/start_all.sh"]