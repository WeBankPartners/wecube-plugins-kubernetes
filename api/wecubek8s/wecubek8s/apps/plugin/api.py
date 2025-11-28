# coding=utf-8

from __future__ import absolute_import

import logging
import time

from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import k8s
from wecubek8s.common import exceptions
from wecubek8s.common import const
from wecubek8s.db import resource as db_resource
from wecubek8s.apps.plugin import utils as api_utils

CONF = config.CONF
LOG = logging.getLogger(__name__)


# ==================== 健康检查探针辅助函数 ====================

def _generate_liveness_probe(container, process_name=None, process_keyword=None, probe_type='auto'):
    """
    智能生成 Liveness Probe 配置
    
    Args:
        container: 容器配置字典（包含 name、ports、image 等信息）
        process_name: 进程名称
        process_keyword: 进程关键字
        probe_type: 探针类型 ('auto', 'http', 'tcp', 'exec', 'pidof', 'none')
    
    Returns:
        dict: Liveness Probe 配置，如果返回 None 则不添加探针
    """
    
    # 如果明确指定不使用探针
    if probe_type == 'none':
        return None
    
    container_name = container.get('name', '')
    ports = container.get('ports', [])
    image = container.get('image', '')
    
    # 自动模式：智能选择最合适的探针类型
    if probe_type == 'auto':
        probe_type = _auto_detect_probe_type(container_name, ports, process_name, image)
    
    # 根据探针类型生成配置
    if probe_type == 'http':
        return _generate_http_probe(ports, image)
    elif probe_type == 'tcp':
        return _generate_tcp_probe(ports)
    elif probe_type == 'pidof':
        return _generate_pidof_probe(process_name, process_keyword)
    elif probe_type == 'exec':
        return _generate_ps_probe(process_name, process_keyword)
    else:
        LOG.warning('Unknown probe type: %s, fallback to pidof', probe_type)
        return _generate_pidof_probe(process_name, process_keyword)


def _auto_detect_probe_type(container_name, ports, process_name, image=None):
    """
    自动检测最合适的探针类型
    
    优先级：
    1. 如果有 HTTP 服务端口 (80, 8080, 3000 等) → HTTP 探针
    2. 如果有任意端口 → TCP 探针
    3. 如果镜像是已知的 Web 服务器（nginx、apache、tomcat 等）→ HTTP 探针 + 推断默认端口
    4. 如果只有进程名 → pidof 探针（兼容性好）
    5. 其他情况 → TCP 探针（最通用）
    """
    
    # 常见的 HTTP 服务端口
    HTTP_PORTS = {80, 443, 8080, 8000, 8008, 3000, 5000, 9000}
    
    if ports:
        for port_config in ports:
            port = port_config.get('containerPort')
            if port in HTTP_PORTS:
                LOG.info('Auto-detected HTTP service on port %s, using HTTP probe', port)
                return 'http'
        
        # 有端口但不是常见 HTTP 端口，使用 TCP 探针
        LOG.info('Detected service ports, using TCP probe')
        return 'tcp'
    
    # 没有端口配置，尝试从镜像名称推断服务类型
    if image:
        image_lower = image.lower()
        
        # 检测常见的 Web 服务器镜像
        WEB_SERVER_PATTERNS = [
            'nginx', 'httpd', 'apache', 'tomcat', 'jetty',
            'caddy', 'traefik', 'haproxy', 'lighttpd'
        ]
        
        for pattern in WEB_SERVER_PATTERNS:
            if pattern in image_lower:
                LOG.info('Detected web server image (%s), using HTTP probe with inferred port', pattern)
                return 'http'
    
    # 没有端口配置，但有进程名
    if process_name:
        LOG.info('No ports configured, using pidof probe for process: %s', process_name)
        return 'pidof'
    
    # 默认使用 TCP 探针（如果有端口）
    return 'tcp'


def _generate_http_probe(ports, image=None):
    """
    生成 HTTP 探针（最可靠，适用于 Web 服务）
    
    如果没有配置端口，会尝试从镜像名推断默认端口
    """
    port = None
    
    # 1. 优先使用配置的端口
    if ports and len(ports) > 0:
        port = ports[0].get('containerPort')
    
    # 2. 如果没有配置端口，从镜像名推断
    if not port and image:
        port = _infer_default_port_from_image(image)
    
    # 3. 仍然没有端口，使用默认的 80
    if not port:
        LOG.warning('No port configured for HTTP probe, using default port 80')
        port = 80
    
    LOG.info('Using HTTP probe on port %s (image: %s)', port, image or 'unknown')
    
    return {
        'httpGet': {
            'path': '/',
            'port': port,
            'scheme': 'HTTP'
        },
        'initialDelaySeconds': 60,      # 增加到60秒，给足启动时间
        'periodSeconds': 10,             # 每10秒检查一次
        'timeoutSeconds': 5,             # 5秒超时
        'successThreshold': 1,           # 成功1次即认为健康
        'failureThreshold': 6            # 失败6次才重启（60秒容错窗口）
    }


def _infer_default_port_from_image(image):
    """
    从镜像名称推断默认端口
    
    Args:
        image: 镜像名称（例如：nginx, tomcat:9.0, registry.io/apache:latest）
    
    Returns:
        int: 推断的端口号，如果无法推断则返回 None
    """
    if not image:
        return None
    
    image_lower = image.lower()
    
    # 常见服务的默认端口映射
    PORT_MAPPINGS = {
        'nginx': 80,
        'httpd': 80,
        'apache': 80,
        'tomcat': 8080,
        'jetty': 8080,
        'wildfly': 8080,
        'jboss': 8080,
        'caddy': 80,
        'traefik': 80,
        'haproxy': 80,
        'lighttpd': 80,
        'redis': 6379,
        'mysql': 3306,
        'mariadb': 3306,
        'postgres': 5432,
        'postgresql': 5432,
        'mongodb': 27017,
        'mongo': 27017
    }
    
    for service_name, default_port in PORT_MAPPINGS.items():
        if service_name in image_lower:
            LOG.info('Inferred port %d for image containing "%s"', default_port, service_name)
            return default_port
    
    return None


def _generate_tcp_probe(ports):
    """生成 TCP 探针（通用，只检查端口是否开放）"""
    if not ports:
        return None
    
    # 使用第一个端口
    port = ports[0].get('containerPort')
    
    return {
        'tcpSocket': {
            'port': port
        },
        'initialDelaySeconds': 60,      # 增加到60秒，给足启动时间
        'periodSeconds': 10,             # 每10秒检查一次
        'timeoutSeconds': 5,             # 5秒超时
        'successThreshold': 1,           # 成功1次即认为健康
        'failureThreshold': 6            # 失败6次才重启（60秒容错窗口）
    }


def _generate_pidof_probe(process_name, process_keyword):
    """
    生成 pidof 探针（轻量级，大多数镜像都支持）
    
    pidof 命令比 ps 更轻量，几乎所有 Linux 发行版都内置
    """
    if not process_name:
        return None
    
    # pidof 在大多数镜像中都可用（busybox、alpine 等）
    # 如果 pidof 不可用，尝试使用 pgrep（也很常见）
    # 最后备用方案：检查 /proc 目录（最兼容）
    
    command = (
        f"pidof {process_name} || "
        f"pgrep -f '{process_keyword}' || "
        f"ps aux | grep '{process_keyword}' | grep -v grep"
    )
    
    return {
        'exec': {
            'command': [
                '/bin/sh',
                '-c',
                command
            ]
        },
        'initialDelaySeconds': 60,      # 增加到60秒，给足启动时间
        'periodSeconds': 10,             # 每10秒检查一次
        'timeoutSeconds': 5,             # 5秒超时
        'successThreshold': 1,           # 成功1次即认为健康
        'failureThreshold': 6            # 失败6次才重启（60秒容错窗口）
    }


def _generate_ps_probe(process_name, process_keyword):
    """
    生成 ps 探针（原有逻辑，仅用于明确指定的场景）
    
    注意：很多轻量级镜像没有 ps 命令，不推荐使用
    """
    if not process_name or not process_keyword:
        return None
    
    return {
        'exec': {
            'command': [
                '/bin/sh',
                '-c',
                f"ps -eo 'pid,comm,pcpu,rsz,args' | awk '($2 == \"{process_name}\" || $0 ~ /{process_keyword}/) && NR > 1 {{exit 0}} END {{if (NR <= 1) exit 1; exit 1}}'"
            ]
        },
        'initialDelaySeconds': 60,      # 增加到60秒，给足启动时间
        'periodSeconds': 10,             # 每10秒检查一次
        'timeoutSeconds': 5,             # 5秒超时
        'successThreshold': 1,           # 成功1次即认为健康
        'failureThreshold': 6            # 失败6次才重启（60秒容错窗口）
    }

# ==================== End of 健康检查探针辅助函数 ====================


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
        # 使用 escape_label_value 确保标签值符合 Kubernetes 规范
        escaped_name = api_utils.escape_label_value(data['name'])
        pod_spec_affinity = api_utils.convert_affinity(data['affinity'], const.Tag.POD_AFFINITY_TAG, escaped_name)
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = escaped_name
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = escaped_name
        
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
        
        # 获取部署脚本（如果提供）
        deploy_script = data.get('image_deploy_script')
        
        containers = api_utils.convert_container(images_data, pod_spec_envs, pod_spec_mnt_vols, pod_spec_limit, deploy_script)
        
        # 智能添加存活探针（基于容器端口和进程信息自动选择最佳探针类型）
        process_name = data.get('process_name')
        process_keyword = data.get('process_keyword')
        probe_type = data.get('probe_type', 'auto')  # 支持手动指定探针类型
        
        for container in containers:
            # 使用智能探针生成器
            liveness_probe = _generate_liveness_probe(
                container=container,
                process_name=process_name,
                process_keyword=process_keyword,
                probe_type=probe_type
            )
            if liveness_probe:
                container['livenessProbe'] = liveness_probe
                LOG.info('Added liveness probe for container "%s" (type: %s)', 
                        container.get('name'), probe_type)
        
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
        
        # 确保 namespace 有值，默认使用 'default'
        if not data.get('namespace') or data['namespace'].strip() == '':
            data['namespace'] = 'default'
            LOG.warning('namespace not provided or empty for Deployment %s, using default namespace', data.get('name'))
        
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
        # StatefulSet 的 metadata.name 必须符合 DNS-1123 label 规范（不允许点号）
        # 因为 Pod 的 hostname 会使用 <statefulset-name>-<ordinal> 格式
        # 所以这里使用 escape_service_name 而不是 escape_name
        resource_name = api_utils.escape_service_name(data['name'])
        resource_namespace = data['namespace']
        resource_tags = api_utils.convert_tag(data.get('tags', []))
        resource_tags[const.Tag.STATEFULSET_ID_TAG] = resource_id
        replicas = data['replicas']
        # 使用 escape_label_value 确保标签值符合 Kubernetes 规范
        escaped_name = api_utils.escape_label_value(data['name'])
        pod_spec_affinity = api_utils.convert_affinity(data['affinity'], const.Tag.POD_AFFINITY_TAG, escaped_name)
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = escaped_name
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = escaped_name
        
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
        
        # 获取部署脚本（如果提供）
        deploy_script = data.get('image_deploy_script')
        
        containers = api_utils.convert_container(images_data, pod_spec_envs, pod_spec_mnt_vols, pod_spec_limit, deploy_script)
        
        # 智能添加存活探针（基于容器端口和进程信息自动选择最佳探针类型）
        process_name = data.get('process_name')
        process_keyword = data.get('process_keyword')
        probe_type = data.get('probe_type', 'auto')  # 支持手动指定探针类型
        
        for container in containers:
            # 使用智能探针生成器
            liveness_probe = _generate_liveness_probe(
                container=container,
                process_name=process_name,
                process_keyword=process_keyword,
                probe_type=probe_type
            )
            if liveness_probe:
                container['livenessProbe'] = liveness_probe
                LOG.info('Added liveness probe for container "%s" (type: %s)', 
                        container.get('name'), probe_type)
        
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
        
        # StatefulSet 的 serviceName 必须符合 DNS-1035 规范
        service_name_for_sts = api_utils.escape_service_name(data.get('serviceName', resource_name))
        
        template = {
            'apiVersion': 'apps/v1',
            'kind': 'StatefulSet',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name
            },
            'spec': {
                'replicas': int(replicas),
                'serviceName': service_name_for_sts,
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
    
    def _ensure_loadbalancer_service(self, k8s_client, data, service_ports, pod_spec_tags):
        """
        为 StatefulSet 创建额外的负载均衡 Service（有 ClusterIP）
        这个 Service 用于提供 ClusterIP 给下游流程使用
        """
        # 负载均衡 Service 名称：原名称 + '-lb' 后缀
        lb_service_name = data.get('serviceName', data['name']) + '-lb'
        lb_service_name = api_utils.escape_service_name(lb_service_name)
        namespace = data['namespace']
        
        # 检查负载均衡 Service 是否已存在
        exists_lb_service = k8s_client.get_service(lb_service_name, namespace)
        if exists_lb_service is not None:
            # Service 已存在，返回其信息
            return lb_service_name
        
        # 创建负载均衡 Service（普通 ClusterIP Service）
        lb_service_resource_id = data['correlation_id'] + '-lb-service'
        lb_service_tags = api_utils.convert_tag(data.get('service_tags', data.get('tags', [])))
        lb_service_tags[const.Tag.SERVICE_ID_TAG] = lb_service_resource_id
        lb_service_tags['service-type'] = 'loadbalancer'  # 标记为负载均衡 Service
        
        lb_service_template = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'labels': lb_service_tags,
                'name': lb_service_name
            },
            'spec': {
                'type': 'ClusterIP',
                # 不设置 clusterIP 字段，让 Kubernetes 自动分配
                'selector': pod_spec_tags,
                'ports': service_ports
            }
        }
        
        # 创建负载均衡 Service
        k8s_client.create_service(namespace, lb_service_template)
        LOG.info('Created LoadBalancer Service %s/%s for StatefulSet %s/%s',
                 namespace, lb_service_name, namespace, data['name'])
        
        return lb_service_name

    def _sync_pods_to_cmdb(self, k8s_client, namespace, pod_list, instance_id):
        """同步 Pod 信息到 CMDB"""
        if not instance_id:
            LOG.warning('No instanceId provided, skipping CMDB sync')
            return
        
        try:
            from wecubek8s.common import wecmdb
            
            # 获取 CMDB 客户端（需要从配置中获取 CMDB 地址）
            cmdb_server = CONF.wecube.base_url
            if not cmdb_server:
                LOG.warning('CMDB base_url not configured, skipping CMDB sync')
                return
            cmdb_client = wecmdb.EntityClient(cmdb_server)
            
            # 1. 查询 CMDB 中该 instanceId 下的所有 Pod
            query_data = {
                "criteria": {
                    "attrName": "app_instance",  # CMDB 字段名：app_instance
                    "op": "eq",
                    "condition": instance_id
                }
            }
            
            LOG.info('Querying CMDB for pods with instanceId: %s', instance_id)
            cmdb_response = cmdb_client.query('wecmdb', 'pod', query_data)
            
            # 记录 CMDB 响应（用于调试）
            if cmdb_response:
                LOG.info('CMDB response status: %s', cmdb_response.get('status', 'unknown'))
                if cmdb_response.get('data'):
                    LOG.info('CMDB query returned %d pod records', len(cmdb_response['data']))
                else:
                    LOG.warning('CMDB query returned empty data for instanceId: %s', instance_id)
            else:
                LOG.warning('CMDB query returned None for instanceId: %s', instance_id)
            
            # 解析 CMDB 返回的 Pod 列表
            cmdb_pods = {}
            if cmdb_response and cmdb_response.get('data'):
                for idx, pod_data in enumerate(cmdb_response['data']):
                    # 记录第一个 pod 的所有字段（用于调试字段名问题）
                    if idx == 0:
                        LOG.info('CMDB pod record fields: %s', ', '.join(pod_data.keys()) if pod_data else 'empty')
                    
                    pod_code = pod_data.get('code')  # CMDB 字段名：code（Pod 名称）
                    if pod_code:
                        cmdb_pods[pod_code] = {
                            'guid': pod_data.get('guid'),  # CMDB 字段名：guid（记录标识符）
                            'asset_id': pod_data.get('asset_id')  # CMDB 字段名：asset_id（K8s Pod UID）
                        }
                        LOG.info('Found CMDB pod [%d]: code=%s, guid=%s, asset_id=%s', 
                                idx + 1, pod_code, pod_data.get('guid'), pod_data.get('asset_id'))
                    else:
                        LOG.warning('CMDB pod record [%d] has no "code" field: %s', idx + 1, list(pod_data.keys()))
                LOG.info('Total CMDB pod names found: [%s]', ', '.join(cmdb_pods.keys()) if cmdb_pods else 'None')
            
            # 2. 对比 K8s 实际的 Pod 列表，找出需要创建和更新的 Pod
            LOG.info('K8s running pods: %s', ', '.join([p['name'] for p in pod_list]) if pod_list else 'None')
            
            creates = []  # 需要创建的 Pod
            updates = []  # 需要更新的 Pod
            
            for pod_info in pod_list:
                pod_name = pod_info['name']
                pod_id = pod_info['id']
                
                # 如果 Pod ID 为空，说明 Pod 还没有创建，跳过
                if not pod_id:
                    LOG.info('Pod %s has no ID yet (not created), skipping CMDB sync', pod_name)
                    continue
                
                if pod_name in cmdb_pods:
                    # Pod 已存在于 CMDB，检查是否需要更新
                    cmdb_pod = cmdb_pods[pod_name]
                    if cmdb_pod['asset_id'] != pod_id:
                        # Pod ID 发生变化（可能是 Pod 被重建），需要更新
                        updates.append({
                            'guid': cmdb_pod['guid'],  # CMDB 字段名：guid（记录标识符）
                            'asset_id': pod_id  # CMDB 字段名：asset_id（新的 K8s Pod UID）
                        })
                        LOG.info('Pod %s ID changed: %s -> %s, will update', 
                                pod_name, cmdb_pod['asset_id'], pod_id)
                    else:
                        LOG.debug('Pod %s ID unchanged: %s', pod_name, pod_id)
                else:
                    # Pod 不存在于 CMDB，需要创建
                    creates.append({
                        'code': pod_name,  # CMDB 字段名：code（Pod 名称）
                        'asset_id': pod_id,  # CMDB 字段名：asset_id（K8s Pod UID）
                        'app_instance': instance_id  # CMDB 字段名：app_instance（关联的 StatefulSet）
                    })
                    LOG.info('Pod %s (ID: %s) not found in CMDB, will create', pod_name, pod_id)
            
            # 3. 批量创建和更新 CMDB
            if creates:
                LOG.info('Creating %d new pods in CMDB', len(creates))
                try:
                    cmdb_client.create('wecmdb', 'pod', creates)
                    LOG.info('Successfully created %d pods in CMDB', len(creates))
                except Exception as e:
                    LOG.error('Failed to create pods in CMDB: %s', str(e))
            
            if updates:
                LOG.info('Updating %d existing pods in CMDB', len(updates))
                try:
                    cmdb_client.update('wecmdb', 'pod', updates)
                    LOG.info('Successfully updated %d pods in CMDB', len(updates))
                except Exception as e:
                    LOG.error('Failed to update pods in CMDB: %s', str(e))
            
            if not creates and not updates:
                LOG.info('All pods in sync with CMDB, no changes needed')
                
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
        
        # 确保 namespace 有值，默认使用 'default'
        if not data.get('namespace') or data['namespace'].strip() == '':
            data['namespace'] = 'default'
            LOG.warning('namespace not provided or empty for StatefulSet %s, using default namespace', data.get('name'))
        
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
        
        # 补充返回对应 Service 的 clusterIP 与 port
        # 策略：优先返回负载均衡 Service 的 ClusterIP（如果存在），否则返回 Headless Service 信息
        cluster_ip = None
        port_str = ""
        
        # 1. 尝试获取负载均衡 Service（带 -lb 后缀）
        lb_service_name = api_utils.escape_service_name(data.get('serviceName', data['name']) + '-lb')
        lb_svc = k8s_client.get_service(lb_service_name, data['namespace'])
        
        if lb_svc and lb_svc.spec.cluster_ip and lb_svc.spec.cluster_ip != 'None':
            # 使用负载均衡 Service 的 ClusterIP
            cluster_ip = lb_svc.spec.cluster_ip
            if getattr(lb_svc.spec, 'ports', None) and len(lb_svc.spec.ports) > 0:
                port_str = str(lb_svc.spec.ports[0].port)
            LOG.info('Using LoadBalancer Service %s ClusterIP: %s', lb_service_name, cluster_ip)
        else:
            # 2. 如果没有负载均衡 Service，尝试创建一个
            # 先获取 Pod 标签和端口信息
            pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
            pod_spec_tags[const.Tag.POD_AUTO_TAG] = api_utils.escape_label_value(data['name'])
            pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = api_utils.escape_label_value(data['name'])
            
            # 获取 Service 端口
            service_ports = []
            if data.get('servicePorts'):
                service_ports = api_utils.convert_service_port(data['servicePorts'])
            elif data.get('image_port'):
                container_ports = api_utils.convert_pod_ports(data.get('image_port', ''))
                for port_info in container_ports:
                    port = port_info.get('containerPort')
                    if port:
                        service_ports.append({
                            'port': port,
                            'targetPort': port,
                            'protocol': port_info.get('protocol', 'TCP')
                        })
            
            if not service_ports:
                service_ports = [{
                    'name': 'default',
                    'port': 80,
                    'targetPort': 80,
                    'protocol': 'TCP'
                }]
            
            # 创建负载均衡 Service
            lb_service_name = self._ensure_loadbalancer_service(k8s_client, data, service_ports, pod_spec_tags)
            
            # 重新获取创建的 Service
            lb_svc = k8s_client.get_service(lb_service_name, data['namespace'])
            if lb_svc:
                cluster_ip = lb_svc.spec.cluster_ip if lb_svc.spec.cluster_ip else None
                if cluster_ip == 'None':
                    cluster_ip = None
                if getattr(lb_svc.spec, 'ports', None) and len(lb_svc.spec.ports) > 0:
                    port_str = str(lb_svc.spec.ports[0].port)
                LOG.info('Created and using LoadBalancer Service %s ClusterIP: %s', lb_service_name, cluster_ip)
        
        # 3. 如果仍然没有 ClusterIP，记录警告
        if not cluster_ip:
            LOG.warning('No ClusterIP available for StatefulSet %s/%s', data['namespace'], data['name'])
        
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
                LOG.info('Found %d running pods for StatefulSet %s in namespace %s', 
                        len(pod_list), resource_name, data['namespace'])
            else:
                # 如果还没有 Pod 运行，使用预期的 Pod 名称（ID 暂时为空）
                # 这是正常现象：StatefulSet 刚创建时，Pod 会异步创建
                LOG.info('No running pods found yet for StatefulSet %s in namespace %s (pods may still be creating), using expected pod names', 
                        resource_name, data['namespace'])
                for i in range(replicas):
                    pod_list.append({
                        'name': f"{resource_name}-{i}",
                        'id': ''
                    })
        except Exception as e:
            LOG.warning('Failed to query pods for StatefulSet %s in namespace %s: %s. Using expected pod names.', 
                       resource_name, data['namespace'], str(e))
            # 使用预期的 Pod 名称
            for i in range(replicas):
                pod_list.append({
                    'name': f"{resource_name}-{i}",
                    'id': ''
                })
        
        # 使用 correlation_id（即 instanceId）同步 Pod 信息到 CMDB
        if resource_id and pod_list:
            # 如果 Pod 还没有 ID，等待一段时间让 Pod 创建完成
            max_wait_time = 30  # 最多等待 30 秒
            wait_interval = 2   # 每 2 秒检查一次
            waited_time = 0
            
            # 检查是否有 Pod 没有 ID
            pods_without_id = [p for p in pod_list if not p.get('id')]
            if pods_without_id:
                LOG.info('Waiting for %d pod(s) to be created: %s', 
                        len(pods_without_id), ', '.join([p['name'] for p in pods_without_id]))
                
                while waited_time < max_wait_time and pods_without_id:
                    time.sleep(wait_interval)
                    waited_time += wait_interval
                    
                    # 重新查询 Pod 状态
                    try:
                        pods = k8s_client.list_pod(data['namespace'], label_selector=label_selector)
                        if pods and pods.items:
                            # 更新 pod_list 中的 ID
                            pod_dict = {pod.metadata.name: pod.metadata.uid for pod in pods.items}
                            for pod_info in pod_list:
                                if pod_info['name'] in pod_dict:
                                    pod_info['id'] = pod_dict[pod_info['name']]
                            
                            # 重新检查还有哪些 Pod 没有 ID
                            pods_without_id = [p for p in pod_list if not p.get('id')]
                            if not pods_without_id:
                                LOG.info('All pods created successfully after waiting %d seconds', waited_time)
                                break
                            else:
                                LOG.info('Still waiting for %d pod(s) after %d seconds: %s', 
                                        len(pods_without_id), waited_time, 
                                        ', '.join([p['name'] for p in pods_without_id]))
                    except Exception as e:
                        LOG.warning('Failed to query pod status during wait: %s', str(e))
                
                if pods_without_id:
                    LOG.warning('Timeout waiting for pods to be created after %d seconds, will sync available pods only', 
                               max_wait_time)
            
            # 同步 Pod 信息到 CMDB（只同步有 ID 的 Pod）
            self._sync_pods_to_cmdb(k8s_client, data['namespace'], pod_list, resource_id)
        
        # 将 Pod 列表转换为字符串格式（用分号拼接），方便页面显示
        pods_str = ';'.join([pod['name'] for pod in pod_list]) if pod_list else ''
        
        # 构建返回结果
        result = {
            'id': exists_resource.metadata.uid,
            'name': exists_resource.metadata.name,
            'correlation_id': resource_id,
            'clusterIP': cluster_ip,
            'port': port_str,
            'pods': pods_str  # 返回 Pod 名称字符串，用分号拼接
        }
        
        # 记录返回信息到日志（方便使用 docker logs 查看）
        LOG.info('StatefulSet apply result: id=%s, name=%s, correlation_id=%s, clusterIP=%s, port=%s, pods=%s',
                result['id'], result['name'], result['correlation_id'], 
                result['clusterIP'], result['port'], result['pods'])
        
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return result

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
        
        # 确保 namespace 有值，默认使用 'default'
        if not data.get('namespace') or data['namespace'].strip() == '':
            data['namespace'] = 'default'
            LOG.warning('namespace not provided or empty for Service %s, using default namespace', data.get('name'))
        
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