# coding=utf-8
"""
wecubek8s.server.base
~~~~~~~~~~~~~~~~~~~~

本模块提供wsgi启动前数据处理能力

"""

from __future__ import absolute_import

import os
from Crypto import Random
from Crypto.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
from Crypto.PublicKey import RSA
from talos.core import config

from wecubek8s.common import utils as plugin_utils

RSA_KEY_PATH = '/certs/rsa_key'


def decrypt_rsa(secret_key, encrypt_text):
    rsakey = RSA.importKey(secret_key)
    cipher = Cipher_pkcs1_v1_5.new(rsakey)
    random_generator = Random.new().read
    text = cipher.decrypt(plugin_utils.b64decode_key(encrypt_text), random_generator)
    return text.decode('utf-8')


@config.intercept('gateway_url', 'jwt_signing_key', 'sub_system_code', 'sub_system_key', 'platform_timezone',
                  'db_username', 'db_password', 'db_hostip', 'db_hostport', 'db_schema', 'platform_encrypt_seed',
                  'notify_pod_added', 'notify_pod_deleted', 'log_level', 'init_container_image')
def get_env_value(value, origin_value):
    prefix = 'ENV@'
    encrypt_prefix = 'RSA@'
    if value.startswith(prefix):
        env_name = value[len(prefix):]
        new_value = os.getenv(env_name, default='')
        if new_value.startswith(encrypt_prefix):
            certs_path = RSA_KEY_PATH
            if os.path.exists(certs_path) and os.path.isfile(certs_path):
                with open(certs_path) as f:
                    new_value = decrypt_rsa(f.read(), new_value[len(encrypt_prefix):])
            else:
                raise ValueError('keys with "RSA@", but rsa_key file not exists')
        return new_value
    return value


@config.intercept('db')
def build_database_connection(db_config, origin_value):
    """
    修复数据库连接字符串的变量替换问题
    处理多种错误格式：
    1. 包含未替换的变量（如 ${db_username}）
    2. 直接使用环境变量名（如 KUBERNETES_DB_SCHEMA）
    3. 格式错误的连接字符串
    """
    if not isinstance(db_config, dict):
        return db_config
    
    connection = db_config.get('connection', '')
    
    # 检查是否需要修复（包含未替换变量、环境变量名、或格式错误）
    needs_fix = False
    if '${' in connection:
        needs_fix = True
        reason = "contains unreplaced variables like ${...}"
    elif 'KUBERNETES_DB_' in connection:
        needs_fix = True
        reason = "contains environment variable names"
    elif not connection.startswith('mysql+pymysql://') or '@' not in connection:
        # 连接字符串格式明显错误
        if connection:  # 只在连接字符串不为空时才尝试修复
            needs_fix = True
            reason = "connection string format is invalid"
    
    if needs_fix:
        print(f"[CONFIG] Detected invalid database connection ({reason})", flush=True)
        print(f"[CONFIG] Original connection (masked): {connection[:50]}...", flush=True)
        
        # 直接从环境变量构建连接字符串
        db_username = os.getenv('KUBERNETES_DB_USERNAME', '')
        db_password = os.getenv('KUBERNETES_DB_PASSWORD', '')
        db_hostip = os.getenv('KUBERNETES_DB_HOSTIP', '')
        db_hostport = os.getenv('KUBERNETES_DB_HOSTPORT', '3306')
        db_schema = os.getenv('KUBERNETES_DB_SCHEMA', '')
        
        # 处理可能的 RSA 加密密码
        if db_password.startswith('RSA@'):
            certs_path = RSA_KEY_PATH
            if os.path.exists(certs_path) and os.path.isfile(certs_path):
                with open(certs_path) as f:
                    db_password = decrypt_rsa(f.read(), db_password[4:])
                    print(f"[CONFIG] Decrypted RSA encrypted password", flush=True)
        
        # 构建新的连接字符串
        if db_username and db_password and db_hostip and db_schema:
            new_connection = f"mysql+pymysql://{db_username}:{db_password}@{db_hostip}:{db_hostport}/{db_schema}?charset=utf8mb4"
            db_config = db_config.copy()  # 不修改原对象
            db_config['connection'] = new_connection
            print(f"[CONFIG] ✓ Database connection rebuilt from environment variables", flush=True)
            print(f"[CONFIG]   mysql+pymysql://{db_username}:****@{db_hostip}:{db_hostport}/{db_schema}", flush=True)
        else:
            print(f"[CONFIG] ✗ WARNING: Cannot rebuild connection - missing environment variables:", flush=True)
            print(f"[CONFIG]   KUBERNETES_DB_USERNAME: {'✓' if db_username else '✗ MISSING'}", flush=True)
            print(f"[CONFIG]   KUBERNETES_DB_PASSWORD: {'✓' if db_password else '✗ MISSING'}", flush=True)
            print(f"[CONFIG]   KUBERNETES_DB_HOSTIP: {'✓' if db_hostip else '✗ MISSING'}", flush=True)
            print(f"[CONFIG]   KUBERNETES_DB_SCHEMA: {'✓' if db_schema else '✗ MISSING'}", flush=True)
    
    return db_config
