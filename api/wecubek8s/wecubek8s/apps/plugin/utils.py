# coding=utf-8

from __future__ import absolute_import

import logging
import re

from talos.core import config
from talos.core.i18n import _
from wecubek8s.common import exceptions

CONF = config.CONF
LOG = logging.getLogger(__name__)


def escape_name(name):
    '''
    lowercase RFC 1123 name must consist of lower case alphanumeric characters, 
    '-' or '.', and must start and end with an alphanumeric character 
    (e.g. 'example.com', regex used for validation is '[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*')
    '''
    rule = r'[^.a-z0-9]'
    return re.sub(rule, '-', name.lower())


def escape_service_name(name, max_length=63):
    '''
    DNS-1035 label (for Service names) must consist of lower case alphanumeric characters or '-',
    start with an alphabetic character, and end with an alphanumeric character.
    More strict than DNS-1123: no dots allowed, must start with a letter.
    (e.g. 'my-service', regex used for validation is '[a-z]([-a-z0-9]*[a-z0-9])?')
    
    Args:
        name: 原始名称
        max_length: 最大长度限制（默认 63）。对于 StatefulSet，建议使用更小的值（如 50）
                   以预留空间给 Kubernetes 自动添加的后缀（如 controller-revision-hash）
    '''
    # 1. 转换为小写并替换所有非字母数字字符为 '-'
    result = re.sub(r'[^a-z0-9]', '-', name.lower())
    
    # 2. 确保以字母开头（如果不是，添加 's-' 前缀）
    if not result or not result[0].isalpha():
        result = 's-' + result
    
    # 3. 确保以字母或数字结尾（删除尾部的 '-'）
    result = result.rstrip('-')
    
    # 4. 合并连续的 '-' 为单个 '-'
    result = re.sub(r'-+', '-', result)
    
    # 5. 确保长度限制
    if len(result) > max_length:
        result = result[:max_length].rstrip('-')
    
    return result


def escape_label_value(value):
    '''
    Kubernetes label value must be an empty string or consist of alphanumeric characters, 
    '-', '_' or '.', and must start and end with an alphanumeric character.
    (e.g. 'MyValue', 'my_value', '12345', regex: '(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?')
    '''
    if not value:
        return ''
    
    # 1. 替换所有不允许的字符为 '-'
    result = re.sub(r'[^A-Za-z0-9._-]', '-', value)
    
    # 2. 确保以字母或数字开头（删除开头的非字母数字字符）
    result = re.sub(r'^[^A-Za-z0-9]+', '', result)
    
    # 3. 确保以字母或数字结尾（删除尾部的非字母数字字符）
    result = re.sub(r'[^A-Za-z0-9]+$', '', result)
    
    # 4. 如果结果为空，返回默认值
    if not result:
        return 'default'
    
    # 5. 确保长度限制（标签值最大 63 字符）
    if len(result) > 63:
        result = result[:63].rstrip('._-')
    
    return result


def convert_tag(items):
    labels = {}
    # 处理 None 或空值的情况（StringToList 转换器可能返回 None）
    if items is None:
        return labels
    for tag in items:
        labels[tag['name']] = tag['value']
    return labels


def convert_pod_ports(item):
    # convert pod ports
    # eg. 12, 23:32, 45::UDP, 678:876:TCP
    rets = []
    parts = re.split(r',|;', item)
    for part in parts:
        if part.strip():
            part = part.strip()
            map_parts = part.split(':', 2)
            ret = {'containerPort': int(map_parts[0]), 'protocol': 'TCP'}
            if len(map_parts) >= 1:
                rets.append(ret)
            if len(map_parts) >= 2:
                if map_parts[1]:
                    ret['hostPort'] = int(map_parts[1])
            if len(map_parts) >= 3:
                ret['protocol'] = map_parts[2]
    return rets


def convert_service_port(items):
    # convert service port
    rets = []
    # 处理 None 或空值的情况
    if items is None:
        return rets
    fields = ['name', 'protocol', 'port', 'targetPort', 'nodePort']
    for item in items:
        ret = {}
        for field in fields:
            if item.get(field):
                ret[field] = item[field]
                if field in ('port', 'targetPort', 'nodePort'):
                    ret[field] = int(ret[field])
        rets.append(ret)
    return rets


def convert_env(items):
    # convert envs
    rets = []
    # 处理 None 或空值的情况
    if items is None:
        return rets
    for idx, item in enumerate(items):
        if 'valueRef' not in item:
            item['valueRef'] = None
        if 'valueFrom' not in item or not item['valueFrom']:
            item['valueFrom'] = 'value'
        if item['valueRef'] is None and item['valueFrom'] != 'value':
            raise exceptions.ValidationError(attribute='envs[%s]' % (idx + 1),
                                             msg=_('valueRef is NULL, while valueFrom is %(value)s') %
                                             {'value': item['valueFrom']})
        if item['valueFrom'] == 'value':
            rets.append({'name': item['name'], 'value': item['value']})
        elif item['valueFrom'] == 'configMap':
            rets.append({
                'name': item['name'],
                'valueFrom': {
                    'configMapKeyRef': {
                        'name': item['valueRef']['name'],
                        'key': item['valueRef']['value']
                    }
                }
            })
        elif item['valueFrom'] == 'secretKey':
            rets.append({
                'name': item['name'],
                'valueFrom': {
                    'secretKeyRef': {
                        'name': item['valueRef']['name'],
                        'key': item['valueRef']['value']
                    }
                }
            })
        elif item['valueFrom'] == 'fieldRef':
            rets.append({'name': item['name'], 'valueFrom': {'fieldRef': {'fieldPath': item['valueRef']['name']}}})
    return rets


def convert_volume(items):
    """
    转换 volume 配置
    支持两种格式：
    1. 完整对象格式：[{'name': 'vol1', 'type': 'emptyDir', 'mountPath': '/data', ...}]
    2. 简单路径格式：['/data/logs', '/app/logs'] 或字符串 '/data/logs,/app/logs'
    """
    # convert volumes
    volumes = []
    mounts = []
    
    # 如果 items 为空，直接返回
    if not items:
        return volumes, mounts
    
    for idx, item in enumerate(items):
        # 判断是字符串路径还是完整对象
        if isinstance(item, str):
            # 简单路径格式：使用 emptyDir 作为默认类型
            mount_path = item.strip()
            if not mount_path:
                continue
            
            # 生成唯一的 volume 名称（基于路径）
            # 将路径转换为合法的 volume 名称（替换 / 为 -，去掉开头的 -）
            volume_name = 'vol-' + mount_path.replace('/', '-').strip('-').replace('_', '-')
            # 如果名称为空，使用索引
            if not volume_name or volume_name == 'vol-':
                volume_name = f'vol-{idx}'
            
            # 创建 emptyDir volume（默认类型）
            volumes.append({
                'name': volume_name,
                'emptyDir': {}
            })
            
            # 创建 mount
            mounts.append({
                'name': volume_name,
                'mountPath': mount_path,
                'readOnly': False
            })
        
        elif isinstance(item, dict):
            # 完整对象格式：保持原有逻辑
            volume_name = item['name']
            volume_type = item['type']
            volume_type_spec = item.get('typeSpec', None) or {}
            volume_mount_path = item['mountPath']
            volume_read_only = item.get('readOnly', None) or False

            volume_type_spec_new = {}
            volumes.append({'name': volume_name, volume_type: volume_type_spec_new})
            if volume_type == 'configMap':
                volume_type_spec_new['name'] = volume_type_spec['name']
            elif volume_type == 'secret':
                volume_type_spec_new['secretName'] = volume_type_spec['name']
            elif volume_type == 'hostPath':
                volume_type_spec_new['path'] = volume_type_spec['path']
                volume_type_spec_new['type'] = volume_type_spec.get('type', None) or ''
            elif volume_type == 'emptyDir':
                volume_type_spec_new['medium'] = volume_type_spec.get('medium', '') or ''
                if 'sizeLimit' in volume_type_spec and volume_type_spec['sizeLimit']:
                    volume_type_spec_new['sizeLimit'] = volume_type_spec['sizeLimit']
            elif volume_type == 'nfs':
                volume_type_spec_new['server'] = volume_type_spec['server']
                volume_type_spec_new['path'] = volume_type_spec['path']
                volume_type_spec_new['readOnly'] = volume_read_only
            elif volume_type == 'persistentVolumeClaim':
                volume_type_spec_new['claimName'] = volume_type_spec['name']
                volume_type_spec_new['readOnly'] = volume_read_only

            mounts.append({'name': volume_name, 'mountPath': volume_mount_path, 'readOnly': volume_read_only})
    
    return volumes, mounts


def convert_resource_limit(cpu, memory):
    """
    转换资源限制配置
    
    Args:
        cpu: CPU 限制，支持格式：'1', '0.5', '500m' 等
        memory: 内存限制，支持格式：'2Gi', '512Mi', '2' (自动添加 Gi 单位)
    
    Returns:
        资源限制字典，包含 limits 和 requests
    """
    ret = {'limits': {}, 'requests': {}}
    
    if cpu:
        ret['limits'].setdefault('cpu', cpu)
        ret['requests'].setdefault('cpu', cpu)
    
    if memory:
        # 修复：如果 memory 是纯数字，自动添加 Gi 单位
        # 避免出现 memory="2" 被当作 2 字节的问题
        memory_str = str(memory).strip()
        
        # 检查是否已经包含单位（Ki, Mi, Gi, Ti, K, M, G, T, m）
        has_unit = False
        for unit in ['Ki', 'Mi', 'Gi', 'Ti', 'K', 'M', 'G', 'T', 'm']:
            if memory_str.endswith(unit):
                has_unit = True
                break
        
        # 如果是纯数字，自动添加 Gi 单位（假设用户输入的是 GB）
        if not has_unit and memory_str.replace('.', '', 1).isdigit():
            memory_str = memory_str + 'Gi'
            LOG.info(f'Auto-added unit to memory limit: {memory} -> {memory_str}')
        
        ret['limits'].setdefault('memory', memory_str)
        ret['requests'].setdefault('memory', memory_str)
    
    return ret


def parse_image_url(image_url):
    '''parse image_url
    eg. 
    ccr.ccs.tencentyun.com:5555/webankpartners/platform-core:v2.9.0
    ccr.ccs.tencentyun.com:5555/platform-core:v2.9.0
    ccr.ccs.tencentyun.com:5555/webankpartners/platform-core
    ccr.ccs.tencentyun.com/webankpartners/platform-core:v2.9.0
    ccr.ccs.tencentyun.com/platform-core:v2.9.0
    ccr.ccs.tencentyun.com/platform-core
    webankpartners/platform-core:v2.9.0
    webankpartners/platform-core
    platform-core:v2.9.0
    platform-core
    minio/mc
    ccr.ccs.tencentyun.com:5555/a.b.c.namespace/d.e.f.name:tag1
    ccr.ccs.tencentyun.com:5555/a.b.c.namespace/d.e.f.name
    ccr.ccs.tencentyun.com/a.b.c.namespace/d.e.f.name:tag1
    ccr.ccs.tencentyun.com/a.b.c.namespace/d.e.f.name
    '''
    url_rule = r'^((?P<server>([a-zA-Z0-9]+(\.[-_a-zA-Z0-9]+)+?))(:(?P<port>\d+))?/)?((?P<namespace>([-_a-zA-Z0-9]+?))/)?(?P<image>([-_a-zA-Z0-9]+?))(:(?P<tag>[-_.a-zA-Z0-9]+))?$'
    # private url like: server/namespace/image[:tag]
    private_url_rule = r'^((?P<server>([a-zA-Z0-9]+(\.[-_a-zA-Z0-9]+)+?))(:(?P<port>\d+))?/)((?P<namespace>([-_.a-zA-Z0-9]+?))/)(?P<image>([-_.a-zA-Z0-9]+?))(:(?P<tag>[-_.a-zA-Z0-9]+))?$'
    ret = re.search(url_rule, image_url)
    if ret:
        server_with_port = None
        if ret['server']:
            if ret['port']:
                server_with_port = '%s:%s' % (ret['server'], ret['port'])
            else:
                server_with_port = ret['server']
        return server_with_port, ret['namespace'], ret['image'], ret['tag']
    else:
        ret = re.search(private_url_rule, image_url)
        if ret:
            server_with_port = None
            if ret['port']:
                server_with_port = '%s:%s' % (ret['server'], ret['port'])
            else:
                server_with_port = ret['server']
            return server_with_port, ret['namespace'], ret['image'], ret['tag']
    return None, None, None, None


def convert_container(images, envs, vols, resource_limit, deploy_script=None):
    """
    转换容器配置
    
    参数:
        images: 镜像列表
        envs: 环境变量列表
        vols: 挂载卷列表
        resource_limit: 资源限制
        deploy_script: 可选的部署脚本，在容器启动时执行
    """
    containers = []
    container_template = {
        'name': '',
        'image': '',
        'imagePullPolicy': 'IfNotPresent',
        'ports': [],
        'env': envs,
        'volumeMounts': vols,
        'resources': resource_limit
    }
    for image_info in images:
        container = container_template.copy()
        registry_server, registry_namespace, image_name, image_tag = parse_image_url(image_info['name'].strip())
        container['name'] = image_name
        container['image'] = image_info['name'].strip()
        container['ports'] = convert_pod_ports(image_info.get('ports', ''))
        
        # 如果提供了部署脚本，修改容器启动命令
        if deploy_script:
            # 使用 bash 执行脚本，脚本最后需要启动原始的容器进程
            # 注意：这里假设脚本已经包含了启动原容器进程的逻辑（如 exec /docker-entrypoint.sh "$@"）
            container['command'] = ['/bin/bash', '-c']
            # 将脚本中的 \\n 替换为真正的换行符
            script_content = deploy_script.replace('\\n', '\n')
            container['args'] = [script_content]
        
        containers.append(container)

    return containers


def convert_registry_secret(k8s_client, images, namespace, username, password):
    """
    为镜像列表创建 registry secret
    参数:
        k8s_client: Kubernetes 客户端
        images: 镜像列表，可以是：
            - 字典列表，每个字典包含 'name' 字段，如 [{'name': 'image1'}, {'name': 'image2'}]
            - 字符串列表，如 ['image1', 'image2']
            - 单个字符串，如 'image1'
        namespace: 命名空间
        username: 用户名
        password: 密码
    返回:
        rets: Secret 引用列表，去重后的结果
    """
    rets = []
    seen_secrets = set()  # 用于去重，避免同一个 registry 创建多个 secret
    
    # 统一处理：将单个字符串或字符串列表转换为统一格式
    if isinstance(images, str):
        images = [images]
    elif not isinstance(images, list):
        images = []
    
    for image_item in images:
        # 处理字典格式 {'name': 'image'} 或字符串格式 'image'
        if isinstance(image_item, dict):
            image_name = image_item.get('name', '').strip()
        else:
            image_name = str(image_item).strip()
        
        if not image_name:
            continue
            
        registry_server, registry_namespace, image_name_parsed, image_tag = parse_image_url(image_name)
        if registry_server:
            name = registry_server + '#' + username
            name = escape_name(name)
            
            # 去重：同一个 registry 和 username 只创建一个 secret
            if name not in seen_secrets:
                k8s_client.ensure_registry_secret(name, namespace, registry_server, username, password)
                rets.append({'name': name})
                seen_secrets.add(name)
    
    return rets


def convert_affinity(strategy, tag_key, tag_value):
    if strategy == 'anti-host-preferred':
        return {
            'podAntiAffinity': {
                'preferredDuringSchedulingIgnoredDuringExecution': [{
                    'weight': 100,
                    'podAffinityTerm': {
                        'labelSelector': {
                            'matchExpressions': [{
                                'key': tag_key,
                                'operator': 'In',
                                'values': [tag_value]
                            }]
                        },
                        'topologyKey': 'kubernetes.io/hostname'
                    }
                }]
            }
        }
    elif strategy == 'anti-host-required':
        return {
            'podAntiAffinity': {
                'requiredDuringSchedulingIgnoredDuringExecution': [{
                    'labelSelector': {
                        'matchExpressions': [{
                            'key': tag_key,
                            'operator': 'In',
                            'values': [tag_value]
                        }]
                    },
                    'topologyKey': 'kubernetes.io/hostname'
                }]
            }
        }
    return {}


def setup_package_init_container(data, containers, volumes, cluster_info=None):
    """
    处理 packageUrl：添加 initContainer 和共享 volume
    参数:
        data: 包含 packageUrl 的字典
        containers: 主容器列表（会被修改，添加 volumeMounts）
        volumes: volumes 列表（会被修改，添加共享 volume）
        cluster_info: 集群信息，包含 private_registry（新增参数）
    返回:
        init_containers: initContainer 列表，如果没有 packageUrl 则返回空列表
    """
    from wecubek8s.common import const  # 导入常量
    
    init_containers = []
    package_url = data.get('packageUrl')
    if package_url:
        # 使用常量定义的镜像名称
        init_container_image = const.Registry.INIT_CONTAINER_IMAGE
        
        # 从 cluster_info 读取私有仓库地址，如果没有则使用默认值
        if cluster_info:
            private_registry = cluster_info.get('private_registry', const.Registry.DEFAULT_PRIVATE_REGISTRY)
        else:
            private_registry = const.Registry.DEFAULT_PRIVATE_REGISTRY
        
        # 拼接完整的镜像地址
        if private_registry:
            full_init_image = f"{private_registry}/{init_container_image}"
        else:
            full_init_image = init_container_image
        
        # 创建共享 volume 名称（固定目录）
        shared_volume_name = 'package-shared-volume'
        shared_mount_path = '/shared-data/diff-var-files/'  # 固定目录路径
        
        # 添加共享 emptyDir volume
        shared_volume = {
            'name': shared_volume_name,
            'emptyDir': {}
        }
        volumes.append(shared_volume)
        
        # 创建 initContainer
        # 使用环境变量 PACKAGE_URL 传递下载地址
        # 使用 PACKAGE_USERNAME 和 PACKAGE_PASSWORD 传递认证信息
        # 镜像的 ENTRYPOINT 会读取该环境变量并执行下载脚本
        init_container = {
            'name': 'package-downloader',
            'image': full_init_image,  # 使用拼接后的完整镜像地址
            'imagePullPolicy': 'IfNotPresent',
            'env': [
                {
                    'name': 'PACKAGE_URL',
                    'value': package_url
                },
                {
                    'name': 'PACKAGE_USERNAME',
                    'value': const.Artifacts.USERNAME
                },
                {
                    'name': 'PACKAGE_PASSWORD',
                    'value': const.Artifacts.PASSWORD
                }
            ],
            'volumeMounts': [
                {
                    'name': shared_volume_name,
                    'mountPath': shared_mount_path
                }
            ]
        }
        init_containers.append(init_container)
        
        # 将共享 volume 挂载到所有主容器
        for container in containers:
            container['volumeMounts'].append({
                'name': shared_volume_name,
                'mountPath': shared_mount_path,
                'readOnly': True  # 主容器只读访问
            })
    
    return init_containers