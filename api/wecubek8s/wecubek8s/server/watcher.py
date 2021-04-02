# coding=utf-8
from __future__ import absolute_import
import logging
import time
from threading import Event
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from talos.core import config
from talos.core import utils

from wecubek8s.server.wsgi_server import application
from wecubek8s.apps.model import api
from wecubek8s.common import wecube

LOG = logging.getLogger(__name__)
CONF = config.CONF


def notify_pod(event, cluster_id, data):
    LOG.info('event: %s from cluster: %s with data: %s', event, cluster_id, data)
    try:
        if event == 'POD.ADDED':
            client = wecube.WeCubeClient(CONF.wecube.base_url, None)
            client.login_subsystem()
            client.post(
                client.build_url('/platform/v1/operation-events'), {
                    "eventSeqNo": utils.generate_prefix_uuid("kubernetes-pod-"),
                    "eventType": event,
                    "sourceSubSystem": CONF.wecube.sub_system_code,
                    "operationKey": CONF.notify.pod_added,
                    "operationData": data['id'],
                    "operationUser": "plugin-kubernetes-watcher"
                })
        elif event == 'POD.DELETED':
            client = wecube.WeCubeClient(CONF.wecube.base_url, None)
            client.login_subsystem()
            client.post(
                client.build_url('/platform/v1/operation-events'), {
                    "eventSeqNo": utils.generate_prefix_uuid("kubernetes-pod-"),
                    "eventType": event,
                    "sourceSubSystem": CONF.wecube.sub_system_code,
                    "operationKey": CONF.notify.pod_deleted,
                    "operationData": data['id'],
                    "operationUser": "plugin-kubernetes-watcher"
                })
    except Exception as e:
        LOG.error('exception raised while notify pod: %s', data['id'])
        LOG.exception(e)


def watch_pod(cluster, event_stop):
    while not event_stop.is_set():
        try:
            api.Pod().watch(cluster, event_stop, notify_pod)
        except Exception as e:
            LOG.error('exception raised while watching pod from %s', cluster['id'])
            LOG.exception(e)
            time.sleep(0.5)


def cluster_equal(cluster1, cluster2):
    cluster1 = cluster1.copy()
    cluster2 = cluster2.copy()
    fields = ['name', 'displayName', 'correlation_id', 'created_by', 'created_time', 'updated_by', 'updated_time']
    for f in fields:
        cluster1.pop(f, None)
    for f in fields:
        cluster2.pop(f, None)
    return cluster1 == cluster2


def main():
    LOG.info('starting watcher')
    pool = PoolExecutor(100)
    cluster_maping = {}
    while True:
        latest_clusters = api.db_resource.Cluster().list()
        latest_cluster_maping = dict(
            zip([cluster['id'] for cluster in latest_clusters], [cluster for cluster in latest_clusters]))
        watching_cluster_ids = set(list(cluster_maping.keys()))
        latest_cluster_ids = set(list(latest_cluster_maping.keys()))
        new_cluster_ids = latest_cluster_ids - watching_cluster_ids
        del_cluster_ids = watching_cluster_ids - latest_cluster_ids
        mod_cluster_ids = latest_cluster_ids & watching_cluster_ids

        if new_cluster_ids:
            for cluster_id in new_cluster_ids:
                LOG.info('start watching pod from newly cluster: %s', cluster_id)
                cluster = latest_cluster_maping[cluster_id]
                event_stop = Event()
                pool.submit(watch_pod, cluster, event_stop)
                # add mapping
                cluster_maping[cluster_id] = (cluster, event_stop)
        if del_cluster_ids:
            for cluster_id in del_cluster_ids:
                LOG.info('stop watching pod from deleted cluster: %s', cluster_id)
                cluster, event_stop = cluster_maping[cluster_id]
                event_stop.set()
                del cluster_maping[cluster_id]

        if mod_cluster_ids:
            for cluster_id in mod_cluster_ids:
                cluster, event_stop = cluster_maping[cluster_id]
                latest_cluster = latest_cluster_maping[cluster_id]
                if not cluster_equal(latest_cluster, cluster):
                    LOG.info('stop watching pod from modified cluster: %s', cluster_id)
                    cluster, event_stop = cluster_maping[cluster_id]
                    event_stop.set()
                    del cluster_maping[cluster_id]
                    LOG.info('start watching pod from modified cluster: %s', cluster_id)
                    event_stop = Event()
                    pool.submit(watch_pod, latest_cluster, event_stop)
                    # add mapping
                    cluster_maping[cluster_id] = (latest_cluster, event_stop)
        time.sleep(1)

    pool.shutdown(True)


if __name__ == '__main__':
    main()
