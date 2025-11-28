#!/bin/bash

# Pod 全面诊断脚本
# 用于诊断 Kubernetes Pod 的各种问题
# 使用方法: ./diagnose-pod-full.sh [namespace] [pod-name-pattern]

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 分隔线
separator() {
    echo -e "${CYAN}==================================================================================${NC}"
}

big_separator() {
    echo ""
    echo -e "${BLUE}##################################################################################${NC}"
    echo -e "${BLUE}#${NC} $1"
    echo -e "${BLUE}##################################################################################${NC}"
    echo ""
}

# 打印标题
print_header() {
    echo -e "${YELLOW}>>> $1${NC}"
}

# 打印成功信息
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# 打印错误信息
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# 打印警告信息
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# 打印信息
print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# 获取参数
NAMESPACE=${1:-default}
POD_PATTERN=${2:-""}

big_separator "Kubernetes Pod 全面诊断工具"

echo "诊断时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "目标命名空间: $NAMESPACE"
if [ -n "$POD_PATTERN" ]; then
    echo "Pod 名称模式: $POD_PATTERN"
else
    echo "Pod 名称模式: 所有 Pod"
fi
echo ""

# 检查 kubectl 是否可用
print_header "检查 kubectl 连接"
if ! kubectl cluster-info &>/dev/null; then
    print_error "无法连接到 Kubernetes 集群"
    echo "请检查 kubectl 配置和集群连接"
    exit 1
fi
print_success "Kubernetes 集群连接正常"
echo ""

# 获取集群信息
print_header "集群基本信息"
separator
echo "Kubernetes 版本:"
kubectl version --short 2>/dev/null || kubectl version
echo ""
echo "集群节点状态:"
kubectl get nodes -o wide
separator
echo ""

# 检查命名空间是否存在
print_header "检查命名空间"
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    print_error "命名空间 '$NAMESPACE' 不存在"
    echo ""
    echo "可用的命名空间:"
    kubectl get namespaces
    exit 1
fi
print_success "命名空间 '$NAMESPACE' 存在"
echo ""

# 获取 Pod 列表
print_header "获取 Pod 列表"
if [ -n "$POD_PATTERN" ]; then
    PODS=$(kubectl get pods -n "$NAMESPACE" --no-headers | grep "$POD_PATTERN" | awk '{print $1}')
else
    PODS=$(kubectl get pods -n "$NAMESPACE" --no-headers | awk '{print $1}')
fi

if [ -z "$PODS" ]; then
    print_error "未找到匹配的 Pod"
    echo ""
    echo "命名空间 '$NAMESPACE' 中的所有 Pod:"
    kubectl get pods -n "$NAMESPACE"
    exit 1
fi

POD_COUNT=$(echo "$PODS" | wc -l | tr -d ' ')
print_success "找到 $POD_COUNT 个匹配的 Pod"
echo ""

# 显示所有 Pod 的概览
big_separator "Pod 概览"
kubectl get pods -n "$NAMESPACE" -o wide
echo ""

# 详细诊断每个 Pod
for POD in $PODS; do
    big_separator "诊断 Pod: $POD"
    
    # 1. Pod 基本信息
    print_header "1. Pod 基本信息"
    separator
    kubectl get pod "$POD" -n "$NAMESPACE" -o wide
    separator
    echo ""
    
    # 2. Pod 详细状态
    print_header "2. Pod 详细状态 (YAML)"
    separator
    kubectl get pod "$POD" -n "$NAMESPACE" -o yaml
    separator
    echo ""
    
    # 3. Pod 状态摘要
    print_header "3. Pod 状态摘要"
    separator
    POD_STATUS=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
    POD_READY=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
    POD_REASON=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.reason}')
    POD_MESSAGE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.message}')
    
    echo "状态 (Phase): $POD_STATUS"
    echo "就绪状态 (Ready): $POD_READY"
    if [ -n "$POD_REASON" ]; then
        echo "原因: $POD_REASON"
    fi
    if [ -n "$POD_MESSAGE" ]; then
        echo "消息: $POD_MESSAGE"
    fi
    
    # 检查状态并给出建议
    echo ""
    case "$POD_STATUS" in
        "Running")
            if [ "$POD_READY" = "True" ]; then
                print_success "Pod 运行正常且就绪"
            else
                print_warning "Pod 正在运行但未就绪"
                echo "可能原因:"
                echo "  - 健康检查失败 (readiness probe)"
                echo "  - 容器内部服务未启动完成"
                echo "  - 端口未正确监听"
            fi
            ;;
        "Pending")
            print_error "Pod 处于 Pending 状态"
            echo "可能原因:"
            echo "  - 节点资源不足 (CPU/内存)"
            echo "  - 镜像拉取失败"
            echo "  - PVC 挂载失败"
            echo "  - 节点亲和性/污点不匹配"
            ;;
        "Failed")
            print_error "Pod 失败"
            echo "需要检查容器日志和事件"
            ;;
        "CrashLoopBackOff")
            print_error "Pod 反复崩溃重启"
            echo "可能原因:"
            echo "  - 应用程序错误"
            echo "  - 配置错误"
            echo "  - 依赖服务不可用"
            ;;
        "ImagePullBackOff"|"ErrImagePull")
            print_error "镜像拉取失败"
            echo "可能原因:"
            echo "  - 镜像不存在"
            echo "  - 镜像仓库认证失败"
            echo "  - 网络连接问题"
            ;;
        *)
            print_warning "未知状态: $POD_STATUS"
            ;;
    esac
    separator
    echo ""
    
    # 4. 容器状态
    print_header "4. 容器状态"
    separator
    CONTAINERS=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.spec.containers[*].name}')
    INIT_CONTAINERS=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.spec.initContainers[*].name}')
    
    if [ -n "$INIT_CONTAINERS" ]; then
        echo "Init 容器:"
        for CONTAINER in $INIT_CONTAINERS; do
            echo ""
            echo "  容器名称: $CONTAINER"
            CONTAINER_STATE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].state}" | jq -r 'keys[0]' 2>/dev/null || echo "unknown")
            CONTAINER_READY=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].ready}")
            CONTAINER_RESTART=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].restartCount}")
            
            echo "  状态: $CONTAINER_STATE"
            echo "  就绪: $CONTAINER_READY"
            echo "  重启次数: $CONTAINER_RESTART"
            
            # 详细状态信息
            if [ "$CONTAINER_STATE" = "waiting" ]; then
                REASON=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].state.waiting.reason}")
                MESSAGE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].state.waiting.message}")
                print_warning "  等待原因: $REASON"
                if [ -n "$MESSAGE" ]; then
                    echo "  消息: $MESSAGE"
                fi
            elif [ "$CONTAINER_STATE" = "terminated" ]; then
                REASON=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].state.terminated.reason}")
                EXIT_CODE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.initContainerStatuses[?(@.name=='$CONTAINER')].state.terminated.exitCode}")
                print_error "  终止原因: $REASON"
                echo "  退出码: $EXIT_CODE"
            fi
        done
        echo ""
    fi
    
    echo "主容器:"
    for CONTAINER in $CONTAINERS; do
        echo ""
        echo "  容器名称: $CONTAINER"
        CONTAINER_STATE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].state}" | jq -r 'keys[0]' 2>/dev/null || echo "unknown")
        CONTAINER_READY=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].ready}")
        CONTAINER_RESTART=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].restartCount}")
        CONTAINER_IMAGE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].image}")
        
        echo "  状态: $CONTAINER_STATE"
        echo "  就绪: $CONTAINER_READY"
        echo "  重启次数: $CONTAINER_RESTART"
        echo "  镜像: $CONTAINER_IMAGE"
        
        # 详细状态信息
        if [ "$CONTAINER_STATE" = "waiting" ]; then
            REASON=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].state.waiting.reason}")
            MESSAGE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].state.waiting.message}")
            print_warning "  等待原因: $REASON"
            if [ -n "$MESSAGE" ]; then
                echo "  消息: $MESSAGE"
            fi
        elif [ "$CONTAINER_STATE" = "terminated" ]; then
            REASON=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].state.terminated.reason}")
            EXIT_CODE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].state.terminated.exitCode}")
            print_error "  终止原因: $REASON"
            echo "  退出码: $EXIT_CODE"
        fi
        
        # 重启次数警告
        if [ "$CONTAINER_RESTART" -gt 0 ]; then
            print_warning "  容器已重启 $CONTAINER_RESTART 次"
        fi
    done
    separator
    echo ""
    
    # 5. Pod 事件
    print_header "5. Pod 相关事件"
    separator
    kubectl get events -n "$NAMESPACE" --field-selector involvedObject.name="$POD" --sort-by='.lastTimestamp'
    separator
    echo ""
    
    # 6. Pod 标签
    print_header "6. Pod 标签"
    separator
    kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.metadata.labels}' | jq '.'
    
    # 检查关键标签
    echo ""
    echo "关键标签检查:"
    POD_AFFINITY=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.metadata.labels.wecube_plugins_kubernetes_pod_affinity}')
    POD_AUTO=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.metadata.labels.wecube_plugins_kubernetes_pod_auto}')
    
    if [ -n "$POD_AFFINITY" ]; then
        # 检查标签值是否符合 Kubernetes 规范
        if [[ "$POD_AFFINITY" =~ ^[a-zA-Z0-9]([-a-zA-Z0-9_.]*[a-zA-Z0-9])?$ ]]; then
            print_success "pod_affinity 标签格式正确: $POD_AFFINITY"
        else
            print_error "pod_affinity 标签格式不符合 Kubernetes 规范: $POD_AFFINITY"
            echo "  标签值必须匹配正则: ^[a-zA-Z0-9]([-a-zA-Z0-9_.]*[a-zA-Z0-9])?\$"
        fi
    else
        print_warning "未找到 pod_affinity 标签"
    fi
    
    if [ -n "$POD_AUTO" ]; then
        if [[ "$POD_AUTO" =~ ^[a-zA-Z0-9]([-a-zA-Z0-9_.]*[a-zA-Z0-9])?$ ]]; then
            print_success "pod_auto 标签格式正确: $POD_AUTO"
        else
            print_error "pod_auto 标签格式不符合 Kubernetes 规范: $POD_AUTO"
        fi
    else
        print_warning "未找到 pod_auto 标签"
    fi
    separator
    echo ""
    
    # 7. Pod 注解
    print_header "7. Pod 注解 (Annotations)"
    separator
    kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations}' | jq '.'
    separator
    echo ""
    
    # 8. 资源请求和限制
    print_header "8. 资源请求和限制"
    separator
    echo "容器资源配置:"
    for CONTAINER in $CONTAINERS; do
        echo ""
        echo "  容器: $CONTAINER"
        REQUESTS_CPU=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].resources.requests.cpu}")
        REQUESTS_MEM=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].resources.requests.memory}")
        LIMITS_CPU=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].resources.limits.cpu}")
        LIMITS_MEM=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].resources.limits.memory}")
        
        echo "    请求 CPU: ${REQUESTS_CPU:-未设置}"
        echo "    请求内存: ${REQUESTS_MEM:-未设置}"
        echo "    限制 CPU: ${LIMITS_CPU:-未设置}"
        echo "    限制内存: ${LIMITS_MEM:-未设置}"
    done
    
    # 检查节点资源
    echo ""
    echo "所在节点资源情况:"
    NODE=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}')
    if [ -n "$NODE" ]; then
        kubectl describe node "$NODE" | grep -A 5 "Allocated resources"
    else
        print_warning "Pod 尚未分配到节点"
    fi
    separator
    echo ""
    
    # 9. 卷挂载
    print_header "9. 卷挂载"
    separator
    VOLUMES=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.spec.volumes}' | jq '.')
    echo "Pod 卷配置:"
    echo "$VOLUMES" | jq '.'
    
    echo ""
    echo "容器挂载点:"
    for CONTAINER in $CONTAINERS; do
        echo ""
        echo "  容器: $CONTAINER"
        kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].volumeMounts}" | jq '.'
    done
    separator
    echo ""
    
    # 10. 网络配置
    print_header "10. 网络配置"
    separator
    POD_IP=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.podIP}')
    HOST_IP=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.hostIP}')
    echo "Pod IP: ${POD_IP:-未分配}"
    echo "主机 IP: ${HOST_IP:-未知}"
    echo ""
    echo "端口配置:"
    for CONTAINER in $CONTAINERS; do
        echo "  容器: $CONTAINER"
        kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].ports}" | jq '.'
    done
    separator
    echo ""
    
    # 11. 健康检查配置
    print_header "11. 健康检查配置"
    separator
    for CONTAINER in $CONTAINERS; do
        echo "容器: $CONTAINER"
        echo ""
        echo "  Liveness Probe (存活探针):"
        LIVENESS=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].livenessProbe}")
        if [ -n "$LIVENESS" ]; then
            echo "$LIVENESS" | jq '.'
        else
            echo "    未配置"
        fi
        
        echo ""
        echo "  Readiness Probe (就绪探针):"
        READINESS=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].readinessProbe}")
        if [ -n "$READINESS" ]; then
            echo "$READINESS" | jq '.'
        else
            echo "    未配置"
        fi
        
        echo ""
        echo "  Startup Probe (启动探针):"
        STARTUP=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].startupProbe}")
        if [ -n "$STARTUP" ]; then
            echo "$STARTUP" | jq '.'
        else
            echo "    未配置"
        fi
        echo ""
    done
    separator
    echo ""
    
    # 12. 环境变量
    print_header "12. 环境变量"
    separator
    for CONTAINER in $CONTAINERS; do
        echo "容器: $CONTAINER"
        kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.spec.containers[?(@.name=='$CONTAINER')].env}" | jq '.'
        echo ""
    done
    separator
    echo ""
    
    # 13. 容器日志（最近100行）
    print_header "13. 容器日志 (最近 100 行)"
    separator
    
    if [ -n "$INIT_CONTAINERS" ]; then
        for CONTAINER in $INIT_CONTAINERS; do
            echo "Init 容器 [$CONTAINER] 日志:"
            echo "---"
            kubectl logs "$POD" -n "$NAMESPACE" -c "$CONTAINER" --tail=100 2>&1 || echo "无法获取日志"
            echo ""
        done
    fi
    
    for CONTAINER in $CONTAINERS; do
        echo "容器 [$CONTAINER] 日志:"
        echo "---"
        kubectl logs "$POD" -n "$NAMESPACE" -c "$CONTAINER" --tail=100 2>&1 || echo "无法获取日志"
        echo ""
        
        # 如果容器重启过，也显示之前的日志
        if [ "$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].restartCount}")" -gt 0 ]; then
            echo "容器 [$CONTAINER] 上次运行日志 (重启前):"
            echo "---"
            kubectl logs "$POD" -n "$NAMESPACE" -c "$CONTAINER" --previous --tail=100 2>&1 || echo "无法获取之前的日志"
            echo ""
        fi
    done
    separator
    echo ""
    
    # 14. 所属控制器
    print_header "14. 所属控制器"
    separator
    OWNER_KIND=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.metadata.ownerReferences[0].kind}')
    OWNER_NAME=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.metadata.ownerReferences[0].name}')
    
    if [ -n "$OWNER_KIND" ]; then
        echo "控制器类型: $OWNER_KIND"
        echo "控制器名称: $OWNER_NAME"
        echo ""
        
        case "$OWNER_KIND" in
            "ReplicaSet")
                echo "ReplicaSet 详情:"
                kubectl get replicaset "$OWNER_NAME" -n "$NAMESPACE" -o wide
                echo ""
                echo "ReplicaSet 事件:"
                kubectl get events -n "$NAMESPACE" --field-selector involvedObject.name="$OWNER_NAME" --sort-by='.lastTimestamp' | tail -20
                ;;
            "StatefulSet")
                echo "StatefulSet 详情:"
                kubectl get statefulset "$OWNER_NAME" -n "$NAMESPACE" -o wide
                echo ""
                echo "StatefulSet 事件:"
                kubectl get events -n "$NAMESPACE" --field-selector involvedObject.name="$OWNER_NAME" --sort-by='.lastTimestamp' | tail -20
                
                # 检查 Service
                echo ""
                echo "关联的 Headless Service:"
                SERVICE_NAME=$(kubectl get statefulset "$OWNER_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.serviceName}')
                if [ -n "$SERVICE_NAME" ]; then
                    kubectl get service "$SERVICE_NAME" -n "$NAMESPACE" -o wide
                else
                    print_warning "未找到关联的 Service"
                fi
                ;;
            "DaemonSet")
                echo "DaemonSet 详情:"
                kubectl get daemonset "$OWNER_NAME" -n "$NAMESPACE" -o wide
                ;;
        esac
    else
        print_warning "未找到所属控制器（可能是独立 Pod）"
    fi
    separator
    echo ""
    
    # 15. DNS 和网络连通性测试
    print_header "15. DNS 和网络测试"
    separator
    if [ "$POD_STATUS" = "Running" ]; then
        echo "尝试在 Pod 内执行网络测试..."
        echo ""
        
        # 测试 DNS
        echo "DNS 解析测试:"
        kubectl exec "$POD" -n "$NAMESPACE" -c "${CONTAINERS%% *}" -- nslookup kubernetes.default 2>&1 | head -20 || print_warning "无法执行 DNS 测试（nslookup 不可用）"
        
        echo ""
        echo "网络接口:"
        kubectl exec "$POD" -n "$NAMESPACE" -c "${CONTAINERS%% *}" -- ip addr 2>&1 || print_warning "无法获取网络接口信息"
        
        echo ""
        echo "路由表:"
        kubectl exec "$POD" -n "$NAMESPACE" -c "${CONTAINERS%% *}" -- ip route 2>&1 || print_warning "无法获取路由信息"
    else
        print_warning "Pod 未运行，跳过网络测试"
    fi
    separator
    echo ""
    
    # 16. 问题总结和建议
    print_header "16. 问题总结和建议"
    separator
    
    echo "基于上述信息的问题分析:"
    echo ""
    
    # 状态检查
    if [ "$POD_STATUS" != "Running" ] || [ "$POD_READY" != "True" ]; then
        print_error "Pod 状态异常"
        echo ""
        
        # 根据不同状态给出建议
        if [ "$POD_STATUS" = "Pending" ]; then
            echo "建议检查:"
            echo "  1. 查看事件部分，确认是否有调度失败信息"
            echo "  2. 检查节点资源是否充足"
            echo "  3. 检查镜像拉取策略和镜像仓库访问"
            echo "  4. 检查 PVC 是否正常绑定"
            echo "  5. 检查节点亲和性和污点容忍配置"
        elif [[ "$POD_STATUS" = *"CrashLoopBackOff"* ]] || [ "$POD_STATUS" = "Error" ]; then
            echo "建议检查:"
            echo "  1. 查看容器日志，确认应用启动失败原因"
            echo "  2. 检查环境变量配置是否正确"
            echo "  3. 检查存储卷挂载是否成功"
            echo "  4. 检查应用依赖的服务是否可用"
            echo "  5. 检查健康检查配置是否合理"
        elif [[ "$POD_STATUS" = *"ImagePull"* ]]; then
            echo "建议检查:"
            echo "  1. 确认镜像名称和标签是否正确"
            echo "  2. 检查镜像仓库认证凭据 (ImagePullSecrets)"
            echo "  3. 检查节点到镜像仓库的网络连接"
            echo "  4. 确认镜像是否存在于仓库中"
        fi
    else
        print_success "Pod 运行正常"
    fi
    
    # 重启检查
    echo ""
    TOTAL_RESTARTS=0
    for CONTAINER in $CONTAINERS; do
        RESTART_COUNT=$(kubectl get pod "$POD" -n "$NAMESPACE" -o jsonpath="{.status.containerStatuses[?(@.name=='$CONTAINER')].restartCount}")
        TOTAL_RESTARTS=$((TOTAL_RESTARTS + RESTART_COUNT))
    done
    
    if [ "$TOTAL_RESTARTS" -gt 0 ]; then
        print_warning "检测到容器重启 (总计: $TOTAL_RESTARTS 次)"
        echo "建议:"
        echo "  1. 查看容器日志，特别是重启前的日志"
        echo "  2. 检查是否是 OOM (内存溢出) 导致"
        echo "  3. 检查健康检查是否配置过于严格"
        echo "  4. 确认应用是否稳定"
    fi
    
    # 标签检查
    echo ""
    if [ -n "$POD_AFFINITY" ] && [[ ! "$POD_AFFINITY" =~ ^[a-zA-Z0-9]([-a-zA-Z0-9_.]*[a-zA-Z0-9])?$ ]]; then
        print_error "检测到标签格式问题"
        echo "标签 'pod_affinity' 的值 '$POD_AFFINITY' 不符合 Kubernetes 规范"
        echo "建议:"
        echo "  1. 更新代码，使用 escape_label_value 函数处理标签值"
        echo "  2. 重新部署 Pod"
        echo "  3. 参考修复文档进行处理"
    fi
    
    separator
    echo ""
    
done

big_separator "诊断完成"

print_success "所有 Pod 诊断完成"
echo ""
echo "如果 Pod 存在问题，请将此输出提供给技术支持人员进行进一步分析"
echo ""
echo "常用后续操作:"
echo "  - 重启 Pod: kubectl delete pod <pod-name> -n $NAMESPACE"
echo "  - 查看完整日志: kubectl logs <pod-name> -n $NAMESPACE -c <container-name> --tail=-1"
echo "  - 进入 Pod 调试: kubectl exec -it <pod-name> -n $NAMESPACE -- /bin/sh"
echo "  - 查看更多事件: kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp'"
echo ""

