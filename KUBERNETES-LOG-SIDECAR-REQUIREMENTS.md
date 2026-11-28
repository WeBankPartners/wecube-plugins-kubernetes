# K8s 插件业务日志采集 Sidecar 更改需求说明

## 背景与目标

WeCube 通过 Kubernetes 插件部署 Deployment 和 StatefulSet。需要采集业务文件日志的部署，由插件在 Pod 模板中加入 Open-Monitor 的 `node_exporter`，让应用和 exporter 共享日志目录。Monitor 可以凭 Pod 上的部署标识找到对应实例，并连接 `PodIP:9100` 下发规则和抓取指标。

本说明覆盖两个 `apply` 接口的入参、Pod 模板生成、镜像拉取和部署验收。编排在 `apply` 成功后提交部署级业务日志配置。Monitor 负责发现 Pod、关联业务对象、下发日志规则和更新抓取目标。

## 接口和发现约定

| 项目 | 要求 |
| --- | --- |
| 生效接口 | `POST /kubernetes/v1/deployments/apply` 和 `POST /kubernetes/v1/statefulsets/apply` |
| 开关 | 新增可选入参 `enable_log_sidecar`，默认 `false`。通过 WeCube 编排开启的部署，在后续每次 `apply` 时继续传 `true`。在两个接口的插件注册描述和请求校验中声明该字段。 |
| 容器日志目录 | 启用时优先使用显式的 `log_path`，其次使用 `deployment_path` 下的 `logs` 子目录，两者均为空时使用 `/logs`。应用和 exporter 使用同一个目录，`__FILE_LOG_PATH__` 使用该目录下的 `*.log`。 |
| 发现标签 | 在启用时向 `spec.template.metadata.labels` 写入 `wecube.io/log-monitor: enabled`。标签用于 Pod 发现，模板构建时保持原有 workload 和 Service selector。 |
| 部署标识 | 向 `spec.template.metadata.annotations` 写入 `wecube.io/log-monitor-workload-id`，值来自现有 `correlation_id`，保留标识原值。编排用同一个值注册业务日志配置，Monitor 用集群、namespace 和该标识匹配。 |

部署标识是跨角色契约。首版以 `correlation_id` 为候选，联调前由编排侧确认它在同一部署单元的重复发布、滚动更新和扩缩容中保持稳定，并在同一集群、namespace 内能唯一定位部署单元。若现网语义不同，三方先确认实际使用的稳定字段，再实现同一条匹配约定。

现有 `apply` 输出继续用于编排后续步骤。日志配置节点从编排上下文取得同一个部署标识、集群和 namespace。业务组 GUID、日志文件路径、日志模板和交易码由该配置节点提交给 Monitor。

[Apply 接口注册描述](build/register.xml.tpl#L154) · [Deployment 请求校验](api/wecubek8s/wecubek8s/apps/plugin/controller.py#L117) · [StatefulSet 请求校验](api/wecubek8s/wecubek8s/apps/plugin/controller.py#L721)

## Pod 模板要求

### 容器与镜像

- 在 `spec.template.spec.containers` 追加名为 `log-exporter` 的容器，使用镜像默认命令，声明名为 `log-metrics` 的 `9100/TCP` 容器端口。已有应用容器继续使用自己的启动脚本、探针和资源配置。`package-downloader` 继续作为 `initContainers` 处理差异化变量包。
- 从 `KUBERNETES_LOG_SIDECAR_IMAGE` 读取 exporter 镜像。完整地址直接使用，相对地址用目标集群的 `private_registry` 补齐，两种形式都支持 tag 和 digest。Sandbox 的 `wecube/monitor-exporter-sidecar:v1.0.0` 解析为 `10.200.16.10:8443/wecube/monitor-exporter-sidecar:v1.0.0`。相对地址缺少仓库配置时，在提交工作负载前报错。同仓库复用 Pod 已有的 `imagePullSecrets`，额外配置的拉取 Secret 按名称合并去重。
- Prometheus 和 Monitor 从集群外直接访问 Pod IP。工作负载模板声明容器端口即可。应用与 sidecar 共用 Pod 网络，已声明的容器名、端口或卷名冲突应在提交 workload 前给出明确错误。

### 日志共享与规则缓存

1. **优先复用已有日志卷。** 按 `log_path` 查找应用容器的有效可写挂载。找到后将同一个卷以同一路径只读挂载给 exporter，并保留 `subPath` 或 `subPathExpr`（如已配置）。现有 `instance-logs`、日志 PVC 和 Pod 级日志卷均按此规则处理。StatefulSet 以最终有效的 PVC 模板和挂载为准。已有挂载占用该目录但无法用作共享日志卷时，报出冲突和原挂载来源。
2. **没有日志卷时创建 Pod 级 `emptyDir`。** 应用读写解析出的容器日志目录，exporter 在同一路径只读。`deployment_path` 推导容器目录时无须新增节点挂载。原有自动 `hostPath` 仍受 `KUBERNETES_ENABLE_HOST_PATH` 控制，启用采集时可继续使用存量挂载。应用部署配置应把实际日志写到共享目录中。`emptyDir` 随 Pod 结束，Pod 被替换时会得到新目录。
3. **给 exporter 提供独立可写卷。** 用单独的 `emptyDir` 挂载 `/app/monitor/data`，保存下发的规则缓存。配置包、业务日志和规则缓存分别使用各自的卷。
4. **确认权限与副本隔离。** 沿用现有 Pod `fsGroup: 10001`。exporter 以 `65534:65534` 运行，需要能遍历日志目录、读取新建及轮转后的文件，并写入自己的缓存目录。复用 `hostPath` 时用节点上的实际目录权限验证。多个副本共用存储时，日志路径应按副本隔离，避免同一文件被重复采集。

[Deployment 模板和日志卷](api/wecubek8s/wecubek8s/apps/plugin/api.py#L2069) · [StatefulSet 模板和日志卷](api/wecubek8s/wecubek8s/apps/plugin/api.py#L2525) · [StatefulSet PVC 更新处理](api/wecubek8s/wecubek8s/apps/plugin/api.py#L3091) · [配置包 init container](api/wecubek8s/wecubek8s/apps/plugin/utils.py#L603)

## 更新与关闭

- 两种 workload 共用 sidecar 组装逻辑。在应用容器的启动配置、探针和日志卷准备好后追加 sidecar。StatefulSet 更新保留既有不可变字段，并在提交前校验日志卷引用仍有效。
- 对已有 workload 开启或关闭功能都通过其 Pod 模板更新，由 Kubernetes 按滚动策略替换实例。关闭时从新模板移除插件注入的 sidecar、发现元数据和专用缓存卷。继续保留应用原有日志挂载。应用仍使用原 `log_path` 且没有配置替代卷时，保留此前为该目录自动创建的共享日志挂载，使新 Pod 的应用日志目录仍可写。
- 重复提交相同配置，生成的 Pod 模板应一致。sidecar 镜像拉取或启动失败时，沿用现有 `apply` 就绪检查并展示出错容器和原因。既有工作负载的更新窗口按其滚动策略评估，尤其是单副本 StatefulSet。

## 验收条件

| 场景 | 预期结果 |
| --- | --- |
| Deployment 和 StatefulSet 开启开关 | 新 Pod 包含 `log-exporter`、可用的日志和缓存挂载，以及准确的发现标签和部署标识。配置了 `packageUrl` 时，`package-downloader` 正常执行，应用按原启动流程运行。 |
| 复用日志卷 | 分别验证已有 `hostPath` 和 StatefulSet 已有日志 PVC。应用写入的文件可被 exporter 读取，exporter 的日志挂载为只读。存量 StatefulSet 可以通过原有更新路径提交。 |
| 新建共享卷 | 无已有日志挂载时，新 Pod 中应用能写入 `log_path`、exporter 能读取该文件并写入缓存目录。关闭自动 `hostPath` 的集群也能部署。 |
| 默认关闭、重复提交和关闭已启用的功能 | 未传开关的首次部署按现有应用模板生成。重复提交后 Pod 模板一致，容器、卷和 Secret 各出现一次。关闭后新 Pod 的应用日志路径仍可用。 |
| 网络与联调 | 从 Monitor 实际运行的网络访问测试 Pod 的 `PodIP:9100/metrics`。编排注册日志配置后，Monitor 能以部署标识匹配到 Pod。滚动替换后，新 Pod 带有相同部署标识和新的 Pod UID。 |
