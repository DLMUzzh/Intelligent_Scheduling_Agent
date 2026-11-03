from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def build_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() != 'sqlite':
        raise ValueError('本版本仅支持 SQLite')
    if parsed.database and parsed.database != ':memory:':
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    options = {'poolclass': StaticPool} if parsed.database in (None, '', ':memory:') else {}
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 20}, **options)

    @event.listens_for(engine, 'connect')
    def configure_sqlite(connection, _record):
        # Explicit transactions work consistently on Python 3.11+.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=20000')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()

    @event.listens_for(engine, 'begin')
    def begin_transaction(connection):
        mode = 'IMMEDIATE' if connection.get_execution_options().get('write_transaction') else 'DEFERRED'
        connection.exec_driver_sql(f'BEGIN {mode}')

    return engine


engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker, write: bool = False) -> Iterator[Session]:
    with factory() as session:
        # Acquire SQLite's write reservation BEFORE reading versions / occupancy.
        if write:
            session.connection(execution_options={'write_transaction': True})
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
