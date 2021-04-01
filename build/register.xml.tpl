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
    </systemParameters>

    <!-- 5.权限设定 -->
    <authorities>
    </authorities>

    <!-- 6.运行资源 - 描述部署运行本插件包需要的基础资源(如主机、虚拟机、容器、数据库等) -->
    <resourceDependencies>
        <docker imageName="{{IMAGENAME}}" containerName="{{CONTAINERNAME}}" portBindings="{{ALLOCATE_PORT}}:9001" volumeBindings="/etc/localtime:/etc/localtime,{{BASE_MOUNT_PATH}}/kubernetes/logs:/var/log/wecubek8s,{{BASE_MOUNT_PATH}}/certs:/certs" envVariables="GATEWAY_URL={{GATEWAY_URL}},JWT_SIGNING_KEY={{JWT_SIGNING_KEY}},SUB_SYSTEM_CODE={{SUB_SYSTEM_CODE}},SUB_SYSTEM_KEY={{SUB_SYSTEM_KEY}},KUBERNETES_DB_USERNAME={{DB_USER}},KUBERNETES_DB_PASSWORD={{DB_PWD}},KUBERNETES_DB_HOSTIP={{DB_HOST}},KUBERNETES_DB_HOSTPORT={{DB_PORT}},KUBERNETES_DB_SCHEMA={{DB_SCHEMA}},ENCRYPT_SEED={{ENCRYPT_SEED}}" />
        <mysql schema="kubernetes" initFileName="init.sql" upgradeFileName="upgrade.sql" />
    </resourceDependencies>

    <!-- 7.插件列表 - 描述插件包中单个插件的输入和输出 -->
    <plugins></plugins>
</package>
