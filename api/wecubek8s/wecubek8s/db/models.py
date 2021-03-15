# coding=utf-8

from __future__ import absolute_import

from talos.db.dictbase import DictBase
from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
metadata = Base.metadata


