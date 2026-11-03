import sqlite3
from contextlib import closing
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateTable

from app.core.config import ROOT
from app.models.foundation import SchemaMigration

INITIAL_REVISION = '0001_foundation'
SCHEMA_FILE = ROOT / 'migrations/versions/0001_foundation.sql'


def structure(connection) -> dict:
    """Read table, column and index facts without modifying application data."""
    result = {}
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    for name, sql in rows.fetchall():
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [tuple(row) for row in connection.execute(f'PRAGMA table_info({quoted})')]
        indexes = []
        for index in connection.execute(f'PRAGMA index_list({quoted})').fetchall():
            index_name = index[1].replace('"', '""')
            fields = tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index_name}")'))
            index_sql = connection.execute(
                'SELECT sql FROM sqlite_master WHERE name=?', (index[1],)
            ).fetchone()[0]
            indexes.append((index[2], fields, index[4], index_sql))
        result[name] = (columns, sorted(indexes, key=str), sql)
    return result


def validate_initial_structure(connection: Connection) -> None:
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(SCHEMA_FILE.read_text(encoding='utf-8'))
        expected = structure(reference)
    actual = structure(connection.connection.driver_connection)
    if actual.keys() != expected.keys():
        raise RuntimeError('数据库表集合与已审核新版结构不符，拒绝自动迁移')
    for name in actual:
        actual_columns, actual_indexes, actual_sql = actual[name]
        expected_columns, expected_indexes, expected_sql = expected[name]
        # ORM-created Alembic version table has equivalent SQL formatting.
        if name == 'schema_migrations':
            actual_columns = [
                tuple(row[:3]) + (0 if row[1] == 'id' else row[3],) + tuple(row[4:]) for row in actual_columns
            ]
            orm_sql = str(CreateTable(SchemaMigration.__table__).compile(dialect=connection.dialect))
            if ''.join(actual_sql.split()) == ''.join(orm_sql.split()):
                actual_sql = expected_sql
        if (actual_columns, actual_indexes, ''.join(actual_sql.split())) != (
            expected_columns,
            expected_indexes,
            ''.join(expected_sql.split()),
        ):
            raise RuntimeError(f'新版表结构校验失败 {name}')
        if connection.exec_driver_sql(f'PRAGMA foreign_key_list("{name}")').fetchall():
            raise RuntimeError('新版数据库包含物理外键，拒绝启动')


def initialize_database(
    engine: Engine, target: str = 'head', migration_directory: Path | None = None
) -> None:
    with engine.connect().execution_options(write_transaction=True) as connection:
        with connection.begin():
            unversioned = False
            version = tuple(
                map(int, connection.exec_driver_sql('SELECT sqlite_version()').scalar_one().split('.'))
            )
            if version < (3, 38):
                raise RuntimeError('需要 SQLite 3.38+、STRICT 和 JSON 函数')
            connection.exec_driver_sql("SELECT json_valid('{}')").scalar_one()
            tables = set(
                connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).scalars()
            )
            if tables:
                if 'schema_migrations' not in tables:
                    raise RuntimeError('检测到旧库或未识别结构，拒绝迁移')
                current = (
                    connection.exec_driver_sql('SELECT version_num FROM schema_migrations').scalars().all()
                )
                if not current or current == [INITIAL_REVISION]:
                    validate_initial_structure(connection)
                unversioned = not current
            config = Config(str(ROOT / 'alembic.ini'))
            if migration_directory is not None:
                config.set_main_option('script_location', str(migration_directory))
            config.attributes['connection'] = connection
            if unversioned:
                command.stamp(config, INITIAL_REVISION)
            command.upgrade(config, target)
            current = connection.exec_driver_sql('SELECT version_num FROM schema_migrations').scalars().all()
            if current == [INITIAL_REVISION]:
                validate_initial_structure(connection)
            for name in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).scalars():
                quoted = name.replace('"', '""')
                if connection.exec_driver_sql(f'PRAGMA foreign_key_list("{quoted}")').fetchall():
                    raise RuntimeError('迁移产生了物理外键，已回滚')
            if (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM business_state WHERE state_key='MAIN'"
                ).scalar_one()
                != 1
            ):
                raise RuntimeError('业务修订元数据缺失，拒绝启动')


if __name__ == '__main__':
    from app.core.runtime import runtime_settings
    from app.database.foundation import build_engine

    database_engine = build_engine(runtime_settings)
    try:
        initialize_database(database_engine)
        print('SQLite 迁移完成')
    finally:
        database_engine.dispose()
