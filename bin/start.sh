#!/bin/bash

# start wecube plugins kubernetes
echo "kubernetes plugins starting "

mkdir ../log
PORT=`cat ../conf/application.conf | grep -v "^#" | grep serverport | awk -F "=" '{print $2}'`

python ../manager.py runserver 0.0.0.0:$PORT >> log/service.log

echo "done"
