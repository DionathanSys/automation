from __future__ import annotations

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

from automation.config import settings


def create_mysql_engine() -> Engine:
    url = URL.create(
        "mysql+mysqlconnector",
        username=settings.mysql.user,
        password=settings.mysql.password,
        host=settings.mysql.host,
        port=settings.mysql.port,
        database=settings.mysql.database,
    )
    return create_engine(url, pool_pre_ping=True)
