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
        probe_type: 探针类型 ('auto', 'tcp', 'exec', 'pidof', 'none')
    
    Returns:
        dict: Liveness Probe 配置，如果返回 None 则不添加探针
    
    简化逻辑：
        - 有端口 → TCP 探针
        - 无端口 → 进程检测（pidof 或 exec）
    """
    
    # 如果明确指定不使用探针
    if probe_type == 'none':
        return None
    
    container_name = container.get('name', '')
    ports = container.get('ports', [])
    image = container.get('image', '')
    
    # 添加调试日志：查看容器的端口配置
    LOG.info('[PROBE DEBUG] Container: %s, Ports: %s, Image: %s, ProbeType: %s', 
             container_name, ports, image, probe_type)
    
    # 自动模式：智能选择最合适的探针类型
    if probe_type == 'auto':
        probe_type = _auto_detect_probe_type(container_name, ports, process_name, image)
        LOG.info('[PROBE DEBUG] Auto-detected probe type for %s: %s', container_name, probe_type)
    
    # 根据探针类型生成配置（仅支持 TCP 和进程检测）
    if probe_type == 'tcp':
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
    
    简化逻辑：
    1. 如果有端口配置 → TCP 探针（检查端口连接性，最可靠）
    2. 如果没有端口，但有进程名 → pidof 探针（进程检测）
    3. 其他情况 → pidof 探针（兜底方案）
    """
    
    # 如果配置了端口，直接使用 TCP 探针
    if ports and len(ports) > 0:
        LOG.info('Detected service ports (%d port(s)), using TCP probe', len(ports))
        return 'tcp'
    
    # 没有端口配置，使用进程检测
    if process_name:
        LOG.info('No ports configured, using pidof probe for process: %s', process_name)
        return 'pidof'
    
    # 兜底：没有端口也没有进程名，使用 pidof 探针
    LOG.warning('No ports or process_name configured, using pidof probe as fallback')
    return 'pidof'


# ============================================================================
# HTTP 探针相关函数（已弃用，保留代码以备将来使用）
# 原因：HTTP 探针依赖应用实现健康检查接口，容易出现 404 等问题
# 当前策略：有端口用 TCP 探针，无端口用进程检测
# ============================================================================

# def _generate_http_probe(ports, image=None):
#     """
#     生成 HTTP 探针（最可靠，适用于 Web 服务）
#     
#     【已弃用】改用 TCP 探针，避免 HTTP 404 等问题
#     
#     如果没有配置端口，会尝试从镜像名推断默认端口
#     """
#     port = None
#     
#     # 1. 优先使用配置的端口
#     if ports and len(ports) > 0:
#         # 智能选择最合适的 HTTP 端口
#         port = _select_best_http_port(ports)
#         LOG.info('[HTTP PROBE] Selected port %s from %d available ports', port, len(ports))
#     
#     # 2. 如果没有配置端口，从镜像名推断
#     if not port and image:
#         port = _infer_default_port_from_image(image)
#     
#     # 3. 仍然没有端口，使用默认的 80
#     if not port:
#         LOG.warning('No port configured for HTTP probe, using default port 80')
#         port = 80
#     
#     LOG.info('Using HTTP probe on port %s (image: %s)', port, image or 'unknown')
#     
#     return {
#         'httpGet': {
#             'path': '/',
#             'port': port,
#             'scheme': 'HTTP'
#         },
#         'initialDelaySeconds': 60,      # 增加到60秒，给足启动时间
#         'periodSeconds': 10,             # 每10秒检查一次
#         'timeoutSeconds': 5,             # 5秒超时
#         'successThreshold': 1,           # 成功1次即认为健康
#         'failureThreshold': 6            # 失败6次才重启（60秒容错窗口）
#     }


# def _infer_default_port_from_image(image):
#     """
#     从镜像名称推断默认端口
#     
#     【已弃用】改用 TCP 探针，避免 HTTP 404 等问题
#     
#     Args:
#         image: 镜像名称（例如：nginx, tomcat:9.0, registry.io/apache:latest）
#     
#     Returns:
#         int: 推断的端口号，如果无法推断则返回 None
#     """
#     if not image:
#         return None
#     
#     image_lower = image.lower()
#     
#     # 常见服务的默认端口映射
#     PORT_MAPPINGS = {
#         'nginx': 80,
#         'httpd': 80,
#         'apache': 80,
#         'tomcat': 8080,
#         'jetty': 8080,
#         'wildfly': 8080,
#         'jboss': 8080,
#         'caddy': 80,
#         'traefik': 80,
#         'haproxy': 80,
#         'lighttpd': 80,
#         'redis': 6379,
#         'mysql': 3306,
#         'mariadb': 3306,
#         'postgres': 5432,
#         'postgresql': 5432,
#         'mongodb': 27017,
#         'mongo': 27017
#     }
#     
#     for service_name, default_port in PORT_MAPPINGS.items():
#         if service_name in image_lower:
#             LOG.info('Inferred port %d for image containing "%s"', default_port, service_name)
#             return default_port
#     
#     return None


# def _select_best_http_port(ports):
#     """
#     从多个端口中智能选择最适合 HTTP 探针的端口
#     
#     【已弃用】改用 TCP 探针，避免 HTTP 404 等问题
#     
#     优先级：
#     1. 常见的 Web 服务端口 (80, 443, 8080, 8000, 3000, 5000, 9000 等)
#     2. 8xxx 系列端口（通常是 Web 应用）
#     3. 3xxx、5xxx、9xxx 系列端口
#     4. 第一个大于 1024 的端口
#     5. 第一个端口
#     
#     Args:
#         ports: 端口配置列表，每个元素是 {'containerPort': xxx, 'protocol': 'TCP'}
#     
#     Returns:
#         int: 选中的端口号
#     """
#     if not ports:
#         return None
#     
#     # 提取所有端口号
#     port_numbers = [p.get('containerPort') for p in ports if p.get('containerPort')]
#     
#     if not port_numbers:
#         return None
#     
#     LOG.info('[PORT SELECTION] Available ports for HTTP probe: %s', port_numbers)
#     
#     # 常见的 HTTP 服务端口（按优先级排序）
#     HTTP_PRIORITY_PORTS = [8080, 80, 8000, 8008, 443, 3000, 5000, 9000, 8888]
#     
#     # 1. 优先选择常见的 HTTP 端口
#     for priority_port in HTTP_PRIORITY_PORTS:
#         if priority_port in port_numbers:
#             LOG.info('[PORT SELECTION] Selected priority HTTP port: %d', priority_port)
#             return priority_port
#     
#     # 2. 选择 8xxx 系列端口（8000-8999，通常是 Web 应用）
#     for port in port_numbers:
#         if 8000 <= port <= 8999:
#             LOG.info('[PORT SELECTION] Selected 8xxx series port: %d', port)
#             return port
#     
#     # 3. 选择其他常见 Web 端口范围（3000-3999, 5000-5999, 9000-9999）
#     for port in port_numbers:
#         if 3000 <= port <= 3999 or 5000 <= port <= 5999 or 9000 <= port <= 9999:
#             LOG.info('[PORT SELECTION] Selected common web port: %d', port)
#             return port
#     
#     # 4. 选择第一个大于 1024 的端口（非特权端口）
#     for port in port_numbers:
#         if port > 1024:
#             LOG.info('[PORT SELECTION] Selected first non-privileged port: %d', port)
#             return port
#     
#     # 5. 默认返回第一个端口
#     selected_port = port_numbers[0]
#     LOG.info('[PORT SELECTION] Selected first available port: %d', selected_port)
#     return selected_port


def _select_best_tcp_port(ports):
    """
    从多个端口中智能选择最适合 TCP 探针的端口
    
    对于 TCP 探针，我们更倾向于选择应用的主服务端口，而不是依赖服务端口（如数据库）
    
    优先级：
    1. 应用服务端口 (8xxx, 3xxx, 5xxx, 9xxx)
    2. 排除已知的依赖服务端口（Redis 6379, MySQL 3306, PostgreSQL 5432, MongoDB 27017）
    3. 第一个大于 1024 的端口
    4. 第一个端口
    
    Args:
        ports: 端口配置列表
    
    Returns:
        int: 选中的端口号
    """
    if not ports:
        return None
    
    port_numbers = [p.get('containerPort') for p in ports if p.get('containerPort')]
    
    if not port_numbers:
        return None
    
    LOG.info('[PORT SELECTION] Available ports for TCP probe: %s', port_numbers)
    
    # 已知的依赖服务端口（通常不应该作为应用探针的目标）
    DEPENDENCY_PORTS = {
        6379,   # Redis
        3306,   # MySQL
        5432,   # PostgreSQL
        27017,  # MongoDB
        5672,   # RabbitMQ
        9092,   # Kafka
        2181,   # Zookeeper
        11211,  # Memcached
        9200,   # Elasticsearch
        6380,   # Redis Sentinel
    }
    
    # 1. 优先选择常见的应用服务端口（排除依赖服务端口）
    APPLICATION_PRIORITY_PORTS = [8080, 8000, 8008, 8888, 3000, 5000, 9000]
    
    for priority_port in APPLICATION_PRIORITY_PORTS:
        if priority_port in port_numbers:
            LOG.info('[PORT SELECTION] Selected priority application port: %d', priority_port)
            return priority_port
    
    # 2. 选择应用服务端口范围，排除依赖服务端口
    for port in port_numbers:
        if port not in DEPENDENCY_PORTS:
            if 8000 <= port <= 8999 or 3000 <= port <= 3999 or 5000 <= port <= 5999 or 9000 <= port <= 9999:
                LOG.info('[PORT SELECTION] Selected application port (non-dependency): %d', port)
                return port
    
    # 3. 选择第一个非依赖服务端口
    for port in port_numbers:
        if port not in DEPENDENCY_PORTS and port > 1024:
            LOG.info('[PORT SELECTION] Selected first non-dependency port: %d', port)
            return port
    
    # 4. 实在没有，选择第一个端口（即使是依赖服务端口）
    selected_port = port_numbers[0]
    if selected_port in DEPENDENCY_PORTS:
        LOG.warning('[PORT SELECTION] Selected dependency service port %d - this may not be ideal for application health checks', selected_port)
    else:
        LOG.info('[PORT SELECTION] Selected first available port: %d', selected_port)
    return selected_port


def _generate_tcp_probe(ports):
    """生成 TCP 探针（通用，只检查端口是否开放）"""
    LOG.info('[TCP PROBE DEBUG] Generating TCP probe, ports: %s', ports)
    
    if not ports:
        LOG.warning('[TCP PROBE DEBUG] No ports provided, returning None')
        return None
    
    # 智能选择最合适的端口
    port = _select_best_tcp_port(ports)
    LOG.info('[TCP PROBE DEBUG] Selected port %s from %d available ports', port, len(ports))
    
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
        # 使用 resource_name 作为标签值，确保标签值与资源名称保持一致（都是小写转换后的值）
        # 这样可以避免因原始名称大小写不一致导致的标签选择器查询失败
        pod_spec_affinity = api_utils.convert_affinity(data['affinity'], const.Tag.POD_AFFINITY_TAG, resource_name)
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = resource_name
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = resource_name
        
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
                # 检测实际使用的探针类型
                actual_probe_type = 'unknown'
                if 'httpGet' in liveness_probe:
                    actual_probe_type = 'http'
                elif 'tcpSocket' in liveness_probe:
                    actual_probe_type = 'tcp'
                elif 'exec' in liveness_probe:
                    actual_probe_type = 'exec/pidof'
                LOG.info('Added liveness probe for container "%s" (requested: %s, actual: %s, config: %s)', 
                        container.get('name'), probe_type, actual_probe_type, liveness_probe)
            else:
                LOG.warning('No liveness probe generated for container "%s" (requested type: %s)', 
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
            service_body['spec']['clusterIP'] = 'None'  # Headless Service (必须是字符串 "None")
        elif cluster_ip:
            service_body['spec']['clusterIP'] = cluster_ip

        # 创建或更新 Service
        exists_service = k8s_client.get_service(service_name, namespace)
        if exists_service is None:
            k8s_client.create_service(namespace, service_body)
            LOG.info('Created Service %s/%s for Deployment %s', namespace, service_name, data['name'])
        else:
            # 使用 replace 而不是 patch，需要保留 resourceVersion
            service_body['metadata']['resourceVersion'] = exists_service.metadata.resource_version
            k8s_client.update_service(service_name, namespace, service_body)
            LOG.info('Updated Service %s/%s for Deployment %s', namespace, service_name, data['name'])

    def apply(self, data):
        resource_id = data['correlation_id']
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
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
        resource_template = self.to_resource(k8s_client, data, cluster_info)
        exists_resource = k8s_client.get_deployment(resource_name, data['namespace'])
        if exists_resource is None:
            LOG.info('Creating new Deployment: %s/%s', data['namespace'], resource_name)
            exists_resource = k8s_client.create_deployment(data['namespace'], resource_template)
        else:
            LOG.info('Updating existing Deployment: %s/%s', data['namespace'], resource_name)
            
            # 使用 replace 而不是 patch,完全替换资源定义
            # 这样可以避免 patch 合并时保留旧字段的问题
            # 注意: replace 需要保留 resourceVersion
            resource_template['metadata']['resourceVersion'] = exists_resource.metadata.resource_version
            exists_resource = k8s_client.replace_deployment(resource_name, data['namespace'], resource_template)
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
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('api_server for cluster %s missing protocol, auto-adding https:// prefix: %s', 
                       cluster_info['name'], api_server)
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        
        # 确保 namespace 有默认值
        namespace = data.get('namespace', 'default')
        
        resource_name = api_utils.escape_name(data['name'])
        
        # 获取 correlation_id
        correlation_id = data.get('correlation_id', '')
        
        # 收集要返回的信息
        result = {
            'id': '',
            'name': resource_name,
            'namespace': namespace,
            'correlation_id': correlation_id,
            'deleted_resources': []
        }
        
        # 删除 Deployment（Pod 会被 Kubernetes 自动删除，因为有 OwnerReference）
        exists_resource = k8s_client.get_deployment(resource_name, namespace)
        if exists_resource is not None:
            result['id'] = exists_resource.metadata.uid
            LOG.info('Deleting Deployment: %s (uid=%s) in namespace: %s', 
                    resource_name, result['id'], namespace)
            k8s_client.delete_deployment(resource_name, namespace)
            result['deleted_resources'].append(f"Deployment/{resource_name}")
        else:
            LOG.warning('Deployment %s not found in namespace: %s', resource_name, namespace)
        
        # 删除关联的 Service（如果存在）
        service_name = api_utils.escape_name(data.get('serviceName', data['name']))
        exists_service = k8s_client.get_service(service_name, namespace)
        if exists_service is not None:
            LOG.info('Deleting Service: %s in namespace: %s', service_name, namespace)
            k8s_client.delete_service(service_name, namespace)
            result['deleted_resources'].append(f"Service/{service_name}")
        else:
            LOG.debug('Service %s not found in namespace: %s', service_name, namespace)
        
        # Pod 会被 Kubernetes 自动删除（通过 OwnerReference）
        LOG.info('Pods managed by Deployment %s will be automatically deleted by Kubernetes', resource_name)
        
        # 将已删除资源列表转换为字符串
        result['deleted_resources'] = ';'.join(result['deleted_resources']) if result['deleted_resources'] else ''
        
        # 记录删除结果到日志
        LOG.info('Deployment destroy result: id=%s, name=%s, namespace=%s, correlation_id=%s, deleted_resources=%s',
                result['id'], result['name'], result['namespace'], result['correlation_id'], result['deleted_resources'])
        
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return result


class StatefulSet:
    def to_resource(self, k8s_client, data, cluster_info):
        resource_id = data['correlation_id']
        # StatefulSet 的 metadata.name 必须符合 DNS-1123 label 规范（不允许点号）
        # 因为 Pod 的 hostname 会使用 <statefulset-name>-<ordinal> 格式
        # 所以这里使用 escape_service_name 而不是 escape_name
        # 【关键】限制为 50 字符，预留空间给 Kubernetes 自动添加的后缀（controller-revision-hash 等）
        # 否则会导致 "metadata.labels: Invalid value: must be no more than 63 characters" 错误
        # 【修复】自动移除 name 中可能包含的端口号后缀，避免因端口变化导致创建多个 StatefulSet
        normalized_name = api_utils.normalize_statefulset_name(data['name'])
        resource_name = api_utils.escape_service_name(normalized_name, max_length=50)
        resource_namespace = data['namespace']
        resource_tags = api_utils.convert_tag(data.get('tags', []))
        resource_tags[const.Tag.STATEFULSET_ID_TAG] = resource_id
        replicas = data['replicas']
        # 使用 resource_name 作为标签值，确保标签值与资源名称保持一致（都是小写转换后的值）
        # 这样可以避免因原始名称大小写不一致导致的标签选择器查询失败
        pod_spec_affinity = api_utils.convert_affinity(data['affinity'], const.Tag.POD_AFFINITY_TAG, resource_name)
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = resource_name
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = resource_name
        
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
                # 检测实际使用的探针类型
                actual_probe_type = 'unknown'
                if 'httpGet' in liveness_probe:
                    actual_probe_type = 'http'
                elif 'tcpSocket' in liveness_probe:
                    actual_probe_type = 'tcp'
                elif 'exec' in liveness_probe:
                    actual_probe_type = 'exec/pidof'
                LOG.info('Added liveness probe for container "%s" (requested: %s, actual: %s, config: %s)', 
                        container.get('name'), probe_type, actual_probe_type, liveness_probe)
            else:
                LOG.warning('No liveness probe generated for container "%s" (requested type: %s)', 
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
        # 【修复】必须先规范化 serviceName（移除端口号后缀），确保端口变化时不会导致 serviceName 改变
        # 因为 StatefulSet 的 spec.serviceName 字段是不可变的（immutable）
        raw_service_name = data.get('serviceName', data.get('name', ''))
        normalized_service_name = api_utils.normalize_statefulset_name(raw_service_name)
        service_name_for_sts = api_utils.escape_service_name(normalized_service_name)
        
        # 获取当前请求的用户 token，保存到 Pod annotations 中
        # 这样 watcher 可以从 Pod 读取 token 来访问 CMDB
        from wecubek8s.common import utils
        user_token = utils.get_token()
        pod_annotations = {}
        if user_token:
            pod_annotations['wecube.io/creator-token'] = user_token
            LOG.info('Adding creator token to Pod annotations for CMDB access (token prefix: %s...)', 
                    user_token[:20])
        
        # 【关键标记】添加创建来源标记，让 watcher 识别这是通过 API 创建的 Pod
        # 这样 watcher 就不会发送 WeCube 编排通知（只有 Pod 漂移/崩溃重启才通知）
        pod_annotations['wecube.io/created-by'] = 'api'
        LOG.info('Marking Pod as created by API to prevent duplicate orchestration notifications')
        
        # 将 instanceId 保存到 StatefulSet annotations 中，供 watcher 读取
        # 这样 watcher 在处理 Pod 漂移时可以直接从 StatefulSet 获取 app_instance
        statefulset_annotations = {}
        if data.get('instanceId'):
            statefulset_annotations['wecube.io/app-instance'] = data['instanceId']
            LOG.info('Adding app-instance to StatefulSet annotations: %s', data['instanceId'])
        
        template = {
            'apiVersion': 'apps/v1',
            'kind': 'StatefulSet',
            'metadata': {
                'labels': resource_tags,
                'name': resource_name,
                'annotations': statefulset_annotations
            },
            'spec': {
                'replicas': int(replicas),
                'serviceName': service_name_for_sts,
                'selector': {
                    'matchLabels': pod_spec_tags
                },
                'template': {
                    'metadata': {
                        'labels': pod_spec_tags,
                        'annotations': pod_annotations
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
        # 【修复】无论用户是否指定 serviceName，都要规范化（移除端口号后缀）
        # 优先使用用户提供的 serviceName，其次使用 data['name']
        raw_name = data.get('serviceName', data['name'])
        # 规范化名称：移除可能的端口号后缀（如 :8080 或 -8080）
        service_name = api_utils.normalize_statefulset_name(raw_name)
        # Service 名称必须符合 DNS-1035 规范（比 DNS-1123 更严格）
        service_name = api_utils.escape_service_name(service_name)
        namespace = data['namespace']
        
        # 获取 Pod 标签作为 Service selector
        # 注意：标签值必须与创建 StatefulSet 时使用的值保持一致
        # StatefulSet 的 resource_name 是通过 normalize + escape_service_name 生成的
        normalized_name = api_utils.normalize_statefulset_name(data['name'])
        resource_name = api_utils.escape_service_name(normalized_name, max_length=50)
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        # 使用 resource_name 作为标签值，与创建 StatefulSet 时保持一致
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = resource_name
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = resource_name
        
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
                for idx, port_info in enumerate(container_ports):
                    port = port_info.get('containerPort')
                    if port:
                        protocol = port_info.get('protocol', 'TCP').lower()
                        # 生成端口名称：协议-端口号（如 tcp-8080）
                        # Kubernetes 要求端口名称最长 15 个字符，必须是小写字母、数字和 '-'
                        port_name = f'{protocol}-{port}'
                        # 如果名称太长，使用索引作为后缀（如 port-0, port-1）
                        if len(port_name) > 15:
                            port_name = f'port-{idx}'
                        
                        service_ports.append({
                            'name': port_name,
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
        
        # 构建 Headless Service 模板
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
                'clusterIP': 'None',  # Headless Service (必须是字符串 "None")
                'selector': pod_spec_tags,
                'ports': service_ports
            }
        }
        
        # 创建或更新 Headless Service
        exists_service = k8s_client.get_service(service_name, namespace)
        if exists_service is None:
            k8s_client.create_service(namespace, service_template)
            LOG.info('Created Headless Service %s/%s for StatefulSet %s/%s',
                     namespace, service_name, namespace, data['name'])
        else:
            # 使用 replace 而不是 patch，需要保留 resourceVersion
            service_template['metadata']['resourceVersion'] = exists_service.metadata.resource_version
            k8s_client.update_service(service_name, namespace, service_template)
            LOG.info('Updated Headless Service %s/%s for StatefulSet %s/%s',
                     namespace, service_name, namespace, data['name'])
    
    def _ensure_loadbalancer_service(self, k8s_client, data, service_ports, pod_spec_tags):
        """
        为 StatefulSet 创建额外的负载均衡 Service（有 ClusterIP）
        这个 Service 用于提供 ClusterIP 给下游流程使用
        """
        # 负载均衡 Service 名称：原名称 + '-lb' 后缀
        # 【修复】无论用户是否指定 serviceName，都要规范化（移除端口号后缀）
        # 优先使用用户提供的 serviceName，其次使用 data['name']
        raw_name = data.get('serviceName', data['name'])
        # 规范化名称：移除可能的端口号后缀（如 :8080 或 -8080）
        base_service_name = api_utils.normalize_statefulset_name(raw_name)
        lb_service_name = base_service_name + '-lb'
        lb_service_name = api_utils.escape_service_name(lb_service_name)
        namespace = data['namespace']
        
        # 构建负载均衡 Service 模板（普通 ClusterIP Service）
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
        
        # 创建或更新负载均衡 Service
        exists_lb_service = k8s_client.get_service(lb_service_name, namespace)
        if exists_lb_service is None:
            k8s_client.create_service(namespace, lb_service_template)
            LOG.info('Created LoadBalancer Service %s/%s for StatefulSet %s/%s',
                     namespace, lb_service_name, namespace, data['name'])
        else:
            # 使用 replace 而不是 patch，需要保留 resourceVersion
            lb_service_template['metadata']['resourceVersion'] = exists_lb_service.metadata.resource_version
            k8s_client.update_service(lb_service_name, namespace, lb_service_template)
            LOG.info('Updated LoadBalancer Service %s/%s for StatefulSet %s/%s',
                     namespace, lb_service_name, namespace, data['name'])
        
        return lb_service_name

    def _query_host_resource_guid(self, cmdb_client, pod_host_ip):
        """根据 IP 地址查询 CMDB 中对应的 host_resource 的 GUID
        
        Args:
            cmdb_client: CMDB 客户端
            pod_host_ip: Pod 所在 Node 的 IP 地址
        
        Returns:
            str: host_resource 的 GUID，如果查询失败或未找到则返回 None
        """
        if not pod_host_ip:
            return None
        
        try:
            query_data = {
                "criteria": {
                    "attrName": "ip_address",
                    "op": "eq",
                    "condition": pod_host_ip
                }
            }
            
            LOG.debug('Querying CMDB for host_resource with ip_address: %s', pod_host_ip)
            response = cmdb_client.query('wecmdb', 'host_resource', query_data)
            
            if response and response.get('data'):
                if len(response['data']) > 0:
                    host_resource_guid = response['data'][0].get('guid')
                    if host_resource_guid:
                        LOG.info('Found host_resource GUID: %s for IP: %s', host_resource_guid, pod_host_ip)
                        return host_resource_guid
                    else:
                        LOG.warning('host_resource record found but no guid field for IP: %s', pod_host_ip)
                else:
                    LOG.warning('No host_resource found in CMDB for IP: %s', pod_host_ip)
            else:
                LOG.warning('CMDB query for host_resource returned no data for IP: %s', pod_host_ip)
        except Exception as e:
            LOG.error('Failed to query host_resource from CMDB for IP %s: %s', pod_host_ip, str(e))
        
        return None
    
    def _validate_pod_health(self, k8s_client, statefulset_name, namespace, expected_replicas):
        """验证 Pod 的健康状态
        
        Args:
            k8s_client: Kubernetes 客户端
            statefulset_name: StatefulSet 名称
            namespace: 命名空间
            expected_replicas: 预期的副本数
        
        Returns:
            bool: 如果所有 Pod 都健康则返回 True，否则返回 False
        """
        try:
            # 获取 StatefulSet 的所有 Pod
            label_selector = f'{const.Tag.POD_AUTO_TAG}={statefulset_name}'
            pod_list = k8s_client.list_pod(namespace, label_selector=label_selector)
            
            if not pod_list or not pod_list.items:
                LOG.warning('No pods found for StatefulSet %s', statefulset_name)
                return False
            
            ready_count = 0
            for pod in pod_list.items:
                pod_name = pod.metadata.name
                phase = pod.status.phase if pod.status else 'Unknown'
                
                # 检查 Pod 的 Ready condition
                is_ready = False
                if pod.status and pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.type == 'Ready' and condition.status == 'True':
                            is_ready = True
                            break
                
                if phase == 'Running' and is_ready:
                    ready_count += 1
                    LOG.info('Pod %s is Running and Ready', pod_name)
                else:
                    LOG.warning('Pod %s - Phase: %s, Ready: %s', pod_name, phase, is_ready)
                    
                    # 记录容器状态
                    if pod.status and pod.status.container_statuses:
                        for container_status in pod.status.container_statuses:
                            if container_status.state.waiting:
                                LOG.warning('  Container %s waiting: %s - %s',
                                          container_status.name,
                                          container_status.state.waiting.reason,
                                          container_status.state.waiting.message or '')
                            elif container_status.state.terminated:
                                LOG.error('  Container %s terminated: %s (exit code %d)',
                                        container_status.name,
                                        container_status.state.terminated.reason or 'Unknown',
                                        container_status.state.terminated.exit_code or 0)
            
            return ready_count >= expected_replicas
        
        except Exception as e:
            LOG.error('Failed to validate pod health: %s', str(e))
            return False
    
    def _check_pod_failures(self, k8s_client, statefulset_name, namespace):
        """检查 Pod 是否有创建失败的情况
        
        Args:
            k8s_client: Kubernetes 客户端
            statefulset_name: StatefulSet 名称
            namespace: 命名空间
        """
        try:
            label_selector = f'{const.Tag.POD_AUTO_TAG}={statefulset_name}'
            pod_list = k8s_client.list_pod(namespace, label_selector=label_selector)
            
            if not pod_list or not pod_list.items:
                LOG.warning('No pods found for StatefulSet %s, may still be creating', statefulset_name)
                return
            
            for pod in pod_list.items:
                pod_name = pod.metadata.name
                phase = pod.status.phase if pod.status else 'Unknown'
                
                # 检查失败状态
                if phase in ['Failed', 'Unknown']:
                    LOG.error('❌ Pod %s is in %s state', pod_name, phase)
                
                # 检查容器状态
                if pod.status and pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        if container_status.state and container_status.state.waiting:
                            reason = container_status.state.waiting.reason
                            if reason in ['ImagePullBackOff', 'ErrImagePull', 'CrashLoopBackOff', 'CreateContainerConfigError']:
                                LOG.error('❌ Pod %s, Container %s: %s - %s',
                                        pod_name,
                                        container_status.name,
                                        reason,
                                        container_status.state.waiting.message or '')
        
        except Exception as e:
            LOG.warning('Failed to check pod failures: %s', str(e))
    
    def _get_pod_failure_details(self, k8s_client, statefulset_name, namespace):
        """获取 Pod 失败的详细信息
        
        Args:
            k8s_client: Kubernetes 客户端
            statefulset_name: StatefulSet 名称
            namespace: 命名空间
        
        Returns:
            str: Pod 失败的详细描述
        """
        try:
            label_selector = f'{const.Tag.POD_AUTO_TAG}={statefulset_name}'
            pod_list = k8s_client.list_pod(namespace, label_selector=label_selector)
            
            if not pod_list or not pod_list.items:
                return "No pods found"
            
            errors = []
            for pod in pod_list.items:
                pod_name = pod.metadata.name
                phase = pod.status.phase if pod.status else 'Unknown'
                
                if phase != 'Running':
                    errors.append(f"{pod_name}: phase={phase}")
                
                if pod.status and pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        if container_status.state:
                            if container_status.state.waiting:
                                reason = container_status.state.waiting.reason or 'Unknown'
                                message = container_status.state.waiting.message or ''
                                errors.append(f"{pod_name}/{container_status.name}: {reason} - {message[:100]}")
                            elif container_status.state.terminated:
                                reason = container_status.state.terminated.reason or 'Unknown'
                                exit_code = container_status.state.terminated.exit_code or 0
                                errors.append(f"{pod_name}/{container_status.name}: terminated - {reason} (exit {exit_code})")
            
            return '; '.join(errors) if errors else "Unknown error"
        
        except Exception as e:
            return f"Failed to get details: {str(e)}"
    
    def _sync_pods_to_cmdb(self, k8s_client, namespace, pod_list, instance_id):
        """同步 Pod 信息到 CMDB"""
        if not instance_id:
            LOG.warning('No instanceId provided, skipping CMDB sync')
            return
        
        try:
            from wecubek8s.common import wecmdb
            from wecubek8s.common import wecube
            
            # 获取 CMDB 客户端（需要从配置中获取 CMDB 地址）
            cmdb_server = CONF.wecube.base_url
            if not cmdb_server:
                LOG.warning('CMDB base_url not configured, skipping CMDB sync')
                return
            
            # 使用请求上下文中的用户 token（从 HTTP 请求头传入）
            # 这样创建的 Pod 记录会关联到该用户，watcher 也需要使用相同的 token 才能访问
            from wecubek8s.common import utils
            user_token = utils.get_token()
            cmdb_client = wecmdb.EntityClient(cmdb_server, user_token)
            LOG.info('Using user token for CMDB operations (token prefix: %s...)', 
                    user_token[:20] if user_token else 'None')
            
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
                pod_host_ip = pod_info.get('host_ip', '')  # Pod 所在 Node 的 IP
                
                # 如果 Pod ID 为空，说明 Pod 还没有创建，跳过
                if not pod_id:
                    LOG.info('Pod %s has no ID yet (not created), skipping CMDB sync', pod_name)
                    continue
                
                if pod_name in cmdb_pods:
                    # Pod 已存在于 CMDB，检查是否需要更新
                    cmdb_pod = cmdb_pods[pod_name]
                    if cmdb_pod['asset_id'] != pod_id:
                        # Pod ID 发生变化（可能是 Pod 被重建），需要更新
                        update_data = {
                            'guid': cmdb_pod['guid'],  # CMDB 字段名：guid（记录标识符）
                            'asset_id': pod_id  # CMDB 字段名：asset_id（新的 K8s Pod UID）
                        }
                        # 如果有 host_ip，查询对应的 host_resource GUID
                        if pod_host_ip:
                            host_resource_guid = self._query_host_resource_guid(cmdb_client, pod_host_ip)
                            if host_resource_guid:
                                update_data['host_resource'] = host_resource_guid  # CMDB 字段名：host_resource（关联的 host_resource GUID）
                                LOG.info('Pod %s will update with host_resource GUID: %s (IP: %s)', 
                                        pod_name, host_resource_guid, pod_host_ip)
                            else:
                                LOG.warning('Pod %s has host_ip %s but no matching host_resource found in CMDB', 
                                           pod_name, pod_host_ip)
                        updates.append(update_data)
                        LOG.info('Pod %s ID changed: %s -> %s, will update (host_ip: %s)', 
                                pod_name, cmdb_pod['asset_id'], pod_id, pod_host_ip or 'N/A')
                    else:
                        LOG.debug('Pod %s ID unchanged: %s', pod_name, pod_id)
                else:
                    # Pod 不存在于 CMDB，需要创建
                    create_data = {
                        'code': pod_name,  # CMDB 字段名：code（Pod 名称）
                        'asset_id': pod_id,  # CMDB 字段名：asset_id（K8s Pod UID）
                        'app_instance': instance_id  # CMDB 字段名：app_instance（关联的 StatefulSet）
                    }
                    # 如果有 host_ip，查询对应的 host_resource GUID
                    if pod_host_ip:
                        host_resource_guid = self._query_host_resource_guid(cmdb_client, pod_host_ip)
                        if host_resource_guid:
                            create_data['host_resource'] = host_resource_guid  # CMDB 字段名：host_resource（关联的 host_resource GUID）
                            LOG.info('Pod %s will create with host_resource GUID: %s (IP: %s)', 
                                    pod_name, host_resource_guid, pod_host_ip)
                        else:
                            LOG.warning('Pod %s has host_ip %s but no matching host_resource found in CMDB', 
                                       pod_name, pod_host_ip)
                    creates.append(create_data)
                    LOG.info('Pod %s (ID: %s, host_ip: %s) not found in CMDB, will create', 
                            pod_name, pod_id, pod_host_ip or 'N/A')
            
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
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
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
        # StatefulSet 的名称使用 escape_service_name（不允许点号），与 to_resource 方法保持一致
        # 【关键】限制为 50 字符，避免 Kubernetes 添加后缀后超过 63 字符限制
        # 【修复】自动移除 name 中可能包含的端口号后缀，避免因端口变化导致创建多个 StatefulSet
        normalized_name = api_utils.normalize_statefulset_name(data['name'])
        resource_name = api_utils.escape_service_name(normalized_name, max_length=50)
        
        # 生成 StatefulSet 资源模板
        resource_template = self.to_resource(k8s_client, data, cluster_info)
        
        # 确保关联的 Headless Service 存在，假如不存在则创建service
        self._ensure_headless_service(k8s_client, data, resource_template)
        
        exists_resource = k8s_client.get_statefulset(resource_name, data['namespace'])
        if exists_resource is None:
            LOG.info('Creating new StatefulSet: %s/%s', data['namespace'], resource_name)
            exists_resource = k8s_client.create_statefulset(data['namespace'], resource_template)
        else:
            LOG.info('Updating existing StatefulSet: %s/%s', data['namespace'], resource_name)

            # 使用 replace 而不是 patch,完全替换资源定义
            # 这样可以避免 patch 合并时保留旧字段的问题
            # 注意: replace 需要保留 resourceVersion
            resource_template['metadata']['resourceVersion'] = exists_resource.metadata.resource_version
            exists_resource = k8s_client.replace_statefulset(resource_name, data['namespace'], resource_template)
        
        # ==================== 等待 Pod 就绪（解决异步创建问题）====================
        replicas = int(data.get('replicas', 1))
        wait_for_pods = data.get('wait_for_ready', 'true').lower() == 'true'  # 可配置是否等待
        
        if wait_for_pods:
            LOG.info('Waiting for StatefulSet Pods to be ready (replicas: %d)...', replicas)
            pod_ready_timeout = int(data.get('pod_ready_timeout', 300))  # 默认等待 5 分钟
            check_interval = 5  # 每 5 秒检查一次
            max_attempts = pod_ready_timeout // check_interval
            
            for attempt in range(1, max_attempts + 1):
                time.sleep(check_interval)
                
                try:
                    # 重新读取 StatefulSet 状态
                    sts = k8s_client.get_statefulset(resource_name, data['namespace'])
                    
                    if sts and sts.status:
                        ready_replicas = sts.status.ready_replicas or 0
                        current_replicas = sts.status.replicas or 0
                        
                        LOG.info('[Wait %d/%d] StatefulSet status: %d/%d replicas ready', 
                                 attempt, max_attempts, ready_replicas, replicas)
                        
                        # 检查是否所有 Pod 都就绪
                        if ready_replicas >= replicas:
                            LOG.info('✅ All Pods are ready! (%d/%d)', ready_replicas, replicas)
                            
                            # 额外验证：检查实际的 Pod 状态
                            pod_validation_passed = self._validate_pod_health(
                                k8s_client, resource_name, data['namespace'], replicas
                            )
                            
                            if pod_validation_passed:
                                LOG.info('✅ Pod health validation passed!')
                                break
                            else:
                                LOG.warning('⚠️  Pod health validation failed, continuing to wait...')
                        else:
                            LOG.info('Still waiting: %d/%d replicas ready', ready_replicas, replicas)
                            
                            # 检查是否有 Pod 创建失败（30秒后开始检查）
                            if attempt > 6:
                                self._check_pod_failures(k8s_client, resource_name, data['namespace'])
                
                except Exception as e:
                    LOG.warning('[Wait %d/%d] Failed to check StatefulSet status: %s', 
                               attempt, max_attempts, str(e))
            
            else:
                # 超时后检查最终状态
                sts = k8s_client.get_statefulset(resource_name, data['namespace'])
                ready_replicas = sts.status.ready_replicas or 0 if sts and sts.status else 0
                
                if ready_replicas < replicas:
                    error_msg = self._get_pod_failure_details(k8s_client, resource_name, data['namespace'])
                    LOG.error('❌ Timeout waiting for Pods to be ready: %d/%d ready after %d seconds', 
                             ready_replicas, replicas, pod_ready_timeout)
                    LOG.error('Pod failure details: %s', error_msg)
                    
                    raise exceptions.PluginError(
                        message=_('StatefulSet created but Pods failed to become ready within %(timeout)ds. '
                                  'Ready: %(ready)d/%(expected)d. Details: %(details)s') % {
                            'timeout': pod_ready_timeout,
                            'ready': ready_replicas,
                            'expected': replicas,
                            'details': error_msg
                        }
                    )
        else:
            LOG.info('Skipping Pod readiness wait (wait_for_ready=false)')
        # ==================== 结束：等待 Pod 就绪 ====================
        
        # 补充返回对应 Service 的 clusterIP 与 port
        # 策略：优先返回负载均衡 Service 的 ClusterIP（如果存在），否则返回 Headless Service 信息
        cluster_ip = None
        port_str = ""
        
        # 【修复】无论 LoadBalancer Service 是否存在，都要确保它被创建/更新
        # 这样端口变更时才能正确更新 Service，避免只在首次创建时设置端口
        
        # 1. 准备 Pod 标签和端口信息
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        # 使用 resource_name（转换后的小写名称）作为标签值，与创建 StatefulSet 时保持一致
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = resource_name
        pod_spec_tags[const.Tag.POD_AFFINITY_TAG] = resource_name
        
        # 2. 获取 Service 端口
        service_ports = []
        if data.get('servicePorts'):
            service_ports = api_utils.convert_service_port(data['servicePorts'])
        elif data.get('image_port'):
            container_ports = api_utils.convert_pod_ports(data.get('image_port', ''))
            for idx, port_info in enumerate(container_ports):
                port = port_info.get('containerPort')
                if port:
                    protocol = port_info.get('protocol', 'TCP').lower()
                    # 生成端口名称：协议-端口号（如 tcp-8080）
                    # Kubernetes 要求端口名称最长 15 个字符，必须是小写字母、数字和 '-'
                    port_name = f'{protocol}-{port}'
                    # 如果名称太长，使用索引作为后缀（如 port-0, port-1）
                    if len(port_name) > 15:
                        port_name = f'port-{idx}'
                    
                    service_ports.append({
                        'name': port_name,
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
        
        # 3. 确保负载均衡 Service 存在并更新（与 Headless Service 保持一致的逻辑）
        lb_service_name = self._ensure_loadbalancer_service(k8s_client, data, service_ports, pod_spec_tags)
        
        # 4. 获取更新后的 Service 信息
        lb_svc = k8s_client.get_service(lb_service_name, data['namespace'])
        if lb_svc:
            cluster_ip = lb_svc.spec.cluster_ip if lb_svc.spec.cluster_ip else None
            if cluster_ip == 'None':
                cluster_ip = None
            if getattr(lb_svc.spec, 'ports', None) and len(lb_svc.spec.ports) > 0:
                port_str = str(lb_svc.spec.ports[0].port)
            LOG.info('Using LoadBalancer Service %s ClusterIP: %s, Port: %s', lb_service_name, cluster_ip, port_str)
        
        # 3. 如果仍然没有 ClusterIP，记录警告
        if not cluster_ip:
            LOG.warning('No ClusterIP available for StatefulSet %s/%s', data['namespace'], data['name'])
        
        # 获取实际的 Pod 列表（包含 name 和 id）
        replicas = int(data.get('replicas', 1))
        pod_list = []
        
        # 查询实际运行的 Pod，获取真实的 Pod ID
        # 使用 label selector 查询该 StatefulSet 的 Pod
        # 注意：标签值使用 resource_name（转换后的小写名称），与创建时保持一致
        label_selector = f"{const.Tag.POD_AUTO_TAG}={resource_name}"
        try:
            pods = k8s_client.list_pod(data['namespace'], label_selector=label_selector)
            if pods and pods.items:
                for pod in pods.items:
                    # 使用 cluster_id + pod_uid 作为全局唯一标识，与 watcher 保持一致
                    pod_uid = pod.metadata.uid if pod.metadata.uid else ''
                    asset_id = f"{cluster_info['id']}_{pod_uid}" if pod_uid else ''
                    pod_list.append({
                        'name': pod.metadata.name,
                        'id': asset_id,  # 使用带 cluster_id 前缀的 asset_id，与 watcher 保持一致
                        'host_ip': pod.status.host_ip if pod.status and pod.status.host_ip else ''  # Pod 所在 Node 的 IP
                    })
                LOG.info('Found %d pods for StatefulSet %s in namespace %s (some may not have UID yet)', 
                        len(pod_list), resource_name, data['namespace'])
            else:
                # 如果还没有 Pod 运行，使用预期的 Pod 名称（ID 暂时为空）
                # 这是正常现象：StatefulSet 刚创建时，Pod 会异步创建
                LOG.info('No running pods found yet for StatefulSet %s in namespace %s (pods may still be creating), using expected pod names', 
                        resource_name, data['namespace'])
                for i in range(replicas):
                    pod_list.append({
                        'name': f"{resource_name}-{i}",
                        'id': '',
                        'host_ip': ''
                    })
        except Exception as e:
            LOG.warning('Failed to query pods for StatefulSet %s in namespace %s: %s. Using expected pod names.', 
                       resource_name, data['namespace'], str(e))
            # 使用预期的 Pod 名称
            for i in range(replicas):
                pod_list.append({
                    'name': f"{resource_name}-{i}",
                    'id': '',
                    'host_ip': ''
                })
        
        # 使用 correlation_id（即 instanceId）同步 Pod 信息到 CMDB
        if resource_id and pod_list:
            # 如果 Pod 还没有 ID，等待一段时间让 Pod 创建完成
            # 注意：如果有 packageUrl，Pod 需要先运行 init container 下载部署包，会比较慢
            has_package = bool(data.get('packageUrl'))
            if has_package:
                max_wait_time = 240  # 有部署包时等待 240 秒（4分钟，init container 下载需要时间）
                LOG.info('Deployment has packageUrl, extending wait time to %d seconds', max_wait_time)
            else:
                max_wait_time = 30   # 无部署包时等待 30 秒
            
            wait_interval = 2   # 每 2 秒检查一次
            waited_time = 0
            
            # 检查是否有 Pod 没有 ID 或 host_ip
            pods_incomplete = [p for p in pod_list if not p.get('id') or not p.get('host_ip')]
            if pods_incomplete:
                pods_without_id = [p for p in pods_incomplete if not p.get('id')]
                pods_without_host = [p for p in pods_incomplete if (p.get('id') and not p.get('host_ip'))]
                LOG.info('Waiting for pods: %d without UID, %d without host_ip', 
                        len(pods_without_id), len(pods_without_host))
                if pods_without_id:
                    LOG.info('Pods without UID: %s', ', '.join([p['name'] for p in pods_without_id]))
                if pods_without_host:
                    LOG.info('Pods without host_ip (not scheduled yet): %s', ', '.join([p['name'] for p in pods_without_host]))
                
                while waited_time < max_wait_time and pods_incomplete:
                    time.sleep(wait_interval)
                    waited_time += wait_interval
                    
                    # 重新查询 Pod 状态
                    try:
                        pods = k8s_client.list_pod(data['namespace'], label_selector=label_selector)
                        if pods and pods.items:
                            # 检查 Pod 是否有失败情况
                            for pod in pods.items:
                                phase = pod.status.phase if pod.status else 'Unknown'
                                pod_name = pod.metadata.name
                                
                                # 检查致命错误状态
                                if phase == 'Failed':
                                    error_msg = f'Pod {pod_name} is in Failed state'
                                    LOG.error('❌ %s', error_msg)
                                    raise exceptions.PluginError(message=_('Pod creation failed: %(error)s') % {'error': error_msg})
                                
                                # 检查容器状态
                                if pod.status and pod.status.container_statuses:
                                    for container_status in pod.status.container_statuses:
                                        # 检查容器重启次数（超过3次认为异常）
                                        restart_count = container_status.restart_count or 0
                                        if restart_count > 3:
                                            error_msg = f'Container has restarted {restart_count} times (threshold: 3)'
                                            LOG.error('❌ Pod %s, Container %s: %s', pod_name, container_status.name, error_msg)
                                            
                                            # 获取更详细的状态信息
                                            detail_msg = error_msg
                                            if container_status.state:
                                                if container_status.state.waiting:
                                                    reason = container_status.state.waiting.reason or 'Unknown'
                                                    detail_msg += f', current state: waiting ({reason})'
                                                elif container_status.state.terminated:
                                                    exit_code = container_status.state.terminated.exit_code or 0
                                                    reason = container_status.state.terminated.reason or 'Unknown'
                                                    detail_msg += f', current state: terminated (exit {exit_code}, {reason})'
                                            
                                            raise exceptions.PluginError(
                                                message=_('Pod container crashed repeatedly: %(pod)s/%(container)s - %(error)s') % {
                                                    'pod': pod_name,
                                                    'container': container_status.name,
                                                    'error': detail_msg
                                                }
                                            )
                                        
                                        if container_status.state and container_status.state.waiting:
                                            reason = container_status.state.waiting.reason
                                            # 检查严重错误（镜像拉取失败、配置错误、崩溃循环等）
                                            if reason in ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError', 
                                                         'InvalidImageName', 'CrashLoopBackOff']:
                                                error_msg = container_status.state.waiting.message or reason
                                                # 如果是 CrashLoopBackOff，添加重启次数信息
                                                if reason == 'CrashLoopBackOff':
                                                    error_msg = f'{error_msg} (restarted {restart_count} times)'
                                                LOG.error('❌ Pod %s, Container %s: %s', pod_name, container_status.name, error_msg)
                                                raise exceptions.PluginError(
                                                    message=_('Pod container failed: %(pod)s/%(container)s - %(error)s') % {
                                                        'pod': pod_name,
                                                        'container': container_status.name,
                                                        'error': error_msg
                                                    }
                                                )
                                        elif container_status.state and container_status.state.terminated:
                                            # 容器已终止且退出码非0表示异常
                                            exit_code = container_status.state.terminated.exit_code or 0
                                            if exit_code != 0:
                                                reason = container_status.state.terminated.reason or 'Unknown'
                                                LOG.error('❌ Pod %s, Container %s terminated with exit code %d: %s',
                                                        pod_name, container_status.name, exit_code, reason)
                                                raise exceptions.PluginError(
                                                    message=_('Pod container terminated abnormally: %(pod)s/%(container)s - exit code %(code)d') % {
                                                        'pod': pod_name,
                                                        'container': container_status.name,
                                                        'code': exit_code
                                                    }
                                                )
                            
                            # 更新 pod_list 中的 ID 和 host_ip（只记录有 UID 的 Pod）
                            pod_dict = {pod.metadata.name: {
                                            'uid': pod.metadata.uid,
                                            'host_ip': pod.status.host_ip if pod.status and pod.status.host_ip else '',
                                            'phase': pod.status.phase if pod.status else 'Unknown',
                                            'ready': False
                                        }
                                       for pod in pods.items if pod.metadata.uid}
                            
                            # 检查 Pod 的 Ready 状态
                            for pod in pods.items:
                                if pod.metadata.name in pod_dict and pod.status and pod.status.conditions:
                                    for condition in pod.status.conditions:
                                        if condition.type == 'Ready' and condition.status == 'True':
                                            pod_dict[pod.metadata.name]['ready'] = True
                                            break
                            
                            # 同时记录 Pod 的状态信息（用于调试）
                            for pod in pods.items:
                                phase = pod.status.phase if pod.status else 'Unknown'
                                uid_status = f'UID: {pod.metadata.uid[:8]}...' if pod.metadata.uid else 'UID: None'
                                host_ip_status = f'host_ip: {pod.status.host_ip}' if pod.status and pod.status.host_ip else 'host_ip: None'
                                ready_status = 'Ready' if pod.metadata.name in pod_dict and pod_dict[pod.metadata.name]['ready'] else 'NotReady'
                                
                                # 检查容器重启次数和状态
                                container_info = ''
                                if pod.status and pod.status.container_statuses:
                                    total_restarts = sum(cs.restart_count or 0 for cs in pod.status.container_statuses)
                                    if total_restarts > 0:
                                        container_info = f' [Restarts: {total_restarts}]'
                                    # 检查是否有异常状态
                                    for cs in pod.status.container_statuses:
                                        if cs.state and cs.state.waiting:
                                            reason = cs.state.waiting.reason or 'Unknown'
                                            if reason in ['CrashLoopBackOff', 'ImagePullBackOff', 'ErrImagePull']:
                                                container_info += f' [{cs.name}: {reason}]'
                                
                                # 检查 init container 状态
                                init_status = ''
                                if pod.status and pod.status.init_container_statuses:
                                    for init_container in pod.status.init_container_statuses:
                                        if init_container.state:
                                            if init_container.state.running:
                                                init_status = f' [Init: {init_container.name} running]'
                                            elif init_container.state.waiting:
                                                reason = init_container.state.waiting.reason or 'Unknown'
                                                init_status = f' [Init: {init_container.name} waiting - {reason}]'
                                            elif init_container.state.terminated:
                                                init_status = f' [Init: {init_container.name} completed]'
                                
                                if pod.metadata.name in [p['name'] for p in pods_incomplete]:
                                    LOG.debug('Pod %s status: %s, %s, %s, %s%s%s', pod.metadata.name, phase, uid_status, host_ip_status, ready_status, container_info, init_status)
                            
                            for pod_info in pod_list:
                                if pod_info['name'] in pod_dict:
                                    pod_info['id'] = pod_dict[pod_info['name']]['uid']
                                    pod_info['host_ip'] = pod_dict[pod_info['name']]['host_ip']
                            
                            # 重新检查还有哪些 Pod 不完整（没有 ID 或 host_ip）
                            pods_incomplete = [p for p in pod_list if not p.get('id') or not p.get('host_ip')]
                            
                            # 检查所有 Pod 是否都已就绪
                            all_pods_ready = all(pod_dict.get(p['name'], {}).get('ready', False) for p in pod_list if p.get('id'))
                            
                            if not pods_incomplete and all_pods_ready:
                                LOG.info('✅ All pods created, scheduled and ready after waiting %d seconds', waited_time)
                                break
                            else:
                                pods_without_id = [p for p in pods_incomplete if not p.get('id')]
                                pods_without_host = [p for p in pods_incomplete if (p.get('id') and not p.get('host_ip'))]
                                pods_not_ready = [p['name'] for p in pod_list if p.get('id') and not pod_dict.get(p['name'], {}).get('ready', False)]
                                LOG.info('Still waiting after %d seconds: %d without UID, %d without host_ip, %d not ready', 
                                        waited_time, len(pods_without_id), len(pods_without_host), len(pods_not_ready))
                    except exceptions.PluginError:
                        # 重新抛出业务异常
                        raise
                    except Exception as e:
                        LOG.warning('Failed to query pod status during wait: %s', str(e))
                
                # 等待循环结束后，检查是否所有 Pod 都已完成
                if pods_incomplete:
                    pods_without_id = [p for p in pods_incomplete if not p.get('id')]
                    pods_without_host = [p for p in pods_incomplete if (p.get('id') and not p.get('host_ip'))]
                    LOG.warning('Timeout after %d seconds: %d pod(s) without UID, %d pod(s) without host_ip, will do final check', 
                               max_wait_time, len(pods_without_id), len(pods_without_host))
            
            # 在等待循环结束后，做最后一次强制查询，验证所有 Pod 的状态
            try:
                LOG.info('Performing final pod status check...')
                pods = k8s_client.list_pod(data['namespace'], label_selector=label_selector)
                if pods and pods.items:
                    # 构建 Pod 状态字典，包含完整的状态信息
                    pod_dict = {}
                    for pod in pods.items:
                        if pod.metadata.uid:
                            is_ready = False
                            if pod.status and pod.status.conditions:
                                for condition in pod.status.conditions:
                                    if condition.type == 'Ready' and condition.status == 'True':
                                        is_ready = True
                                        break
                            
                            pod_dict[pod.metadata.name] = {
                                'uid': pod.metadata.uid,
                                'host_ip': pod.status.host_ip if pod.status and pod.status.host_ip else '',
                                'phase': pod.status.phase if pod.status else 'Unknown',
                                'ready': is_ready
                            }
                    
                    # 更新 pod_list 中的信息
                    updated_count = 0
                    for pod_info in pod_list:
                        if pod_info['name'] in pod_dict:
                            # 更新缺失的信息
                            if not pod_info.get('id'):
                                pod_info['id'] = pod_dict[pod_info['name']]['uid']
                                updated_count += 1
                            if not pod_info.get('host_ip') and pod_dict[pod_info['name']]['host_ip']:
                                pod_info['host_ip'] = pod_dict[pod_info['name']]['host_ip']
                                updated_count += 1
                    if updated_count > 0:
                        LOG.info('Final check updated %d pod field(s)', updated_count)
                    
                    # 检查所有 Pod 是否都已就绪
                    pods_not_ready = []
                    error_details = []
                    
                    for pod_info in pod_list:
                        pod_name = pod_info['name']
                        if pod_name not in pod_dict:
                            pods_not_ready.append(pod_name)
                            error_details.append(f'{pod_name}: Pod not found')
                        elif not pod_dict[pod_name]['ready']:
                            pods_not_ready.append(pod_name)
                            phase = pod_dict[pod_name]['phase']
                            error_details.append(f'{pod_name}: phase={phase}, ready=False')
                    
                    # 如果有 Pod 未就绪，获取详细错误信息并抛出异常
                    if pods_not_ready:
                        LOG.error('❌ %d/%d pods are not ready after %d seconds', 
                                 len(pods_not_ready), len(pod_list), max_wait_time)
                        
                        # 获取更详细的失败信息
                        for pod in pods.items:
                            if pod.metadata.name in pods_not_ready:
                                pod_name = pod.metadata.name
                                phase = pod.status.phase if pod.status else 'Unknown'
                                LOG.error('Pod %s - Phase: %s', pod_name, phase)
                                
                                # 记录容器状态
                                if pod.status and pod.status.container_statuses:
                                    for container_status in pod.status.container_statuses:
                                        restart_count = container_status.restart_count or 0
                                        
                                        if container_status.state:
                                            if container_status.state.waiting:
                                                reason = container_status.state.waiting.reason or 'Unknown'
                                                message = container_status.state.waiting.message or ''
                                                LOG.error('  Container %s waiting: %s (restarts: %d) - %s',
                                                        container_status.name, reason, restart_count, message)
                                                
                                                # 在错误详情中包含重启次数（如果有的话）
                                                if restart_count > 0:
                                                    error_details.append(f'{pod_name}/{container_status.name}: {reason} (restarted {restart_count} times)')
                                                else:
                                                    error_details.append(f'{pod_name}/{container_status.name}: {reason}')
                                            elif container_status.state.terminated:
                                                reason = container_status.state.terminated.reason or 'Unknown'
                                                exit_code = container_status.state.terminated.exit_code or 0
                                                LOG.error('  Container %s terminated: %s (exit code %d, restarts: %d)',
                                                        container_status.name, reason, exit_code, restart_count)
                                                error_details.append(f'{pod_name}/{container_status.name}: terminated (exit {exit_code}, restarted {restart_count} times)')
                                            elif container_status.state.running:
                                                # 容器在运行但 Pod 不 ready（可能健康检查失败）
                                                if restart_count > 0:
                                                    LOG.error('  Container %s running but not ready (restarts: %d)',
                                                            container_status.name, restart_count)
                                                    error_details.append(f'{pod_name}/{container_status.name}: running but not ready (restarted {restart_count} times)')
                                        else:
                                            # 没有状态信息，但可能有重启次数
                                            if restart_count > 0:
                                                LOG.error('  Container %s - restarts: %d', container_status.name, restart_count)
                                                error_details.append(f'{pod_name}/{container_status.name}: restarted {restart_count} times')
                        
                        error_msg = '; '.join(error_details[:5])  # 只显示前5个错误，避免信息过长
                        raise exceptions.PluginError(
                            message=_('StatefulSet created but %(count)d/%(total)d pods failed to become ready within %(timeout)ds. Details: %(details)s') % {
                                'count': len(pods_not_ready),
                                'total': len(pod_list),
                                'timeout': max_wait_time,
                                'details': error_msg
                            }
                        )
                    
                    LOG.info('✅ All %d pods are ready', len(pod_list))
                    
            except exceptions.PluginError:
                # 重新抛出业务异常
                raise
            except Exception as e:
                LOG.error('Final pod status check failed: %s', str(e))
                raise exceptions.PluginError(
                    message=_('Failed to verify pod status: %(error)s') % {'error': str(e)}
                )
            
            # 同步 Pod 信息到 CMDB（只同步有 ID 的 Pod）
            self._sync_pods_to_cmdb(k8s_client, data['namespace'], pod_list, resource_id)
        
        # 将 Pod 列表转换为字符串格式（用分号拼接），方便页面显示
        pods_str = ';'.join([pod['name'] for pod in pod_list]) if pod_list else ''
        
        # 标记预期创建的 Pod（告知 watcher 这些 Pod 是主动创建的，不需要通知 WeCube）
        # 这样可以避免 watcher 在收到 POD.ADDED 事件时重复触发编排
        # 只有 Pod 漂移/崩溃重启等意外情况，watcher 才会通知 WeCube
        try:
            from wecubek8s.server import watcher
            pod_names = [pod['name'] for pod in pod_list]
            watcher.mark_expected_pods(
                cluster_id=cluster_info['id'],
                namespace=data['namespace'],
                pod_names=pod_names,
                source='statefulset_apply'
            )
        except Exception as e:
            LOG.warning('Failed to mark expected pods in watcher (watcher may still notify for these pods): %s', str(e))
        
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

    def sync_pods_to_cmdb(self, data):
        """
        独立的 CMDB 同步接口，用于补偿同步
        
        参数:
            data: {
                'cluster': 集群名称,
                'namespace': 命名空间,
                'name': StatefulSet 名称,
                'correlation_id': instanceId（用于关联 CMDB）
            }
        """
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 namespace 有值
        if not data.get('namespace') or data['namespace'].strip() == '':
            data['namespace'] = 'default'
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        # StatefulSet 的名称使用 escape_service_name（与创建时保持一致）
        # 【关键】限制为 50 字符，避免 Kubernetes 添加后缀后超过 63 字符限制
        # 【修复】自动移除 name 中可能包含的端口号后缀，避免因端口变化导致查询失败
        normalized_name = api_utils.normalize_statefulset_name(data['name'])
        resource_name = api_utils.escape_service_name(normalized_name, max_length=50)
        correlation_id = data['correlation_id']
        
        # 查询 Pod 列表，使用 resource_name 作为标签值（与创建时保持一致）
        label_selector = f"{const.Tag.POD_AUTO_TAG}={resource_name}"
        
        pod_list = []
        try:
            pods = k8s_client.list_pod(data['namespace'], label_selector=label_selector)
            if pods and pods.items:
                for pod in pods.items:
                    pod_list.append({
                        'name': pod.metadata.name,
                        'id': pod.metadata.uid,
                        'host_ip': pod.status.host_ip if pod.status and pod.status.host_ip else ''  # Pod 所在 Node 的 IP
                    })
                LOG.info('Found %d pods for StatefulSet %s in namespace %s', 
                        len(pod_list), resource_name, data['namespace'])
            else:
                LOG.warning('No pods found for StatefulSet %s in namespace %s', 
                           resource_name, data['namespace'])
                return {
                    'result': 'success',
                    'message': f'No pods found for StatefulSet {resource_name}',
                    'synced_count': 0
                }
        except Exception as e:
            LOG.error('Failed to query pods for StatefulSet %s: %s', resource_name, str(e))
            raise exceptions.PluginError(message=f'Failed to query pods: {str(e)}')
        
        # 同步到 CMDB
        if correlation_id and pod_list:
            try:
                self._sync_pods_to_cmdb(k8s_client, data['namespace'], pod_list, correlation_id)
                synced_count = len([p for p in pod_list if p.get('id')])
                LOG.info('Successfully synced %d pods to CMDB for instanceId: %s', 
                        synced_count, correlation_id)
                return {
                    'result': 'success',
                    'message': f'Synced {synced_count} pods to CMDB',
                    'synced_count': synced_count,
                    'correlation_id': correlation_id
                }
            except Exception as e:
                LOG.error('Failed to sync pods to CMDB: %s', str(e))
                raise exceptions.PluginError(message=f'Failed to sync pods to CMDB: {str(e)}')
        else:
            return {
                'result': 'success',
                'message': 'No correlation_id or pods to sync',
                'synced_count': 0
            }
    
    def remove(self, data):
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('api_server for cluster %s missing protocol, auto-adding https:// prefix: %s', 
                       cluster_info['name'], api_server)
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        
        # 确保 namespace 有默认值
        namespace = data.get('namespace', 'default')
        
        # 使用与 apply 时一致的名称转换方式（escape_service_name）
        # 【关键】限制为 50 字符，避免 Kubernetes 添加后缀后超过 63 字符限制
        # 【修复】自动移除 name 中可能包含的端口号后缀，确保能正确删除资源
        normalized_name = api_utils.normalize_statefulset_name(data['name'])
        resource_name = api_utils.escape_service_name(normalized_name, max_length=50)
        
        # 获取 correlation_id
        correlation_id = data.get('correlation_id', '')
        
        # 收集要返回的信息
        result = {
            'id': '',
            'name': resource_name,
            'namespace': namespace,
            'correlation_id': correlation_id,
            'deleted_resources': [],
            'pods': ''
        }
        
        # 在删除前，查询 Pod 列表
        label_selector = f"{const.Tag.POD_AUTO_TAG}={resource_name}"
        pod_list = []
        try:
            pods = k8s_client.list_pod(namespace, label_selector=label_selector)
            if pods and pods.items:
                for pod in pods.items:
                    pod_list.append(pod.metadata.name)
                LOG.info('Found %d pods for StatefulSet %s in namespace %s', 
                        len(pod_list), resource_name, namespace)
        except Exception as e:
            LOG.warning('Failed to query pods for StatefulSet %s: %s', resource_name, str(e))
        
        result['pods'] = ';'.join(pod_list) if pod_list else ''
        
        # 删除 StatefulSet（Pod 会被 Kubernetes 自动删除，因为有 OwnerReference）
        exists_resource = k8s_client.get_statefulset(resource_name, namespace)
        if exists_resource is not None:
            result['id'] = exists_resource.metadata.uid
            LOG.info('Deleting StatefulSet: %s (uid=%s) in namespace: %s', 
                    resource_name, result['id'], namespace)
            k8s_client.delete_statefulset(resource_name, namespace)
            result['deleted_resources'].append(f"StatefulSet/{resource_name}")
        else:
            LOG.warning('StatefulSet %s not found in namespace: %s', resource_name, namespace)
        
        # 删除关联的 Headless Service（如果存在）
        # 【修复】无论用户是否指定 serviceName，都要规范化（移除端口号后缀）
        raw_name = data.get('serviceName', data['name'])
        base_service_name = api_utils.normalize_statefulset_name(raw_name)
        service_name = api_utils.escape_service_name(base_service_name)
        exists_service = k8s_client.get_service(service_name, namespace)
        if exists_service is not None:
            LOG.info('Deleting Headless Service: %s in namespace: %s', service_name, namespace)
            k8s_client.delete_service(service_name, namespace)
            result['deleted_resources'].append(f"Service/{service_name}")
        else:
            LOG.debug('Headless Service %s not found in namespace: %s', service_name, namespace)
        
        # 删除关联的负载均衡 Service（带 -lb 后缀，如果存在）
        # 【修复】使用与 Headless Service 相同的 base_service_name
        lb_service_name = api_utils.escape_service_name(base_service_name + '-lb')
        exists_lb_service = k8s_client.get_service(lb_service_name, namespace)
        if exists_lb_service is not None:
            LOG.info('Deleting Load Balancer Service: %s in namespace: %s', lb_service_name, namespace)
            k8s_client.delete_service(lb_service_name, namespace)
            result['deleted_resources'].append(f"Service/{lb_service_name}")
        else:
            LOG.debug('Load Balancer Service %s not found in namespace: %s', lb_service_name, namespace)
        
        # Pod 会被 Kubernetes 自动删除（通过 OwnerReference）
        LOG.info('Pods managed by StatefulSet %s will be automatically deleted by Kubernetes', resource_name)
        
        # 将已删除资源列表转换为字符串
        result['deleted_resources'] = ';'.join(result['deleted_resources']) if result['deleted_resources'] else ''
        
        # 记录删除结果到日志
        LOG.info('StatefulSet destroy result: id=%s, name=%s, namespace=%s, correlation_id=%s, deleted_resources=%s, pods=%s',
                result['id'], result['name'], result['namespace'], result['correlation_id'],
                result['deleted_resources'], result['pods'])
        
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return result


class DaemonSet:
    def to_resource(self, k8s_client, data, cluster_info):
        """将输入数据转换为 K8s DaemonSet 资源定义"""
        LOG.info('[DaemonSet-API] to_resource started for %s', data.get('name'))
        
        resource_id = data['correlation_id']
        resource_name = api_utils.escape_name(data['name'])
        resource_namespace = data['namespace']
        LOG.info('[DaemonSet-API] Resource info: id=%s, name=%s, namespace=%s', 
                 resource_id, resource_name, resource_namespace)
        
        resource_tags = api_utils.convert_tag(data.get('tags', []))
        resource_tags[const.Tag.DAEMONSET_ID_TAG] = resource_id
        LOG.debug('[DaemonSet-API] Resource tags: %s', resource_tags)
        
        pod_spec_tags = api_utils.convert_tag(data.get('pod_tags', []))
        pod_spec_tags[const.Tag.POD_AUTO_TAG] = resource_name
        
        # 添加 correlation_id 作为 Pod 标签
        if data.get('correlation_id'):
            pod_spec_tags['correlation_id'] = api_utils.escape_label_value(data['correlation_id'])
        
        LOG.debug('[DaemonSet-API] Pod spec tags: %s', pod_spec_tags)
        
        pod_spec_envs = api_utils.convert_env(data.get('envs', []))
        LOG.info('[DaemonSet-API] Converted %d environment variables', len(pod_spec_envs))
        
        # 如果提供了 image_port，自动注入 PORT 环境变量
        if data.get('image_port'):
            image_port_str = data.get('image_port', '').strip()
            # 解析端口号（支持 "9200/tcp" 或 "9200" 格式）
            port_number = image_port_str.split('/')[0].strip()
            if port_number.isdigit():
                # 检查是否已经存在 PORT 环境变量
                has_port_env = any(env.get('name') == 'PORT' for env in pod_spec_envs)
                if not has_port_env:
                    pod_spec_envs.append({
                        'name': 'PORT',
                        'value': port_number
                    })
                    LOG.info('[DaemonSet-API] Auto-injected PORT=%s from image_port parameter', port_number)
                else:
                    LOG.debug('[DaemonSet-API] PORT environment variable already exists, skipping auto-injection')
            else:
                LOG.warning('[DaemonSet-API] Invalid image_port format: %s, expected format like "9200/tcp"', image_port_str)
        
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
            },
            {
                'name': 'NODE_NAME',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'spec.nodeName'
                    }
                }
            }
        ])
        LOG.debug('[DaemonSet-API] Added Downward API env vars, total env vars: %d', len(pod_spec_envs))
        
        pod_spec_src_vols, pod_spec_mnt_vols = api_utils.convert_volume(data.get('volumes', []))
        LOG.info('[DaemonSet-API] Converted volumes: %d source volumes, %d mount volumes', 
                 len(pod_spec_src_vols), len(pod_spec_mnt_vols))
        
        pod_spec_limit = api_utils.convert_resource_limit(data.get('cpu', None), data.get('memory', None))
        LOG.info('[DaemonSet-API] Resource limits: %s', pod_spec_limit)
        
        # 从数据库的 cluster_info 中读取私有仓库地址
        private_registry = cluster_info.get('private_registry', '')
        LOG.info('[DaemonSet-API] Private registry: %s', private_registry or '(none)')
        
        # 构建完整的镜像地址
        image_name = data['image_name'].strip()
        if private_registry:
            full_image_name = f"{private_registry}/{image_name}"
            LOG.info('[DaemonSet-API] Using private registry, full image: %s', full_image_name)
        else:
            full_image_name = image_name
            LOG.info('[DaemonSet-API] Using public image: %s', full_image_name)
        
        # 构建 images 数组格式
        images_data = [{
            'name': full_image_name,
            'ports': data.get('image_port', '')
        }]
        LOG.debug('[DaemonSet-API] Images data: %s', images_data)
        
        # 获取 deploy_script（可选）
        deploy_script = data.get('deploy_script')
        if deploy_script:
            LOG.info('[DaemonSet-API] Using deploy_script: %s', deploy_script.replace('\n', '\\n'))
        
        containers = api_utils.convert_container(images_data, pod_spec_envs, pod_spec_mnt_vols, pod_spec_limit, deploy_script)
        LOG.info('[DaemonSet-API] Converted %d containers', len(containers))
        
        # 处理镜像拉取凭据
        image_pull_username = cluster_info.get('image_pull_username', '')
        image_pull_password = cluster_info.get('image_pull_password', '')
        LOG.info('[DaemonSet-API] Image pull credentials: username=%s, password=%s', 
                 image_pull_username or '(none)', '***' if image_pull_password else '(none)')
        
        registry_secrets = []
        if image_pull_username and image_pull_password:
            LOG.info('[DaemonSet-API] Converting registry secrets...')
            registry_secrets = api_utils.convert_registry_secret(k8s_client, images_data, resource_namespace,
                                                                 image_pull_username,
                                                                 image_pull_password)
            LOG.info('[DaemonSet-API] Registry secrets created: %s', registry_secrets)
        else:
            LOG.info('[DaemonSet-API] No registry credentials provided, skipping secret creation')
        
        # 构建 Pod 模板
        LOG.info('[DaemonSet-API] Building Pod template...')
        pod_template = {
            'metadata': {
                'labels': pod_spec_tags
            },
            'spec': {
                'containers': containers,
                'volumes': pod_spec_src_vols,
                'restartPolicy': 'Always'
            }
        }
        
        # 设置镜像拉取凭据
        if registry_secrets:
            pod_template['spec']['imagePullSecrets'] = registry_secrets
            LOG.info('[DaemonSet-API] Added imagePullSecrets to Pod template')
        
        # 处理节点选择器
        if data.get('node_selector'):
            pod_template['spec']['nodeSelector'] = data['node_selector']
            LOG.info('[DaemonSet-API] Added nodeSelector: %s', data['node_selector'])
        else:
            LOG.debug('[DaemonSet-API] No nodeSelector specified')
        
        # 处理容忍度（tolerations）
        if data.get('tolerations'):
            pod_template['spec']['tolerations'] = data['tolerations']
            LOG.info('[DaemonSet-API] Added tolerations: %s', data['tolerations'])
        else:
            LOG.debug('[DaemonSet-API] No tolerations specified')
        
        # 构建 DaemonSet 资源定义
        LOG.info('[DaemonSet-API] Building DaemonSet resource definition...')
        daemonset_body = {
            'apiVersion': 'apps/v1',
            'kind': 'DaemonSet',
            'metadata': {
                'name': resource_name,
                'namespace': resource_namespace,
                'labels': resource_tags
            },
            'spec': {
                'selector': {
                    'matchLabels': {
                        const.Tag.POD_AUTO_TAG: resource_name
                    }
                },
                'template': pod_template,
                'updateStrategy': {
                    'type': 'RollingUpdate',
                    'rollingUpdate': {
                        'maxUnavailable': 1
                    }
                }
            }
        }
        
        LOG.info('[DaemonSet-API] DaemonSet resource definition built successfully')
        LOG.debug('[DaemonSet-API] DaemonSet body: %s', daemonset_body)
        return daemonset_body

    def apply(self, data):
        """创建或更新 DaemonSet"""
        LOG.info('=' * 80)
        LOG.info('[DaemonSet-API] ========== DaemonSet Apply Started ==========')
        LOG.info('[DaemonSet-API] Request data: name=%s, cluster=%s, namespace=%s', 
                 data.get('name'), data.get('cluster'), data.get('namespace'))
        LOG.debug('[DaemonSet-API] Full request data: %s', data)
        
        resource_id = data['correlation_id']
        LOG.info('[DaemonSet-API] Resource ID (correlation_id): %s', resource_id)
        
        LOG.info('[DaemonSet-API] Step 1/7: Querying cluster info from database...')
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            LOG.error('[DaemonSet-API] Cluster not found: %s', data['cluster'])
            raise exceptions.ValidationError(
                attribute='cluster',
                message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']})
            )
        cluster_info = cluster_info[0]
        LOG.info('[DaemonSet-API] ✓ Cluster found: %s (api_server=%s)', 
                 cluster_info['name'], cluster_info.get('api_server'))
        
        # 确保 namespace 有值
        LOG.info('[DaemonSet-API] Step 2/7: Validating namespace...')
        if not data.get('namespace') or data['namespace'].strip() == '':
            data['namespace'] = 'default'
            LOG.warning('[DaemonSet-API] namespace not provided for DaemonSet %s, using default', data.get('name'))
        LOG.info('[DaemonSet-API] ✓ Namespace: %s', data['namespace'])
        
        # 确保 api_server 有正确的协议前缀
        LOG.info('[DaemonSet-API] Step 3/7: Preparing API server URL...')
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('[DaemonSet-API] api_server missing protocol, adding https:// prefix: %s', api_server)
        LOG.info('[DaemonSet-API] ✓ API Server URL: %s', api_server)
        
        LOG.info('[DaemonSet-API] Step 4/7: Creating K8s client...')
        try:
            k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
            k8s_client = k8s.Client(k8s_auth)
            LOG.info('[DaemonSet-API] ✓ K8s client created successfully')
        except Exception as e:
            LOG.error('[DaemonSet-API] ✗ Failed to create K8s client: %s', str(e), exc_info=True)
            raise
        
        LOG.info('[DaemonSet-API] Step 5/7: Ensuring namespace exists...')
        try:
            k8s_client.ensure_namespace(data['namespace'])
            LOG.info('[DaemonSet-API] ✓ Namespace ensured: %s', data['namespace'])
        except Exception as e:
            LOG.error('[DaemonSet-API] ✗ Failed to ensure namespace: %s', str(e), exc_info=True)
            raise
        
        resource_name = api_utils.escape_name(data['name'])
        LOG.info('[DaemonSet-API] Escaped resource name: %s -> %s', data['name'], resource_name)
        
        LOG.info('[DaemonSet-API] Step 6/7: Checking if DaemonSet exists...')
        try:
            exists_resource = k8s_client.get_daemonset(resource_name, data['namespace'])
            if exists_resource is None:
                LOG.info('[DaemonSet-API] DaemonSet does not exist, will create new one')
            else:
                LOG.info('[DaemonSet-API] DaemonSet exists, will update it')
        except Exception as e:
            LOG.error('[DaemonSet-API] ✗ Failed to check DaemonSet existence: %s', str(e), exc_info=True)
            raise
        
        LOG.info('[DaemonSet-API] Step 7/7: Creating/Updating DaemonSet...')
        LOG.info('[DaemonSet-API] Converting data to K8s resource...')
        daemonset_body = self.to_resource(k8s_client, data, cluster_info)
        
        if exists_resource is None:
            try:
                LOG.info('[DaemonSet-API] Calling k8s_client.create_daemonset...')
                exists_resource = k8s_client.create_daemonset(
                    data['namespace'],
                    daemonset_body
                )
                LOG.info('[DaemonSet-API] ✓ Created DaemonSet %s/%s', data['namespace'], resource_name)
            except Exception as e:
                LOG.error('[DaemonSet-API] ✗ Failed to create DaemonSet: %s', str(e), exc_info=True)
                raise
        else:
            try:
                LOG.info('[DaemonSet-API] Using replace instead of patch to avoid field merge issues')
                
                # 使用 replace 而不是 patch,完全替换资源定义
                # 这样可以避免 patch 合并时保留旧字段的问题
                # 注意: replace 需要保留 resourceVersion
                daemonset_body['metadata']['resourceVersion'] = exists_resource.metadata.resource_version
                LOG.info('[DaemonSet-API] Calling k8s_client.replace_daemonset...')
                exists_resource = k8s_client.replace_daemonset(
                    resource_name,
                    data['namespace'],
                    daemonset_body
                )
                LOG.info('[DaemonSet-API] ✓ Updated DaemonSet %s/%s', data['namespace'], resource_name)
            except Exception as e:
                LOG.error('[DaemonSet-API] ✗ Failed to update DaemonSet: %s', str(e), exc_info=True)
                raise
        
        # 等待 DaemonSet 状态更新
        LOG.info('[DaemonSet-API] Waiting for DaemonSet status to update...')
        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                # 等待一段时间让 Kubernetes 更新状态
                if attempt > 0:
                    time.sleep(retry_delay)
                    LOG.info('[DaemonSet-API] Retry %d/%d: Fetching updated DaemonSet status...', attempt + 1, max_retries)
                else:
                    # 第一次也等待一下，让 Kubernetes 有时间初始化
                    time.sleep(1)
                    LOG.info('[DaemonSet-API] Fetching DaemonSet status...')
                
                # 重新获取 DaemonSet 状态
                exists_resource = k8s_client.get_daemonset(resource_name, data['namespace'])
                
                if exists_resource and exists_resource.status:
                    desired = exists_resource.status.desired_number_scheduled or 0
                    current = exists_resource.status.current_number_scheduled or 0
                    ready = exists_resource.status.number_ready or 0
                    available = exists_resource.status.number_available or 0
                    
                    LOG.info('[DaemonSet-API] Current status: desired=%d, current=%d, ready=%d, available=%d',
                            desired, current, ready, available)
                    
                    # 如果 desired > 0，说明状态已经更新，可以返回
                    if desired > 0:
                        LOG.info('[DaemonSet-API] ✓ DaemonSet status updated successfully')
                        break
                    
                    # 如果是最后一次重试，即使 desired=0 也返回
                    if attempt == max_retries - 1:
                        LOG.warning('[DaemonSet-API] Status still shows 0 after %d retries, returning current status', max_retries)
                else:
                    LOG.warning('[DaemonSet-API] Failed to fetch DaemonSet status on attempt %d', attempt + 1)
                    
            except Exception as e:
                LOG.error('[DaemonSet-API] Error fetching DaemonSet status: %s', str(e))
                if attempt == max_retries - 1:
                    LOG.warning('[DaemonSet-API] Using initial status after retries failed')
        
        # 返回结果
        LOG.info('[DaemonSet-API] Preparing result...')
        try:
            result = {
                'correlation_id': resource_id,
                'name': data['name'],
                'namespace': data['namespace'],
                'desired_number_scheduled': exists_resource.status.desired_number_scheduled or 0,
                'current_number_scheduled': exists_resource.status.current_number_scheduled or 0,
                'number_ready': exists_resource.status.number_ready or 0,
                'number_available': exists_resource.status.number_available or 0
            }
            
            LOG.info('[DaemonSet-API] ========== DaemonSet Apply Completed Successfully ==========')
            LOG.info('[DaemonSet-API] Result: %s', result)
            LOG.info('[DaemonSet-API] Status: desired=%s, current=%s, ready=%s, available=%s',
                     result['desired_number_scheduled'],
                     result['current_number_scheduled'],
                     result['number_ready'],
                     result['number_available'])
            LOG.info('=' * 80)
            return result
        except Exception as e:
            LOG.error('[DaemonSet-API] ✗ Failed to prepare result: %s', str(e), exc_info=True)
            raise

    def remove(self, data):
        """删除 DaemonSet"""
        LOG.info('=' * 80)
        LOG.info('[DaemonSet-API] ========== DaemonSet Remove Started ==========')
        LOG.info('[DaemonSet-API] Request: name=%s, cluster=%s, namespace=%s', 
                 data.get('name'), data.get('cluster'), data.get('namespace'))
        
        LOG.info('[DaemonSet-API] Step 1/4: Querying cluster info...')
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            LOG.error('[DaemonSet-API] Cluster not found: %s', data['cluster'])
            raise exceptions.ValidationError(
                attribute='cluster',
                message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']})
            )
        cluster_info = cluster_info[0]
        LOG.info('[DaemonSet-API] ✓ Cluster found: %s', cluster_info['name'])
        
        if not data.get('namespace'):
            data['namespace'] = 'default'
            LOG.info('[DaemonSet-API] Using default namespace')
        
        LOG.info('[DaemonSet-API] Step 2/4: Preparing API server URL...')
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
        LOG.info('[DaemonSet-API] ✓ API Server: %s', api_server)
        
        LOG.info('[DaemonSet-API] Step 3/4: Creating K8s client...')
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        LOG.info('[DaemonSet-API] ✓ K8s client created')
        
        resource_name = api_utils.escape_name(data['name'])
        LOG.info('[DaemonSet-API] Escaped resource name: %s -> %s', data['name'], resource_name)
        
        LOG.info('[DaemonSet-API] Step 4/4: Checking and deleting DaemonSet...')
        exists_resource = k8s_client.get_daemonset(resource_name, data['namespace'])
        
        if exists_resource:
            LOG.info('[DaemonSet-API] DaemonSet exists, deleting...')
            k8s_client.delete_daemonset(resource_name, data['namespace'])
            LOG.info('[DaemonSet-API] ✓ Deleted DaemonSet %s/%s', data['namespace'], resource_name)
            
            result = {
                'name': data['name'],
                'namespace': data['namespace'],
                'status': 'deleted'
            }
        else:
            LOG.warning('[DaemonSet-API] DaemonSet %s/%s not found, nothing to delete', 
                       data['namespace'], resource_name)
            result = {
                'name': data['name'],
                'namespace': data['namespace'],
                'status': 'not_found'
            }
        
        LOG.info('[DaemonSet-API] ========== DaemonSet Remove Completed ==========')
        LOG.info('[DaemonSet-API] Result: %s', result)
        LOG.info('=' * 80)
        return result


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
            template['spec']['clusterIP'] = 'None'  # Headless Service (必须是字符串 "None")
        elif resource_cluster_ip:
            # not headless & user specific cluster ip, use it
            template['spec']['clusterIP'] = resource_cluster_ip
        return template

    def apply(self, data):
        resource_id = data['correlation_id']
        cluster_info = db_resource.Cluster().list({'name': data['cluster']})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
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
            # 使用 replace 而不是 patch，需要保留 resourceVersion
            resource_template = self.to_resource(k8s_client, data)
            resource_template['metadata']['resourceVersion'] = exists_resource.metadata.resource_version
            exists_resource = k8s_client.update_service(resource_name, data['namespace'], resource_template)
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
                                             message=_('name of cluster(%(name)s) not found' % {'name': data['cluster']}))
        cluster_info = cluster_info[0]
        
        # 确保 api_server 有正确的协议前缀
        api_server = cluster_info['api_server']
        if not api_server.startswith('https://') and not api_server.startswith('http://'):
            api_server = 'https://' + api_server
            LOG.warning('api_server for cluster %s missing protocol, auto-adding https:// prefix: %s', 
                       cluster_info['name'], api_server)
        
        k8s_auth = k8s.AuthToken(api_server, cluster_info['token'])
        k8s_client = k8s.Client(k8s_auth)
        resource_name = api_utils.escape_name(data['name'])
        
        # 获取 correlation_id
        correlation_id = data.get('correlation_id', '')
        
        # 收集要返回的信息
        result = {
            'id': '',
            'name': resource_name,
            'namespace': data.get('namespace', 'default'),
            'correlation_id': correlation_id,
            'deleted_resources': []
        }
        
        exists_resource = k8s_client.get_service(resource_name, data['namespace'])
        if exists_resource is not None:
            result['id'] = exists_resource.metadata.uid
            # 收集 Service 的详细信息
            cluster_ip = exists_resource.spec.cluster_ip if exists_resource.spec.cluster_ip else None
            ports = []
            if exists_resource.spec.ports:
                for port in exists_resource.spec.ports:
                    port_str = f"{port.port}"
                    if port.node_port:
                        port_str += f":{port.node_port}"
                    ports.append(port_str)
            
            result['clusterIP'] = cluster_ip
            result['ports'] = ';'.join(ports) if ports else ''
            
            LOG.info('Deleting Service: %s (uid=%s, clusterIP=%s) in namespace: %s', 
                    resource_name, result['id'], cluster_ip, data['namespace'])
            k8s_client.delete_service(resource_name, data['namespace'])
            result['deleted_resources'].append(f"Service/{resource_name}")
        else:
            LOG.warning('Service %s not found in namespace: %s', resource_name, data['namespace'])
        
        # 将已删除资源列表转换为字符串
        result['deleted_resources'] = ';'.join(result['deleted_resources']) if result['deleted_resources'] else ''
        
        # 记录删除结果到日志
        LOG.info('Service destroy result: id=%s, name=%s, namespace=%s, correlation_id=%s, deleted_resources=%s',
                result['id'], result['name'], result['namespace'], result['correlation_id'], result['deleted_resources'])
        
        # TODO: k8s为异步接口，是否需要等待真正执行完毕
        return result


class Node:
    def label(self, data):
        """查询集群中的所有 node 并更新标签"""
        cluster_name = data['cluster']
        
        # 获取集群信息
        cluster_info = db_resource.Cluster().list({'name': cluster_name})
        if not cluster_info:
            raise exceptions.ValidationError(attribute='cluster',
                                             message=_('name of cluster(%(name)s) not found' % {'name': cluster_name}))
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
                raise exceptions.K8sCallError(cluster=cluster_name, message='Failed to update node %s: %s' % (node_name, str(e)))
        
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
                                             message=_('name of cluster(%(name)s) not found' % {'name': cluster_name}))
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
                                                 message=_('node(%(name)s) not found in cluster' % {'name': node_name}))
            
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
                raise exceptions.K8sCallError(cluster=cluster_name, message='Failed to update node %s: %s' % (node_name, str(e)))
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
                message=_('local_cluster and service_name are required'))

        # 获取集群信息
        all_clusters = self.db_cluster.list()
        cluster_map = {c['name']: c for c in all_clusters}

        if local_cluster_name not in cluster_map:
            raise exceptions.ValidationError(
                attribute='local_cluster',
                message=_('Local cluster %(name)s not found' % {'name': local_cluster_name}))

        local_cluster = cluster_map[local_cluster_name]
        k8s_auth = k8s.AuthToken(local_cluster['api_server'], local_cluster['token'])
        local_client = k8s.Client(k8s_auth)
        local_client.ensure_namespace(local_namespace)

        # 如果使用Endpoint方式，需要获取远程集群的服务IP
        if service_type == 'Endpoint':
            if not remote_cluster_name:
                raise exceptions.ValidationError(
                    attribute='remote_cluster',
                    message=_('remote_cluster is required when service_type is Endpoint'))

            if remote_cluster_name not in cluster_map:
                raise exceptions.ValidationError(
                    attribute='remote_cluster',
                    message=_('Remote cluster %(name)s not found' % {'name': remote_cluster_name}))

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
                    message=_('Remote service %(name)s/%(ns)s not found' %
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
                        message=_('external_name or remote_cluster is required for ExternalName type'))
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
            # 使用 replace 而不是 patch，需要保留 resourceVersion
            service_body['metadata']['resourceVersion'] = existing_service.metadata.resource_version
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
                message=_('cluster and policy_name are required'))

        all_clusters = self.db_cluster.list()
        cluster_map = {c['name']: c for c in all_clusters}

        if cluster_name not in cluster_map:
            raise exceptions.ValidationError(
                attribute='cluster',
                message=_('Cluster %(name)s not found' % {'name': cluster_name}))

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