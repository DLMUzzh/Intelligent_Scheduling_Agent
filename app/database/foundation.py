import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import ROOT
from app.core.runtime import RuntimeSettings


class CommitUncertain(Exception):
    """A failed commit acknowledgement requires a fresh-session status lookup."""


def build_engine(config: RuntimeSettings) -> Engine:
    url = make_url(config.database_url)
    if url.get_backend_name() != 'sqlite':
        raise ValueError('新版仅支持 SQLite')
    if url.database in (None, '', ':memory:'):
        raise ValueError('运行库必须使用本机 SQLite 文件，以持久保存操作结果')
    path = Path(url.database)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if path == (ROOT / 'data/scheduling.db').resolve():
        raise ValueError('新版数据库路径不能指向旧数据库')
    if path.is_file() and path.stat().st_size:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as existing:
            tables = {
                row[0]
                for row in existing.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables and 'schema_migrations' not in tables:
                raise ValueError('数据库不是已审核新版结构，拒绝更改连接配置')
    path.parent.mkdir(parents=True, exist_ok=True)
    url = url.set(database=path.as_posix())
    engine = create_engine(
        url,
        connect_args={
            'check_same_thread': False,
            'timeout': config.busy_timeout_ms / 1000,
        },
        hide_parameters=True,
    )

    @event.listens_for(engine, 'connect')
    def configure(connection, _record):
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute(f'PRAGMA busy_timeout={config.busy_timeout_ms}')
        cursor.execute('PRAGMA journal_mode=DELETE')
        cursor.execute('PRAGMA synchronous=FULL')
        cursor.close()

    @event.listens_for(engine, 'begin')
    def begin(connection):
        mode = 'IMMEDIATE' if connection.get_execution_options().get('write_transaction') else 'DEFERRED'
        connection.exec_driver_sql(f'BEGIN {mode}')

    return engine


@contextmanager
def transaction(factory: sessionmaker, write: bool = False) -> Iterator[Session]:
    with factory() as session:
        try:
            if write:
                session.connection(execution_options={'write_transaction': True})
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise
        try:
            session.commit()
        except Exception as exc:
            raise CommitUncertain from exc
