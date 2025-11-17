SET FOREIGN_KEY_CHECKS = 0;
CREATE TABLE `cluster` (
  `id` varchar(255) NOT NULL,
  `name` varchar(255) DEFAULT NULL,
  `correlation_id` varchar(36) DEFAULT NULL,
  `api_server` varchar(255) NOT NULL,
  `token` varchar(2048) NOT NULL,
  `metric_host` varchar(63) DEFAULT NULL,
  `metric_port` varchar(20) DEFAULT NULL,
  `created_by` varchar(36) DEFAULT NULL,
  `created_time` datetime DEFAULT NULL,
  `updated_by` varchar(36) DEFAULT NULL,
  `updated_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_cluster_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

SET FOREIGN_KEY_CHECKS = 1;

#@v0.1.5-begin@;
-- 删除旧字段
ALTER TABLE `cluster` DROP COLUMN IF EXISTS `metric_host`;
ALTER TABLE `cluster` DROP COLUMN IF EXISTS `metric_port`;

-- 添加新字段
ALTER TABLE `cluster` ADD COLUMN `image_pull_username` varchar(255) DEFAULT NULL COMMENT '镜像仓库用户名';
ALTER TABLE `cluster` ADD COLUMN `image_pull_password` varchar(255) DEFAULT NULL COMMENT '镜像仓库密码';
ALTER TABLE `cluster` ADD COLUMN `private_registry` varchar(255) DEFAULT NULL COMMENT '私有镜像仓库地址';

#@v0.1.5-end@;
