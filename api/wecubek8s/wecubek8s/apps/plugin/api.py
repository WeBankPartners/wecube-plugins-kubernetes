# coding=utf-8

from __future__ import absolute_import

import logging

from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import k8s
from wecubek8s.common import exceptions
from wecubek8s.common import const
from wecubek8s.db import resource as db_resource
from wecubek8s.apps.plugin import utils as api_utils

CONF = config.CONF
LOG = logging.getLogger(__name__)


class Cluster:
    def apply(self, data):
        cluster_name = data.get('name')
        LOG.info('Applying cluster: %s', cluster_name)
        
        # 注意：如果客户端发送的 token 是加密格式 {cipher_a}xxx，
        # controller 层已经解密处理过了，这里接收到的应该是明文
        
        cluster_info = db_resource.Cluster().list({'name': cluster_name})
        result = None
        if not cluster_info:
            LOG.info('Creating new cluster: %s', cluster_name)
            data['id'] = 'cluster-' + cluster_name
            result = db_resource.Cluster().create(data)
        else:
            LOG.info('Updating existing cluster: %s', cluster_name)
            cluster_info = cluster_info[0]
            # for token decryption
            data['id'] = cluster_info['id']
            
            # 记录哪些字段会被更新
            update_fields = list(data.keys())
            LOG.info('Fields to update for cluster %s: %s', cluster_name, update_fields)
            if 'token' in data:
                LOG.info('Token field will be updated and re-encrypted with guid: %s', data['id'])
            else:
                LOG.info('Token field not in update data, existing token will be kept')
            
            result_before, result = db_resource.Cluster().update(cluster_info['id'], data)
            LOG.info('Successfully updated cluster: %s', cluster_name)
        return result

    def remove(self, data):
        cluster_info = db_resource.Cluster().list({'name': data['name']})
        result = {'id': '', 'name': '', 'correlation_id': ''}
        if cluster_info:
            cluster_info = cluster_info[0]
            ref_count, refs = db_resource.Cluster().delete(cluster_info['id'])
            result = refs[0]
        return result


class Deployment:
    def to_resource(self, k8s_client, data, cluster_info):
        resource_id = data['correlation_id']
        resource_name = api_utils.escape_name(data['name'])
        resource_namespace = data['namespace']
        resource_tags = api_utils.convert_tag(data.get('tags', []))
        resource_tags[const.Tag.DEPLOYMENT_ID_TAG] = resource_id
        replicas = data['replicas']
        pod_spec_affinity = api_utils.convert_affinity(data['affinity'], const.Tag.POD_AFFINITY_TAG, data['name'])
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        # 使用 escape_label_value 确保标签值符合 Kubernetes 规范
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = api_utils.escape_label_value(data['name'])
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = api_utils.escape_label_value(data['name'])
        
        # 添加 correlation_id 和 instanceId 作为 Pod 标签
        if data.get('correlation_id'):
            pod_spec_tags['correlation_id'] = api_utils.escape_label_value(data['correlation_id'])
        if data.get('instanceId'):
            pod_spec_tags['instanceId'] = api_utils.escape_label_value(data['instanceId'])
        
        pod_spec_envs = api_utils.convert_env(data.get('envs', []))
        
        # 自动注入 Kubernetes Downward API 环境变量
        pod_spec_envs.extend([
            {
                'name': 'HOST_IP',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'status.hostIP'
                    }
                }
            },
            {
                'name': 'POD_IP',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'status.podIP'
                    }
                }
            },
            {
                'name': 'POD_NAME',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'metadata.name'
                    }
                }
            }
        ])
        
        pod_spec_src_vols, pod_spec_mnt_vols = api_utils.convert_volume(data.get('volumes', []))
        
        # 自动添加 /logs hostPath 挂载（基于传入的 deployment_path 参数）
        deployment_path = data.get('deployment_path')
        if deployment_path:
            # 确保路径以 / 结尾
            if not deployment_path.endswith('/'):
                deployment_path += '/'
            # 构建宿主机日志路径：deployment_path + logs
            host_log_path = deployment_path + 'logs'
            
            # 添加 hostPath volume
            log_volume_name = 'instance-logs'
            pod_spec_src_vols.append({
                'name': log_volume_name,
                'hostPath': {
                    'path': host_log_path,
                    'type': 'DirectoryOrCreate'
                }
            })
            
            # 添加 volume mount 到容器的 /logs
            pod_spec_mnt_vols.append({
                'name': log_volume_name,
                'mountPath': '/logs',
                'readOnly': False
            })
            
            LOG.info('Auto-mounted host path %s to /logs', host_log_path)
        
        pod_spec_limit = api_utils.convert_resource_limit(data.get('cpu', None), data.get('memory', None))
        
        # 从数据库的 cluster_info 中读取私有仓库地址
        private_registry = cluster_info.get('private_registry', '')
        
        # 构建完整的镜像地址（拼接私有仓库地址）
        image_name = data['image_name'].strip()
        if private_registry:
            # 如果配置了私有仓库，拼接私有仓库地址
            full_image_name = f"{private_registry}/{image_name}"
        else:
            # 否则直接使用原始镜像名
            full_image_name = image_name
        
        # 构建 images 数组格式（兼容原有的 convert_container 函数）
        images_data = [{
            'name': full_image_name,
            'ports': data.get('image_port', '')
        }]
        
        containers = api_utils.convert_container(images_data, pod_spec_envs, pod_spec_mnt_vols, pod_spec_limit)
        
        # 自动添加存活探针（基于传入的 process_name 和 process_keyword 参数）
        process_name = data.get('process_name')
        process_keyword = data.get('process_keyword')
        
        if process_name and process_keyword:
            # 为所有容器添加存活探针
            for container in containers:
                # 使用 ps 命令检查进程，comm 列匹配进程名，args 列匹配进程关键字
                container['livenessProbe'] = {
                    'exec': {
                        'command': [
                            '/bin/sh',
                            '-c',
                            f"ps -eo 'pid,comm,pcpu,rsz,args' | awk '($2 == \"{process_name}\" || $0 ~ /{process_keyword}/) && NR > 1 {{exit 0}} END {{if (NR <= 1) exit 1; exit 1}}'"
                        ]
                    },
                    'initialDelaySeconds': 30,  # 容器启动后30秒开始探测
                    'periodSeconds': 10,         # 每10秒探测一次
                    'timeoutSeconds': 5,         # 探测超时时间5秒
                    'successThreshold': 1,       # 连续1次成功则认为健康
                    'failureThreshold': 3        # 连续3次失败则重启容器
                }
            LOG.info('Added liveness probe for process_name "%s" and process_keyword "%s"', process_name, process_keyword)
        
        # 从数据库的 cluster_info 中读取镜像拉取认证信息
        image_pull_username = cluster_info.get('image_pull_username', '')
        image_pull_password = cluster_info.get('image_pull_password', '')
        
        registry_secrets = []
        if image_pull_username and image_pull_password:
            # 为主容器镜像创建 registry secret
            registry_secrets = api_utils.convert_registry_secret(k8s_client, images_data, resource_namespace,
                                                                 image_pull_username,
                                                                 image_pull_password)
        
        # 处理 packageUrl：添加 initContainer 和共享 volume（复用公共函数）
        init_containers = api_utils.setup_package_init_container(data, containers, pod_spec_src_vols, cluster_info)
        
        # 为 initContainer 镜像也创建 registry secret（如果提供了认证信息）
        if init_containers and image_pull_username and image_pull_password:
            # 收集所有 initContainer 的镜像
            init_container_images = [init_container.get('image') for init_container in init_containers if init_container.get('image')]
            if init_container_images:
                # 为 initContainer 镜像创建 secret，并合并到 registry_secrets 中
                # convert_registry_secret 内部已经做了去重，所以直接合并即可
                init_registry_secrets = api_utils.convert_registry_secret(k8s_client, init_container_images, resource_namespace,
                                                                          image_pull_username,
                                                                          image_pull_password)
                # 合并 secret 列表（去重）
                existing_secret_names = {secret['name'] for secret in registry_secrets}
                for secret in init_registry_secrets:
                    if secret['name'] not in existing_secret_names:
                        registry_secrets.append(secret)
                        existing_secret_names.add(secret['name'])
        
        template = {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name
            },
            'spec': {
                'replicas': int(replicas),
                'selector': {
                    'matchLabels': pod_spec_tags
                },
                'template': {
                    'metadata': {
                        'labels': pod_spec_tags
                    },
                    'spec': {
                        'affinity': pod_spec_affinity,
                        'containers': containers,
                        'volumes': pod_spec_src_vols
                    }
                }
            }
        }
        
        # 如果有 initContainers，添加到 spec 中
        if init_containers:
            template['spec']['template']['spec']['initContainers'] = init_containers
        
        # set imagePullSecrets if available
        if registry_secrets:
            template['spec']['template']['spec']['imagePullSecrets'] = registry_secrets
        return template

    def _ensure_service_for_deployment(self, k8s_client, data):
        """当入参包含端口信息时，为 Deployment 创建或更新对应的 Service"""
        # 仅当显式提供端口时才创建 Service：支持两种方式
        has_single_port = data.get('port') is not None
        has_service_ports = bool(data.get('servicePorts'))
        if not (has_single_port or has_service_ports):
            return

        namespace = data['namespace']
        # Service 名称必须符合 DNS-1035 规范
        service_name = api_utils.escape_service_name(data.get('serviceName', data['name']))

        # 从入参中取 selectors：仅使用传入的 pod_tags（不自动追加内部标签）
        selectors = api_utils.convert_tag(data.get('pod_tags', []))

        # 端口：优先使用 servicePorts，其次使用单个 port
        service_ports = []
        if has_service_ports:
            service_ports = api_utils.convert_service_port(data['servicePorts'])
        else:
            # 单端口快速路径
            target_port = data.get('targetPort', data['port'])
            protocol = data.get('protocol', 'TCP')
            port_name = data.get('portName')
            node_port = data.get('nodePort')
            port_item = {
                'port': int(data['port']),
                'targetPort': int(target_port) if isinstance(target_port, (int, float)) or str(target_port).isdigit() else target_port,
                'protocol': protocol
            }
            if port_name:
                port_item['name'] = port_name
            if node_port:
                port_item['nodePort'] = int(node_port)
            service_ports = [port_item]

        # 其它字段：能从入参取到的用入参，否则给默认值
        service_type = data.get('serviceType', 'ClusterIP')
        session_affinity = data.get('sessionAffinity')
        cluster_ip = data.get('clusterIP')  # 如果用户提供则尊重；否则不设置让集群分配
        headless = ('clusterIP' in data and data['clusterIP'] is None)

        # 标签
        service_resource_id = data.get('service_correlation_id', data['correlation_id'] + '-service')
        service_tags = api_utils.convert_tag(data.get('service_tags', data.get('tags', [])))
        service_tags[const.Tag.SERVICE_ID_TAG] = service_resource_id

        # 生成 Service 模板
        service_body = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'labels': service_tags,
                'name': service_name
            },
            'spec': {
                'type': service_type,
                'selector': selectors,
                'ports': service_ports
            }
        }
        if headless:
            service_body['spec']['clusterIP'] = None
        elif cluster_ip:
            service_body['spec']['clusterIP'] = cluster_ip

        # 创建或更新 Service
        exists_service = k8s_client.get_service(service_name, namespace)
        if exists_service is None:
            k8s_client.create_service(namespace, service_body)
            LOG.info('Created Service %s/%s for Deployment %s', namespace, service_name, data['name'])
        else:
            k8s_client.update_service(service_name, namespace, service_body)
            LOG.info('Updated Service %s/%s for Deployment %s', namespace, service_name, data['name'])

    def apply(self, data):
        resource_id = data['correlation_id']
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('api_server for cluster %s missing protocol, auto-adding https:// prefix: %s', 
                       cluster_info['name'], api_server)
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        k8s_client.ensure_namespace(data['namespace'])
        resource_name = api_utils.escape_name(data['name'])
        exists_resource = k8s_client.get_deployment(resource_name, data['namespace'])
        if exists_resource is None:
            exists_resource = k8s_client.create_deployment(data['namespace'], self.to_resource(k8s_client, data, cluster_info))
        else:
            exists_resource = k8s_client.update_deployment(resource_name, data['namespace'],
                                                           self.to_resource(k8s_client, data, cluster_info))
        # 若入参提供端口信息，则同时创建/更新对应 Service，并返回其分配信息
        self._ensure_service_for_deployment(k8s_client, data)
        has_single_port = data.get('port') is not None
        has_service_ports = bool(data.get('servicePorts'))
        cluster_ip = None
        port_str = ""
        if has_single_port or has_service_ports:
            service_name = api_utils.escape_name(data.get('serviceName', data['name']))
            svc = k8s_client.get_service(service_name, data['namespace'])
            if svc:
                cluster_ip = svc.spec.cluster_ip if getattr(svc.spec, 'cluster_ip', None) else None
                if getattr(svc.spec, 'ports', None) and len(svc.spec.ports) > 0:
                    # 取第一个 service 端口作为暴露端口返回
                    port_str = str(svc.spec.ports[0].port)
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return {
            'id': exists_resource.metadata.uid,
            'name': exists_resource.metadata.name,
            'correlation_id': resource_id,
            'clusterIP': cluster_ip,
            'port': port_str
        }

    def remove(self, data):
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        k8s_auth = k8s.AuthToken(cluster_info['api_server'], cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        resource_name = api_utils.escape_name(data['name'])
        exists_resource = k8s_client.get_deployment(resource_name, data['namespace'])
        if exists_resource is not None:
            k8s_client.delete_deployment(resource_name, data['namespace'])
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return {'id': '', 'name': '', 'correlation_id': ''}


class StatefulSet:
    def to_resource(self, k8s_client, data, cluster_info):
        resource_id = data['correlation_id']
        resource_name = api_utils.escape_name(data['name'])
        resource_namespace = data['namespace']
        resource_tags = api_utils.convert_tag(data.get('tags', []))
        resource_tags[const.Tag.STATEFULSET_ID_TAG] = resource_id
        replicas = data['replicas']
        pod_spec_affinity = api_utils.convert_affinity(data['affinity'], const.Tag.POD_AFFINITY_TAG, data['name'])
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        # 使用 escape_label_value 确保标签值符合 Kubernetes 规范
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = api_utils.escape_label_value(data['name'])
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = api_utils.escape_label_value(data['name'])
        
        # 添加 correlation_id 和 instanceId 作为 Pod 标签
        if data.get('correlation_id'):
            pod_spec_tags['correlation_id'] = api_utils.escape_label_value(data['correlation_id'])
        if data.get('instanceId'):
            pod_spec_tags['instanceId'] = api_utils.escape_label_value(data['instanceId'])
        
        pod_spec_envs = api_utils.convert_env(data.get('envs', []))
        
        # 自动注入 Kubernetes Downward API 环境变量
        pod_spec_envs.extend([
            {
                'name': 'HOST_IP',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'status.hostIP'
                    }
                }
            },
            {
                'name': 'POD_IP',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'status.podIP'
                    }
                }
            },
            {
                'name': 'POD_NAME',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'metadata.name'
                    }
                }
            }
        ])
        
        pod_spec_src_vols, pod_spec_mnt_vols = api_utils.convert_volume(data.get('volumes', []))
        
        # 自动添加 /logs hostPath 挂载（基于传入的 deployment_path 参数）
        deployment_path = data.get('deployment_path')
        if deployment_path:
            # 确保路径以 / 结尾
            if not deployment_path.endswith('/'):
                deployment_path += '/'
            # 构建宿主机日志路径：deployment_path + logs
            host_log_path = deployment_path + 'logs'
            
            # 添加 hostPath volume
            log_volume_name = 'instance-logs'
            pod_spec_src_vols.append({
                'name': log_volume_name,
                'hostPath': {
                    'path': host_log_path,
                    'type': 'DirectoryOrCreate'
                }
            })
            
            # 添加 volume mount 到容器的 /logs
            pod_spec_mnt_vols.append({
                'name': log_volume_name,
                'mountPath': '/logs',
                'readOnly': False
            })
            
            LOG.info('Auto-mounted host path %s to /logs', host_log_path)
        
        pod_spec_limit = api_utils.convert_resource_limit(data.get('cpu', None), data.get('memory', None))
        
        # 从数据库的 cluster_info 中读取私有仓库地址
        private_registry = cluster_info.get('private_registry', '')
        
        # 构建完整的镜像地址（拼接私有仓库地址）
        image_name = data['image_name'].strip()
        if private_registry:
            # 如果配置了私有仓库，拼接私有仓库地址
            full_image_name = f"{private_registry}/{image_name}"
        else:
            # 否则直接使用原始镜像名
            full_image_name = image_name
        
        # 构建 images 数组格式（兼容原有的 convert_container 函数）
        images_data = [{
            'name': full_image_name,
            'ports': data.get('image_port', '')
        }]
        
        containers = api_utils.convert_container(images_data, pod_spec_envs, pod_spec_mnt_vols, pod_spec_limit)
        
        # 自动添加存活探针（基于传入的 process_name 和 process_keyword 参数）
        process_name = data.get('process_name')
        process_keyword = data.get('process_keyword')
        
        if process_name and process_keyword:
            # 为所有容器添加存活探针
            for container in containers:
                # 使用 ps 命令检查进程，comm 列匹配进程名，args 列匹配进程关键字
                container['livenessProbe'] = {
                    'exec': {
                        'command': [
                            '/bin/sh',
                            '-c',
                            f"ps -eo 'pid,comm,pcpu,rsz,args' | awk '($2 == \"{process_name}\" || $0 ~ /{process_keyword}/) && NR > 1 {{exit 0}} END {{if (NR <= 1) exit 1; exit 1}}'"
                        ]
                    },
                    'initialDelaySeconds': 30,  # 容器启动后30秒开始探测
                    'periodSeconds': 10,         # 每10秒探测一次
                    'timeoutSeconds': 5,         # 探测超时时间5秒
                    'successThreshold': 1,       # 连续1次成功则认为健康
                    'failureThreshold': 3        # 连续3次失败则重启容器
                }
            LOG.info('Added liveness probe for process_name "%s" and process_keyword "%s"', process_name, process_keyword)
        
        # 从数据库的 cluster_info 中读取镜像拉取认证信息
        image_pull_username = cluster_info.get('image_pull_username', '')
        image_pull_password = cluster_info.get('image_pull_password', '')
        
        registry_secrets = []
        if image_pull_username and image_pull_password:
            # 为主容器镜像创建 registry secret
            registry_secrets = api_utils.convert_registry_secret(k8s_client, images_data, resource_namespace,
                                                                 image_pull_username,
                                                                 image_pull_password)
        
        # 处理 packageUrl：添加 initContainer 和共享 volume（复用公共函数）
        init_containers = api_utils.setup_package_init_container(data, containers, pod_spec_src_vols, cluster_info)
        
        # 为 initContainer 镜像也创建 registry secret（如果提供了认证信息）
        if init_containers and image_pull_username and image_pull_password:
            # 收集所有 initContainer 的镜像
            init_container_images = [init_container.get('image') for init_container in init_containers if init_container.get('image')]
            if init_container_images:
                # 为 initContainer 镜像创建 secret，并合并到 registry_secrets 中
                # convert_registry_secret 内部已经做了去重，所以直接合并即可
                init_registry_secrets = api_utils.convert_registry_secret(k8s_client, init_container_images, resource_namespace,
                                                                          image_pull_username,
                                                                          image_pull_password)
                # 合并 secret 列表（去重）
                existing_secret_names = {secret['name'] for secret in registry_secrets}
                for secret in init_registry_secrets:
                    if secret['name'] not in existing_secret_names:
                        registry_secrets.append(secret)
                        existing_secret_names.add(secret['name'])
        
        template = {
            'apiVersion': 'apps/v1',
            'kind': 'StatefulSet',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name
            },
            'spec': {
                'replicas': int(replicas),
                'serviceName': data.get('serviceName', resource_name),
                'selector': {
                    'matchLabels': pod_spec_tags
                },
                'template': {
                    'metadata': {
                        'labels': pod_spec_tags
                    },
                    'spec': {
                        'affinity': pod_spec_affinity,
                        'containers': containers,
                        'volumes': pod_spec_src_vols
                    }
                }
            }
        }
        
        # 如果有 initContainers，添加到 spec 中
        if init_containers:
            template['spec']['template']['spec']['initContainers'] = init_containers
        
        # set imagePullSecrets if available
        if registry_secrets:
            template['spec']['template']['spec']['imagePullSecrets'] = registry_secrets
        # StatefulSet 支持 volumeClaimTemplates（可选）
        if data.get('volumeClaimTemplates'):
            template['spec']['volumeClaimTemplates'] = data['volumeClaimTemplates']
        return template

    def _ensure_headless_service(self, k8s_client, data, resource_template):
        """确保 StatefulSet 关联的 Headless Service 存在"""
        service_name = data.get('serviceName', data['name'])
        # Service 名称必须符合 DNS-1035 规范（比 DNS-1123 更严格）
        service_name = api_utils.escape_service_name(service_name)
        namespace = data['namespace']
        
        # 检查 Service 是否已存在
        exists_service = k8s_client.get_service(service_name, namespace)
        if exists_service is not None:
            # Service 已存在，无需创建
            return
        
        # 获取 Pod 标签作为 Service selector
        # 注意：标签值也需要转义以符合 Kubernetes 标签规范
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        # 使用 escape_label_value 确保标签值符合 Kubernetes 规范
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = api_utils.escape_label_value(data['name'])
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = api_utils.escape_label_value(data['name'])
        
        # 获取 Service 端口
        # 优先级：1. 用户提供的 servicePorts 2. 从 image_port 推断
        service_ports = []
        if data.get('servicePorts'):
            # 用户提供了 Service 端口配置
            service_ports = api_utils.convert_service_port(data['servicePorts'])
        else:
            # 从 image_port 推断
            if data.get('image_port'):
                container_ports = api_utils.convert_pod_ports(data.get('image_port', ''))
                for port_info in container_ports:
                    port = port_info.get('containerPort')
                    if port:
                        service_ports.append({
                            'port': port,
                            'targetPort': port,
                            'protocol': port_info.get('protocol', 'TCP')
                        })
        
        # 如果没有找到任何端口，使用默认端口（Kubernetes 要求 Service 必须有 ports 字段）
        if not service_ports:
            LOG.warning('No ports specified for StatefulSet %s, using default port 80', data['name'])
            service_ports = [{
                'name': 'default',
                'port': 80,
                'targetPort': 80,
                'protocol': 'TCP'
            }]
        
        # 创建 Headless Service
        service_resource_id = data.get('service_correlation_id', data['correlation_id'] + '-service')
        service_tags = api_utils.convert_tag(data.get('service_tags', data.get('tags', [])))
        service_tags[const.Tag.SERVICE_ID_TAG] = service_resource_id
        
        service_template = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'labels': service_tags,
                'name': service_name
            },
            'spec': {
                'type': 'ClusterIP',
                'clusterIP': None,  # Headless Service
                'selector': pod_spec_tags,
                'ports': service_ports
            }
        }
        
        # 创建 Headless Service
        k8s_client.create_service(namespace, service_template)
        LOG.info('Created Headless Service %s/%s for StatefulSet %s/%s',
                 namespace, service_name, namespace, data['name'])

    def _sync_pods_to_cmdb(self, k8s_client, namespace, pod_list, instance_id):
        """同步 Pod 信息到 CMDB"""
        if not instance_id:
            LOG.warning('No instanceId provided, skipping CMDB sync')
            return
        
        try:
            from wecubek8s.common import wecmdb
            
            # 获取 CMDB 客户端（需要从配置中获取 CMDB 地址）
            cmdb_server = CONF.wecube.gateway_url
            cmdb_client = wecmdb.EntityClient(cmdb_server)
            
            # 1. 查询 CMDB 中该 instanceId 下的所有 Pod
            query_data = {
                "criteria": {
                    "attrName": "instance",  # CMDB 字段名：instance
                    "op": "eq",
                    "condition": instance_id
                }
            }
            
            LOG.info('Querying CMDB for pods with instanceId: %s', instance_id)
            cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
            
            # 解析 CMDB 返回的 Pod 列表
            cmdb_pods = {}
            if cmdb_response and cmdb_response.get('data'):
                for pod_data in cmdb_response['data']:
                    pod_code = pod_data.get('code')  # CMDB 字段名：code（Pod 名称）
                    if pod_code:
                        cmdb_pods[pod_code] = {
                            'guid': pod_data.get('guid'),  # CMDB 字段名：guid（记录标识符）
                            'asset_id': pod_data.get('asset_id')  # CMDB 字段名：asset_id（K8s Pod UID）
                        }
            
            # 2. 对比 K8s 实际的 Pod 列表，找出需要更新的 Pod
            updates = []
            for pod_info in pod_list:
                pod_name = pod_info['name']
                pod_id = pod_info['id']
                
                if pod_name in cmdb_pods:
                    cmdb_pod = cmdb_pods[pod_name]
                    # 如果 Pod ID 发生变化，需要更新
                    if cmdb_pod['asset_id'] != pod_id:
                        updates.append({
                            'guid': cmdb_pod['guid'],  # CMDB 字段名：guid（记录标识符）
                            'asset_id': pod_id  # CMDB 字段名：asset_id（新的 K8s Pod UID）
                        })
                        LOG.info('Pod %s ID changed: %s -> %s', pod_name, cmdb_pod['asset_id'], pod_id)
                else:
                    LOG.warning('Pod %s not found in CMDB, skipping update', pod_name)
            
            # 3. 批量更新 CMDB
            if updates:
                LOG.info('Updating %d pods in CMDB', len(updates))
                cmdb_client.update('wecmdb', 'pod', updates)
                LOG.info('Successfully updated pods in CMDB')
            else:
                LOG.info('No pod ID changes detected, CMDB sync skipped')
                
        except Exception as e:
            LOG.error('Failed to sync pods to CMDB: %s', str(e))
            # 不抛出异常，避免影响主流程
    
    def apply(self, data):
        resource_id = data['correlation_id']
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('api_server for cluster %s missing protocol, auto-adding https:// prefix: %s', 
                       cluster_info['name'], api_server)
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        k8s_client.ensure_namespace(data['namespace'])
        resource_name = api_utils.escape_name(data['name'])
        
        # 生成 StatefulSet 资源模板
        resource_template = self.to_resource(k8s_client, data, cluster_info)
        
        # 确保关联的 Headless Service 存在，假如不存在则创建service
        self._ensure_headless_service(k8s_client, data, resource_template)
        
        exists_resource = k8s_client.get_statefulset(resource_name, data['namespace'])
        if exists_resource is None:
            exists_resource = k8s_client.create_statefulset(data['namespace'], resource_template)
        else:
            exists_resource = k8s_client.update_statefulset(resource_name, data['namespace'], resource_template)
        
        # 补充返回对应 Service 的 clusterIP 与 port（若存在端口）
        service_name = api_utils.escape_name(data.get('serviceName', data['name']))
        cluster_ip = None
        port_str = ""
        svc = k8s_client.get_service(service_name, data['namespace'])
        if svc:
            cluster_ip = svc.spec.cluster_ip if getattr(svc.spec, 'cluster_ip', None) else None
            if getattr(svc.spec, 'ports', None) and len(svc.spec.ports) > 0:
                port_str = str(svc.spec.ports[0].port)
        
        # 获取实际的 Pod 列表（包含 name 和 id）
        replicas = int(data.get('replicas', 1))
        pod_list = []
        
        # 查询实际运行的 Pod，获取真实的 Pod ID
        # 使用 label selector 查询该 StatefulSet 的 Pod
        # 注意：label 值必须经过 escape 处理以符合 Kubernetes 规范
        escaped_name = api_utils.escape_label_value(data['name'])
        label_selector = f"{const.Tag.POD_AUTO_TAG}={escaped_name}"
        try:
            pods = k8s_client.list_pod(data['namespace'], label_selector=label_selector)
            if pods and pods.items:
                for pod in pods.items:
                    pod_list.append({
                        'name': pod.metadata.name,
                        'id': pod.metadata.uid
                    })
                LOG.info('Found %d running pods for StatefulSet %s', len(pod_list), resource_name)
            else:
                # 如果还没有 Pod 运行，使用预期的 Pod 名称（ID 暂时为空）
                LOG.warning('No running pods found for StatefulSet %s, using expected pod names', resource_name)
                for i in range(replicas):
                    pod_list.append({
                        'name': f"{resource_name}-{i}",
                        'id': ''
                    })
        except Exception as e:
            LOG.error('Failed to query pods: %s', str(e))
            # 使用预期的 Pod 名称
            for i in range(replicas):
                pod_list.append({
                    'name': f"{resource_name}-{i}",
                    'id': ''
                })
        
        # 如果提供了 instanceId，同步 Pod 信息到 CMDB
        instance_id = data.get('instanceId')
        if instance_id and pod_list:
            self._sync_pods_to_cmdb(k8s_client, data['namespace'], pod_list, instance_id)
        
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return {
            'id': exists_resource.metadata.uid,
            'name': exists_resource.metadata.name,
            'correlation_id': resource_id,
            'clusterIP': cluster_ip,
            'port': port_str,
            'pods': pod_list  # 返回 Pod 对象数组，包含 name 和 id
        }

    def remove(self, data):
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        k8s_auth = k8s.AuthToken(cluster_info['api_server'], cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        resource_name = api_utils.escape_name(data['name'])
        exists_resource = k8s_client.get_statefulset(resource_name, data['namespace'])
        if exists_resource is not None:
            k8s_client.delete_statefulset(resource_name, data['namespace'])
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return {'id': '', 'name': '', 'correlation_id': ''}


class Service:
    def to_resource(self, k8s_client, data):
        resource_id = data['correlation_id']
        # Service 名称必须符合 DNS-1035 规范
        resource_name = api_utils.escape_service_name(data['name'])
        resource_tags = api_utils.convert_tag(data.get('tags', []))
        resource_tags[const.Tag.SERVICE_ID_TAG] = resource_id
        resource_type = data['type']
        resource_headless = 'clusterIP' in data and data['clusterIP'] is None
        resource_cluster_ip = data.get('clusterIP', None)
        resource_session = data.get('sessionAffinity', None)

        ports = api_utils.convert_service_port(data['instances'])
        selectors = api_utils.convert_tag(data['selectors'])
        template = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name
            },
            'spec': {
                'type': resource_type,
                'sessionAffinity': resource_session,
                'ports': ports,
                'selector': selectors
            }
        }
        if resource_headless:
            template['spec']['clusterIP'] = None
        elif resource_cluster_ip:
            # not headless & user specific cluster ip, use it
            template['spec']['clusterIP'] = resource_cluster_ip
        return template

    def apply(self, data):
        resource_id = data['correlation_id']
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('api_server for cluster %s missing protocol, auto-adding https:// prefix: %s', 
                       cluster_info['name'], api_server)
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        k8s_client.ensure_namespace(data['namespace'])
        # Service 名称必须符合 DNS-1035 规范
        resource_name = api_utils.escape_service_name(data['name'])
        exists_resource = k8s_client.get_service(resource_name, data['namespace'])
        if not exists_resource:
            exists_resource = k8s_client.create_service(data['namespace'], self.to_resource(k8s_client, data))
        else:
            exists_resource = k8s_client.update_service(resource_name, data['namespace'],
                                                        self.to_resource(k8s_client, data))
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        
        # Extract clusterIP and ports from the created/updated service
        cluster_ip = exists_resource.spec.cluster_ip if exists_resource.spec.cluster_ip else None
        ports = []
        if exists_resource.spec.ports:
            for port in exists_resource.spec.ports:
                port_info = {
                    'port': port.port,
                    'protocol': port.protocol if port.protocol else 'TCP',
                }
                # targetPort can be int or string (IntOrString type in K8s)
                if port.target_port is not None:
                    port_info['targetPort'] = port.target_port if isinstance(port.target_port, int) else str(port.target_port)
                if port.name:
                    port_info['name'] = port.name
                if port.node_port is not None:
                    port_info['nodePort'] = port.node_port
                ports.append(port_info)
        
        return {
            'id': exists_resource.metadata.uid,
            'name': exists_resource.metadata.name,
            'correlation_id': resource_id,
            'clusterIP': cluster_ip,
            'ports': ports
        }

    def remove(self, data):
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        k8s_auth = k8s.AuthToken(cluster_info['api_server'], cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        resource_name = api_utils.escape_name(data['name'])
        exists_resource = k8s_client.get_service(resource_name, data['namespace'])
        if exists_resource is not None:
            k8s_client.delete_service(resource_name, data['namespace'])
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return {'id': '', 'name': '', 'correlation_id': ''}


class Node:
    def label(self, data):
        """查询集群中的所有 node 并更新标签"""
        cluster_name = data['cluster']
        
        # 获取集群信息
        cluster_info = db_resource.Cluster().list({'name': cluster_name})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': cluster_name}))
        cluster_info = cluster_info[0]
        
        # 创建 k8s client
        auth = k8s.AuthToken(cluster_info['api_server'], cluster_info['token'])
        k8s_client = k8s.Client(auth)
        
        # 获取所有 node
        nodes = k8s_client.list_node()
        
        # 获取单个标签的 name 和 value
        tag_name = data['tagName']
        tag_value = data['tagValue']
        
        results = []
        for node in nodes.items:
            node_name = node.metadata.name
            
            # 获取现有标签，保留系统标签
            existing_labels = {}
            if node.metadata.labels:
                existing_labels = dict(node.metadata.labels)
            
            # 添加或更新单个标签
            merged_labels = existing_labels.copy()
            merged_labels[tag_name] = tag_value
            
            # 准备 patch body（只更新 labels）
            patch_body = {
                'metadata': {
                    'labels': merged_labels
                }
            }
            
            # 更新 node 标签
            try:
                k8s_client.patch_node(node_name, patch_body)
                results.append({
                    'name': node_name,
                    'id': node.metadata.uid,
                    'labels': merged_labels
                })
                LOG.info('Updated labels for node %s in cluster %s', node_name, cluster_name)
            except Exception as e:
                LOG.error('Failed to update labels for node %s: %s', node_name, str(e))
                raise exceptions.K8sCallError(cluster=cluster_name, msg='Failed to update node %s: %s' % (node_name, str(e)))
        
        return {
            'cluster': cluster_name,
            'nodes_updated': len(results),
            'nodes': results
        }
    
    def remove_label(self, data):
        """移除指定 Node 上的指定标签"""
        cluster_name = data['cluster']
        
        # 获取集群信息
        cluster_info = db_resource.Cluster().list({'name': cluster_name})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             msg=_('name of cluster(%(name)s) not found' % {'name': cluster_name}))
        cluster_info = cluster_info[0]
        
        # 创建 k8s client
        auth = k8s.AuthToken(cluster_info['api_server'], cluster_info['token'])
        k8s_client = k8s.Client(auth)
        
        # 获取要移除标签的标签名
        tag_name = data['tagName']
        
        # 判断是针对指定 Node 还是所有 Node
        node_name = data.get('nodeName')
        
        results = []
        if node_name:
            # 针对指定的 Node
            node = k8s_client.get_node(node_name)
            if not node:
                raise exceptions.ValidationError(attribute='nodeName',
                                                 msg=_('node(%(name)s) not found in cluster' % {'name': node_name}))
            
            # 获取现有标签
            existing_labels = {}
            if node.metadata.labels:
                existing_labels = dict(node.metadata.labels)
            
            # 检查标签是否存在
            if tag_name not in existing_labels:
                LOG.warning('Label %s not found on node %s, skipping', tag_name, node_name)
                return {
                    'cluster': cluster_name,
                    'nodes_updated': 0,
                    'message': f'Label {tag_name} not found on node {node_name}'
                }
            
            # 移除指定标签
            updated_labels = existing_labels.copy()
            del updated_labels[tag_name]
            
            # 准备 patch body
            patch_body = {
                'metadata': {
                    'labels': updated_labels
                }
            }
            
            # 更新 node 标签
            try:
                k8s_client.patch_node(node_name, patch_body)
                results.append({
                    'name': node_name,
                    'id': node.metadata.uid,
                    'removed_label': tag_name,
                    'remaining_labels': updated_labels
                })
                LOG.info('Removed label %s from node %s in cluster %s', tag_name, node_name, cluster_name)
            except Exception as e:
                LOG.error('Failed to remove label from node %s: %s', node_name, str(e))
                raise exceptions.K8sCallError(cluster=cluster_name, msg='Failed to update node %s: %s' % (node_name, str(e)))
        else:
            # 针对所有 Node
            nodes = k8s_client.list_node()
            
            for node in nodes.items:
                node_name = node.metadata.name
                
                # 获取现有标签
                existing_labels = {}
                if node.metadata.labels:
                    existing_labels = dict(node.metadata.labels)
                
                # 检查标签是否存在
                if tag_name not in existing_labels:
                    LOG.debug('Label %s not found on node %s, skipping', tag_name, node_name)
                    continue
                
                # 移除指定标签
                updated_labels = existing_labels.copy()
                del updated_labels[tag_name]
                
                # 准备 patch body
                patch_body = {
                    'metadata': {
                        'labels': updated_labels
                    }
                }
                
                # 更新 node 标签
                try:
                    k8s_client.patch_node(node_name, patch_body)
                    results.append({
                        'name': node_name,
                        'id': node.metadata.uid,
                        'removed_label': tag_name,
                        'remaining_labels': updated_labels
                    })
                    LOG.info('Removed label %s from node %s in cluster %s', tag_name, node_name, cluster_name)
                except Exception as e:
                    LOG.error('Failed to remove label from node %s: %s', node_name, str(e))
                    # 继续处理其他节点，不中断整个操作
                    continue
        
        return {
            'cluster': cluster_name,
            'nodes_updated': len(results),
            'nodes': results
        }


class ClusterInterconnect:
    """跨集群互联策略管理"""

    def __init__(self):
        self.db_cluster = db_resource.Cluster()

    def create_external_service(self, data):
        """
        创建跨集群服务（使用ExternalName或Endpoint方式）
        参数:
            {
                "local_cluster": "cluster1",  # 本地集群
                "local_namespace": "default",
                "service_name": "remote-service",
                "remote_cluster": "cluster2",  # 远程集群
                "remote_namespace": "default",
                "remote_service_name": "backend-service",
                "service_type": "ExternalName",  # 或 "Endpoint"
                "external_name": "backend.cluster2.svc.cluster.local",  # ExternalName类型
                "endpoints": [  # Endpoint类型
                    {"ip": "10.0.1.100", "ports": [{"port": 8080, "protocol": "TCP"}]}
                ]
            }
        """
        local_cluster_name = data.get('local_cluster')
        local_namespace = data.get('local_namespace', 'default')
        service_name = data.get('service_name')
        remote_cluster_name = data.get('remote_cluster')
        service_type = data.get('service_type', 'ExternalName')

        if not local_cluster_name or not service_name:
            raise exceptions.ValidationError(
                attribute='local_cluster, service_name',
                msg=_('local_cluster and service_name are required'))

        # 获取集群信息
        all_clusters = self.db_cluster.list()
        cluster_map = {c['name']: c for c in all_clusters}

        if local_cluster_name not in cluster_map:
            raise exceptions.ValidationError(
                attribute='local_cluster',
                msg=_('Local cluster %(name)s not found' % {'name': local_cluster_name}))

        local_cluster = cluster_map[local_cluster_name]
        k8s_auth = k8s.AuthToken(local_cluster['api_server'], local_cluster['token'])
        local_client = k8s.Client(k8s_auth)
        local_client.ensure_namespace(local_namespace)

        # 如果使用Endpoint方式，需要获取远程集群的服务IP
        if service_type == 'Endpoint':
            if not remote_cluster_name:
                raise exceptions.ValidationError(
                    attribute='remote_cluster',
                    msg=_('remote_cluster is required when service_type is Endpoint'))

            if remote_cluster_name not in cluster_map:
                raise exceptions.ValidationError(
                    attribute='remote_cluster',
                    msg=_('Remote cluster %(name)s not found' % {'name': remote_cluster_name}))

            remote_cluster = cluster_map[remote_cluster_name]
            remote_namespace = data.get('remote_namespace', 'default')
            remote_service_name = data.get('remote_service_name', service_name)

            # 获取远程服务的ClusterIP
            remote_auth = k8s.AuthToken(remote_cluster['api_server'], remote_cluster['token'])
            remote_client = k8s.Client(remote_auth)
            remote_service = remote_client.get_service(remote_service_name, remote_namespace)

            if not remote_service:
                raise exceptions.ValidationError(
                    attribute='remote_service_name',
                    msg=_('Remote service %(name)s/%(ns)s not found' %
                         {'name': remote_service_name, 'ns': remote_namespace}))

            cluster_ip = remote_service.spec.cluster_ip
            ports = []
            if remote_service.spec.ports:
                ports = [{'port': p.port, 'protocol': p.protocol or 'TCP'} for p in remote_service.spec.ports]

            # 如果用户提供了自定义endpoints，使用用户的配置
            if data.get('endpoints'):
                endpoints_data = data['endpoints']
            else:
                endpoints_data = [{'ip': cluster_ip, 'ports': ports}]

            # 创建Endpoint
            endpoint_body = {
                'apiVersion': 'v1',
                'kind': 'Endpoints',
                'metadata': {
                    'name': service_name,
                    'namespace': local_namespace,
                    'labels': {
                        'wecube.interconnect': 'true',
                        'remote.cluster': remote_cluster_name
                    }
                },
                'subsets': []
            }

            # 构建subsets
            subsets = []
            for ep_data in endpoints_data:
                ep_ip = ep_data.get('ip')
                ep_ports = ep_data.get('ports', ports)
                if ep_ip:
                    subset = {
                        'addresses': [{'ip': ep_ip}],
                        'ports': [{'port': p['port'], 'protocol': p.get('protocol', 'TCP')} for p in ep_ports]
                    }
                    subsets.append(subset)
            endpoint_body['subsets'] = subsets

            existing_endpoint = local_client.get_endpoint(service_name, local_namespace)
            if existing_endpoint:
                local_client.update_endpoint(service_name, local_namespace, endpoint_body)
            else:
                local_client.create_endpoint(local_namespace, endpoint_body)

            # 创建无selector的Service
            service_body = {
                'apiVersion': 'v1',
                'kind': 'Service',
                'metadata': {
                    'name': service_name,
                    'namespace': local_namespace,
                    'labels': {
                        'wecube.interconnect': 'true',
                        'remote.cluster': remote_cluster_name
                    }
                },
                'spec': {
                    'type': 'ClusterIP',
                    'ports': [{'port': p['port'], 'protocol': p.get('protocol', 'TCP'), 'targetPort': p['port']}
                             for p in ports] if ports else []
                }
            }

        else:  # ExternalName类型
            external_name = data.get('external_name')
            if not external_name:
                # 自动构建外部名称
                if not remote_cluster_name:
                    raise exceptions.ValidationError(
                        attribute='external_name or remote_cluster',
                        msg=_('external_name or remote_cluster is required for ExternalName type'))
                remote_namespace = data.get('remote_namespace', 'default')
                remote_service_name = data.get('remote_service_name', service_name)
                external_name = f"{remote_service_name}.{remote_namespace}.svc.{remote_cluster_name}.local"

            ports = data.get('ports', [{'port': 80, 'protocol': 'TCP'}])
            service_body = {
                'apiVersion': 'v1',
                'kind': 'Service',
                'metadata': {
                    'name': service_name,
                    'namespace': local_namespace,
                    'labels': {
                        'wecube.interconnect': 'true',
                        'service.type': 'ExternalName'
                    }
                },
                'spec': {
                    'type': 'ExternalName',
                    'externalName': external_name,
                    'ports': [{'port': p['port'], 'protocol': p.get('protocol', 'TCP')} for p in ports]
                }
            }

        # 创建或更新Service
        existing_service = local_client.get_service(service_name, local_namespace)
        if existing_service:
            local_client.update_service(service_name, local_namespace, service_body)
        else:
            local_client.create_service(local_namespace, service_body)

        return {
            'id': '',
            'name': service_name,
            'cluster': local_cluster_name,
            'namespace': local_namespace,
            'type': service_type,
            'status': 'created'
        }

    def create_network_policy(self, data):
        """
        创建跨集群网络策略
        参数:
            {
                "cluster": "cluster1",
                "namespace": "default",
                "policy_name": "allow-cross-cluster",
                "pod_selector": {"app": "frontend"},  # 应用策略的Pod
                "allowed_clusters": ["cluster2"],  # 允许访问的远程集群
                "allowed_ports": [{"port": 8080, "protocol": "TCP"}],
                "direction": "egress"  # egress/ingress
            }
        """
        cluster_name = data.get('cluster')
        namespace = data.get('namespace', 'default')
        policy_name = data.get('policy_name')

        if not cluster_name or not policy_name:
            raise exceptions.ValidationError(
                attribute='cluster, policy_name',
                msg=_('cluster and policy_name are required'))

        all_clusters = self.db_cluster.list()
        cluster_map = {c['name']: c for c in all_clusters}

        if cluster_name not in cluster_map:
            raise exceptions.ValidationError(
                attribute='cluster',
                msg=_('Cluster %(name)s not found' % {'name': cluster_name}))

        cluster = cluster_map[cluster_name]
        k8s_auth = k8s.AuthToken(cluster['api_server'], cluster['token'])
        k8s_client = k8s.Client(k8s_auth)
        k8s_client.ensure_namespace(namespace)

        # 获取远程集群的Pod CIDR范围（需要预先配置）
        allowed_clusters = data.get('allowed_clusters', [])
        pod_selector = data.get('pod_selector', {})
        direction = data.get('direction', 'egress')
        allowed_ports = data.get('allowed_ports', [])

        # 构建网络策略
        policy_body = {
            'apiVersion': 'networking.k8s.io/v1',
            'kind': 'NetworkPolicy',
            'metadata': {
                'name': policy_name,
                'namespace': namespace
            },
            'spec': {
                'podSelector': {
                    'matchLabels': pod_selector
                }
            }
        }

        if direction == 'egress':
            # 出站策略：允许访问远程集群
            egress_rules = []
            for remote_cluster in allowed_clusters:
                # 通过namespace selector匹配远程集群的命名空间
                # 假设远程集群的命名空间有cluster标签
                egress_rule = {
                    'to': [{
                        'namespaceSelector': {
                            'matchLabels': {'cluster': remote_cluster}
                        }
                    }]
                }
                if allowed_ports:
                    egress_rule['ports'] = [
                        {'protocol': p.get('protocol', 'TCP'), 'port': p['port']} for p in allowed_ports
                    ]
                egress_rules.append(egress_rule)
            if egress_rules:
                policy_body['spec']['egress'] = egress_rules
        else:
            # 入站策略：允许来自远程集群的访问
            ingress_rules = []
            for remote_cluster in allowed_clusters:
                ingress_rule = {
                    'from': [{
                        'namespaceSelector': {
                            'matchLabels': {'cluster': remote_cluster}
                        }
                    }]
                }
                if allowed_ports:
                    ingress_rule['ports'] = [
                        {'protocol': p.get('protocol', 'TCP'), 'port': p['port']} for p in allowed_ports
                    ]
                ingress_rules.append(ingress_rule)
            if ingress_rules:
                policy_body['spec']['ingress'] = ingress_rules

        existing_policy = k8s_client.get_network_policy(policy_name, namespace)
        if existing_policy:
            k8s_client.update_network_policy(policy_name, namespace, policy_body)
        else:
            k8s_client.create_network_policy(namespace, policy_body)

        return {
            'id': '',
            'name': policy_name,
            'cluster': cluster_name,
            'namespace': namespace,
            'status': 'created'
        }

    def setup_interconnect(self, data):
        """
        一键设置跨集群互联（创建Service + NetworkPolicy）
        参数:
            {
                "local_cluster": "cluster1",
                "remote_cluster": "cluster2",
                "local_namespace": "default",
                "remote_namespace": "default",
                "service_name": "backend",
                "service_type": "Endpoint",
                "enable_network_policy": true
            }
        """
        # 创建跨集群服务
        service_data = {
            'local_cluster': data['local_cluster'],
            'local_namespace': data.get('local_namespace', 'default'),
            'service_name': data['service_name'],
            'remote_cluster': data['remote_cluster'],
            'remote_namespace': data.get('remote_namespace', 'default'),
            'service_type': data.get('service_type', 'Endpoint')
        }
        service_result = self.create_external_service(service_data)

        result = {
            'service': service_result,
            'network_policy': None
        }

        # 如果需要，创建网络策略
        if data.get('enable_network_policy'):
            policy_data = {
                'cluster': data['local_cluster'],
                'namespace': data.get('local_namespace', 'default'),
                'policy_name': f"allow-{data['remote_cluster']}",
                'pod_selector': {'app': data['service_name']},
                'allowed_clusters': [data['remote_cluster']],
                'direction': 'egress',
                'allowed_ports': []  # 可以从service中获取，这里简化处理
            }
            try:
                policy_result = self.create_network_policy(policy_data)
                result['network_policy'] = policy_result
            except Exception as e:
                LOG.warning('Failed to create network policy: %s', str(e))
                # 不阻止service创建，只记录警告

        return result