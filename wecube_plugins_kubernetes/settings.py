# _*_ coding:utf-8 _*_
from __future__ import (absolute_import, division, print_function, unicode_literals)

import os

SECRET_KEY = 'o32_bglz)m_t&ezts^6@c&pv$sj2hi4@dwla3p(77r_krp@__9'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_BASE_PATH = os.path.join(BASE_DIR, 'logs')
KEY_BASE_PATH = os.path.join(BASE_DIR, 'key')
YAML_TMP_PATH = os.path.join(LOG_BASE_PATH, "yamlfiles")
CAFILE_PATH = os.path.join(BASE_DIR, 'cafile')

# Application definition
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
]

MIDDLEWARE = [
    'wecube_plugins_kubernetes.logmiddleware.logger_middleware',
    'django.middleware.security.SecurityMiddleware'
]

from ._config import *

ROOT_URLCONF = 'wecube_plugins_kubernetes.urls'
WSGI_APPLICATION = 'wecube_plugins_kubernetes.wsgi.application'
ALLOWED_HOSTS = ["*"]
DEFAULT_CHARSET = 'UTF-8'
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
STATIC_URL = '/static/'
USE_I18N = True
USE_L10N = True
USE_TZ = True
