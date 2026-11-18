from os import environ

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url():
    url = environ["CAMPUSFLOW_DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Use a postgresql+psycopg:// connection URL")
    return url


def session_factory():
    return sessionmaker(create_engine(database_url(), pool_pre_ping=True), expire_on_commit=False)
