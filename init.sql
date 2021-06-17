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
