# coding=utf-8

from __future__ import absolute_import

from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from talos.db.dictbase import DictBase

Base = declarative_base()
metadata = Base.metadata


class Cluster(Base, DictBase):
    __tablename__ = 'cluster'

    id = Column(String(255), primary_key=True)
    name = Column(String(255), unique=True)
    correlation_id = Column(String(64))
    api_server = Column(String(255), nullable=False)
    token = Column(String(2048), nullable=False)
    image_pull_username = Column(String(255))
    image_pull_password = Column(String(255))
    private_registry = Column(String(255))
    created_by = Column(String(36))
    created_time = Column(DateTime)
    updated_by = Column(String(36))
    updated_time = Column(DateTime)