#!/bin/bash

# wecube plugins kubernetes stop

PID=`ps -ef | grep python | grep -v grep | awk -F " " '{print $2}'`

echo "wating"
kill -9 $PID
echo "done"

