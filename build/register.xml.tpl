<?xml version="1.0" encoding="UTF-8"?>
<package name="kubernetes" version="{{PLUGIN_VERSION}}">
    <!-- 1.依赖分析 - 描述运行本插件包需要的其他插件包 -->
    <packageDependencies>
        <packageDependency name="platform" version="v3.0.0" />
    </packageDependencies>

    <!-- 2.菜单注入 - 描述运行本插件包需要注入的菜单 -->
    <menus>
    </menus>

    <!-- 3.数据模型 - 描述本插件包的数据模型,并且描述和Framework数据模型的关系 -->
    <dataModel>
        <entity name="cluster" displayName="集群" description="K8s集群">
            <attribute name="id" datatype="str" description="唯一ID"/>
            <attribute name="name" datatype="str" description="名称"/>
            <attribute name="displayName" datatype="str" description="显示名称"/>
            <attribute name="correlation_id" datatype="ref" description="关联资源ID"
                       refPackage="wecmdb" refVersion="" refEntity="resource_set" ref="id"/>
            <attribute name="api_server" datatype="str" description="API URL"/>
            <attribute name="api_host" datatype="str" description="API地址"/>
            <attribute name="api_port" datatype="str" description="API端口"/>
            <attribute name="token" datatype="str" description="API Token"/>
            <attribute name="metric_host" datatype="str" description="指标服务地址"/>
            <attribute name="metric_port" datatype="str" description="指标服务端口"/>
        </entity>
        <entity name="node" displayName="计算节点" description="K8s集群的Node">
            <attribute name="id" datatype="str" description="唯一ID"/>
            <attribute name="name" datatype="str" description="名称"/>
            <attribute name="displayName" datatype="str" description="显示名称"/>
            <attribute name="ip_address" datatype="str" description="IP地址"/>
            <attribute name="cluster_id" datatype="ref" description="所属集群"
                       refPackage="" refVersion="" refEntity="cluster" ref="id"/>
            <attribute name="correlation_id" datatype="ref" description="关联资源ID"
                       refPackage="wecmdb" refVersion="" refEntity="host_resource_instance" ref="id"/>
        </entity>
        <entity name="deployment" displayName="Deployment" description="Deployment控制器">
            <attribute name="id" datatype="str" description="唯一ID"/>
            <attribute name="name" datatype="str" description="名称"/>
            <attribute name="displayName" datatype="str" description="显示名称"/>
            <attribute name="namespace" datatype="str" description="命名空间"/>
            <attribute name="cluster_id" datatype="ref" description="所属集群"
                       refPackage="" refVersion="" refEntity="cluster" ref="id"/>
            <attribute name="correlation_id" datatype="ref" description="关联资源ID"
                       refPackage="wecmdb" refVersion="" refEntity="unit" ref="id"/>
        </entity>
        <entity name="service" displayName="Service" description="Service服务">
            <attribute name="id" datatype="str" description="唯一ID"/>
            <attribute name="name" datatype="str" description="名称"/>
            <attribute name="displayName" datatype="str" description="显示名称"/>
            <attribute name="namespace" datatype="str" description="命名空间"/>
            <attribute name="ip_address" datatype="str" description="IP地址"/>
            <attribute name="cluster_id" datatype="ref" description="所属集群"
                       refPackage="" refVersion="" refEntity="cluster" ref="id"/>
            <attribute name="correlation_id" datatype="ref" description="关联资源ID"
                       refPackage="wecmdb" refVersion="" refEntity="unit" ref="id"/>
        </entity>
        <entity name="pod" displayName="Pod" description="Pod服务">
            <attribute name="id" datatype="str" description="唯一ID"/>
            <attribute name="name" datatype="str" description="名称"/>
            <attribute name="displayName" datatype="str" description="显示名称"/>
            <attribute name="namespace" datatype="str" description="命名空间"/>
            <attribute name="ip_address" datatype="str" description="IP地址"/>
            <attribute name="deployment_id" datatype="ref" description="所属Deployment"
                       refPackage="" refVersion="" refEntity="deployment" ref="id"/>
            <attribute name="node_id" datatype="ref" description="所属计算节点"
                       refPackage="" refVersion="" refEntity="node" ref="id"/>
            <attribute name="cluster_id" datatype="ref" description="所属集群"
                       refPackage="" refVersion="" refEntity="cluster" ref="id"/>
            <attribute name="correlation_id" datatype="ref" description="关联资源ID"
                       refPackage="wecmdb" refVersion="" refEntity="app_instance" ref="id"/>
        </entity>
    </dataModel>

    <!-- 4.系统参数 - 描述运行本插件包需要的系统参数 -->
    <systemParameters>
        <systemParameter name="KUBERNETES_NOTIFY_POD_ADDED" scopeType="plugins" defaultValue="kubernetes-pod-added" />
        <systemParameter name="KUBERNETES_NOTIFY_POD_DELETED" scopeType="plugins" defaultValue="kubernetes-pod-deleted" />
    </systemParameters>

    <!-- 5.权限设定 -->
    <authorities>
    </authorities>

    <!-- 6.运行资源 - 描述部署运行本插件包需要的基础资源(如主机、虚拟机、容器、数据库等) -->
    <resourceDependencies>
        <docker imageName="{{IMAGENAME}}" containerName="{{CONTAINERNAME}}" portBindings="{{ALLOCATE_PORT}}:9001" volumeBindings="/etc/localtime:/etc/localtime,{{BASE_MOUNT_PATH}}/kubernetes/logs:/var/log/wecubek8s,{{BASE_MOUNT_PATH}}/certs:/certs" envVariables="GATEWAY_URL={{GATEWAY_URL}},JWT_SIGNING_KEY={{JWT_SIGNING_KEY}},SUB_SYSTEM_CODE={{SUB_SYSTEM_CODE}},SUB_SYSTEM_KEY={{SUB_SYSTEM_KEY}},KUBERNETES_DB_USERNAME={{DB_USER}},KUBERNETES_DB_PASSWORD={{DB_PWD}},KUBERNETES_DB_HOSTIP={{DB_HOST}},KUBERNETES_DB_HOSTPORT={{DB_PORT}},KUBERNETES_DB_SCHEMA={{DB_SCHEMA}},ENCRYPT_SEED={{ENCRYPT_SEED}},NOTIFY_POD_ADDED={{KUBERNETES_NOTIFY_POD_ADDED}},NOTIFY_POD_DELETED={{KUBERNETES_NOTIFY_POD_DELETED}}" />
        <mysql schema="kubernetes" initFileName="init.sql" upgradeFileName="upgrade.sql" />
    </resourceDependencies>

    <!-- 7.插件列表 - 描述插件包中单个插件的输入和输出 -->
    <paramObjects>
        <paramObject name="deploymentImage">
            <property name="name" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="ports" datatype="string" refType="" mapType="constant" mapExpr="" />
        </paramObject>
        <paramObject name="commonTag">
            <property name="name" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="value" datatype="string" refType="" mapType="constant" mapExpr="" />
        </paramObject>
        <paramObject name="deploymentEnv">
            <property name="name" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="value" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="valueFrom" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="valueRef" datatype="object" refType="commonTag" mapType="constant" mapExpr="" />
        </paramObject>
        <paramObject name="deploymentVolume">
            <property name="name" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="mountPath" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="readOnly" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="type" datatype="string" refType="" mapType="constant" mapExpr="" />
        </paramObject>
        <paramObject name="servicePort">
            <property name="name" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="protocol" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="port" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="targetPort" datatype="string" refType="" mapType="constant" mapExpr="" />
            <property name="nodePort" datatype="string" refType="" mapType="constant" mapExpr="" />
        </paramObject>
    </paramObjects>
    <plugins>
        <plugin name="cluster">
            <interface action="apply" path="/kubernetes/v1/clusters/apply" httpMethod="POST" isAsyncProcessing="N" type="EXECUTION">
                <inputParameters>
                    <parameter datatype="string" mappingType="constant" required="Y">name</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">correlation_id</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">api_server</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">token</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">metric_host</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">metric_port</parameter>
                </inputParameters>
                <outputParameters>
                    <parameter datatype="string">errorCode</parameter>
                    <parameter datatype="string">errorMessage</parameter>
                    <parameter datatype="string">id</parameter>
                    <parameter datatype="string">name</parameter>
                    <parameter datatype="string">correlation_id</parameter>
                </outputParameters>
            </interface>
            <interface action="destroy" path="/kubernetes/v1/clusters/destroy" httpMethod="POST" isAsyncProcessing="N" type="EXECUTION">
                <inputParameters>
                    <parameter datatype="string" mappingType="constant" required="Y">name</parameter>
                </inputParameters>
                <outputParameters>
                    <parameter datatype="string">errorCode</parameter>
                    <parameter datatype="string">errorMessage</parameter>
                    <parameter datatype="string">id</parameter>
                    <parameter datatype="string">name</parameter>
                    <parameter datatype="string">correlation_id</parameter>
                </outputParameters>
            </interface>
        </plugin>
        <plugin name="deployment">
            <interface action="apply" path="/kubernetes/v1/deployments/apply" httpMethod="POST" isAsyncProcessing="N" type="EXECUTION">
                <inputParameters>
                    <parameter datatype="string" mappingType="constant" required="Y">cluster</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">correlation_id</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">name</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">namespace</parameter>
                    <parameter datatype="list"   mappingType="constant" required="Y" mappingEntityExpression="deploymentImage">images</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">image_pull_username</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">image_pull_password</parameter>
                    <parameter datatype="list"   mappingType="constant" required="N" mappingEntityExpression="commonTag">tags</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">replicas</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">cpu</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">memory</parameter>
                    <parameter datatype="list"   mappingType="constant" required="N" mappingEntityExpression="commonTag">pod_tags</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">affinity</parameter>
                    <parameter datatype="list"   mappingType="constant" required="N" mappingEntityExpression="deploymentEnv">envs</parameter>
                    <parameter datatype="list"   mappingType="constant" required="N" mappingEntityExpression="deploymentVolume">volumes</parameter>
                </inputParameters>
                <outputParameters>
                    <parameter datatype="string">errorCode</parameter>
                    <parameter datatype="string">errorMessage</parameter>
                    <parameter datatype="string">id</parameter>
                    <parameter datatype="string">name</parameter>
                    <parameter datatype="string">correlation_id</parameter>
                </outputParameters>
            </interface>
            <interface action="destroy" path="/kubernetes/v1/deployments/destroy" httpMethod="POST" isAsyncProcessing="N" type="EXECUTION">
                <inputParameters>
                    <parameter datatype="string" mappingType="constant" required="Y">cluster</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">name</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">namespace</parameter>
                </inputParameters>
                <outputParameters>
                    <parameter datatype="string">errorCode</parameter>
                    <parameter datatype="string">errorMessage</parameter>
                    <parameter datatype="string">id</parameter>
                    <parameter datatype="string">name</parameter>
                    <parameter datatype="string">correlation_id</parameter>
                </outputParameters>
            </interface>
        </plugin>
        <plugin name="service">
            <interface action="apply" path="/kubernetes/v1/services/apply" httpMethod="POST" isAsyncProcessing="N" type="EXECUTION">
                <inputParameters>
                    <parameter datatype="string" mappingType="constant" required="Y">cluster</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">correlation_id</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">name</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">namespace</parameter>
                    <parameter datatype="string" mappingType="constant" required="N" >type</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">clusterIP</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">sessionAffinity</parameter>
                    <parameter datatype="list"   mappingType="constant" required="N" mappingEntityExpression="commonTag">tags</parameter>
                    <parameter datatype="list"   mappingType="constant" required="Y" mappingEntityExpression="commonTag">selectors</parameter>
                    <parameter datatype="list"   mappingType="constant" required="Y" mappingEntityExpression="servicePort">instances</parameter>
                </inputParameters>
                <outputParameters>
                    <parameter datatype="string">errorCode</parameter>
                    <parameter datatype="string">errorMessage</parameter>
                    <parameter datatype="string">id</parameter>
                    <parameter datatype="string">name</parameter>
                    <parameter datatype="string">correlation_id</parameter>
                </outputParameters>
            </interface>
            <interface action="destroy" path="/kubernetes/v1/services/destroy" httpMethod="POST" isAsyncProcessing="N" type="EXECUTION">
                <inputParameters>
                    <parameter datatype="string" mappingType="constant" required="Y">cluster</parameter>
                    <parameter datatype="string" mappingType="constant" required="Y">name</parameter>
                    <parameter datatype="string" mappingType="constant" required="N">namespace</parameter>
                </inputParameters>
                <outputParameters>
                    <parameter datatype="string">errorCode</parameter>
                    <parameter datatype="string">errorMessage</parameter>
                    <parameter datatype="string">id</parameter>
                    <parameter datatype="string">name</parameter>
                    <parameter datatype="string">correlation_id</parameter>
                </outputParameters>
            </interface>
        </plugin>
    </plugins>
</package>
