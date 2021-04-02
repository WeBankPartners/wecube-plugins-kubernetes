# coding=utf-8

from __future__ import absolute_import

from sqlalchemy import Column, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from talos.db.dictbase import DictBase

Base = declarative_base()
metadata = Base.metadata


class Cluster(Base, DictBase):
    __tablename__ = 'cluster'

    id = Column(String(36), primary_key=True)
    name = Column(String(36), unique=True)
    correlation_id = Column(String(36))
    api_server = Column(String(100), nullable=False)
    token = Column(String(2048), nullable=False)
    created_by = Column(String(36))
    created_time = Column(DateTime)
    updated_by = Column(String(36))
    updated_time = Column(DateTime)