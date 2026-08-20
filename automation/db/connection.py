from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from automation.config import settings


def create_mysql_engine() -> Engine:
    return create_engine(settings.mysql.sqlalchemy_url, pool_pre_ping=True)
