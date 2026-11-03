import shutil
import sqlite3

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.core.config import ROOT
from app.core.runtime import RuntimeSettings
from app.database.foundation import build_engine
from app.database.migrate import INITIAL_REVISION, initialize_database
from app.models.foundation import FoundationBase


@pytest.fixture
def database_engine(tmp_path):
    config = RuntimeSettings(database_url=f'sqlite:///{(tmp_path / "foundation.db").as_posix()}')
    engine = build_engine(config)
    yield engine
    engine.dispose()


def test_initialize_repeat_preserves_data_and_schema(database_engine):
    initialize_database(database_engine)
    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO collection_categories(task_mode,name) VALUES ('TAG','测试保留')"
        )
    initialize_database(database_engine)
    with database_engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT name FROM collection_categories').scalar_one() == '测试保留'
        assert connection.exec_driver_sql('SELECT revision FROM business_state').scalar_one() == 1
        assert (
            connection.exec_driver_sql('SELECT version_num FROM schema_migrations').scalar_one()
            == INITIAL_REVISION
        )
        assert len(inspect(connection).get_table_names()) == 13
        assert connection.exec_driver_sql('PRAGMA journal_mode').scalar_one() == 'delete'
        assert connection.exec_driver_sql('PRAGMA synchronous').scalar_one() == 2
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        tables = connection.exec_driver_sql(
            "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).all()
        assert sum(len(inspect(connection).get_columns(name)) for name, _ in tables) == 137
        for name, sql in tables:
            assert sql.rstrip().endswith('STRICT')
            assert 'AUTOINCREMENT' in sql
            assert not inspect(connection).get_foreign_keys(name)
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'"
            ).scalar_one()
            == 12
        )
    assert all(not table.foreign_keys for table in FoundationBase.metadata.tables.values())


def test_initialization_empty_business(database_engine):
    initialize_database(database_engine)
    with database_engine.connect() as connection:
        for name in inspect(connection).get_table_names():
            expected = 1 if name in ('business_state', 'schema_migrations') else 0
            assert connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one() == expected


def test_reject_legacy_without_mutation(database_engine):
    with database_engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE old_business(id INTEGER PRIMARY KEY, value TEXT)')
        connection.exec_driver_sql("INSERT INTO old_business VALUES (1,'保留')")
    with pytest.raises(RuntimeError, match='旧库'):
        initialize_database(database_engine)
    with database_engine.connect() as connection:
        assert inspect(connection).get_table_names() == ['old_business']
        assert connection.exec_driver_sql('SELECT value FROM old_business').scalar_one() == '保留'


def test_refuse_original_database_path():
    config = RuntimeSettings(database_url=f'sqlite:///{(ROOT / "data/scheduling.db").as_posix()}')
    with pytest.raises(ValueError, match='旧数据库'):
        build_engine(config)


def test_drift_rejected_without_clearing_data(database_engine):
    initialize_database(database_engine)
    with database_engine.begin() as connection:
        connection.exec_driver_sql('DROP INDEX ix_audit_logs_operation_id')
    with pytest.raises(RuntimeError, match='结构校验失败'):
        initialize_database(database_engine)


def test_unversioned_approved_schema_gets_real_revision(database_engine):
    raw = sqlite3.connect(database_engine.url.database)
    raw.executescript((ROOT / 'scripts/sql/schema.sql').read_text(encoding='utf-8'))
    raw.execute("INSERT INTO drivers(name) VALUES ('现有记录')")
    raw.commit()
    raw.close()
    initialize_database(database_engine)
    with database_engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT name FROM drivers').scalar_one() == '现有记录'
        assert (
            connection.exec_driver_sql('SELECT version_num FROM schema_migrations').scalar_one()
            == INITIAL_REVISION
        )


def test_upgrade_failure_rolls_back_schema_data_and_revision(database_engine, tmp_path):
    initialize_database(database_engine)
    migration_directory = tmp_path / 'migrations'
    shutil.copytree(ROOT / 'migrations', migration_directory)
    upgrade = migration_directory / 'versions/0002_exercise.py'
    upgrade.write_text(
        """from alembic import op
revision = '0002_exercise'
down_revision = '0001_foundation'
def upgrade():
    op.get_bind().exec_driver_sql('ALTER TABLE drivers ADD COLUMN exercise TEXT')
    op.get_bind().exec_driver_sql("INSERT INTO drivers(name) VALUES ('must rollback')")
    raise RuntimeError('migration exercise')
""",
        encoding='utf-8',
    )
    with pytest.raises(RuntimeError, match='migration exercise'):
        initialize_database(database_engine, migration_directory=migration_directory)
    with database_engine.connect() as connection:
        assert 'exercise' not in {c['name'] for c in inspect(connection).get_columns('drivers')}
        assert connection.exec_driver_sql('SELECT count(*) FROM drivers').scalar_one() == 0
        assert (
            connection.exec_driver_sql('SELECT version_num FROM schema_migrations').scalar_one()
            == INITIAL_REVISION
        )
    upgrade.write_text(
        upgrade.read_text(encoding='utf-8').replace("    raise RuntimeError('migration exercise')", ''),
        encoding='utf-8',
    )
    initialize_database(database_engine, migration_directory=migration_directory)
    initialize_database(database_engine, migration_directory=migration_directory)
    with database_engine.connect() as connection:
        assert (
            connection.exec_driver_sql('SELECT version_num FROM schema_migrations').scalar_one()
            == '0002_exercise'
        )
        assert connection.exec_driver_sql('SELECT count(*) FROM drivers').scalar_one() == 1


@pytest.mark.parametrize(
    'sql',
    [
        "INSERT INTO drivers(name,efficiency_level) VALUES ('invalid','OTHER')",
        "INSERT INTO drivers(name,is_enabled) VALUES ('invalid',2)",
        "INSERT INTO drivers(name,is_enabled) VALUES ('invalid',1.5)",
        "INSERT INTO vehicles(plate_number,plate_key) VALUES ('TEST','TEST')",
        "INSERT INTO collection_plans(name,start_date,end_date) VALUES ('invalid','2026-02-30','2026-03-01')",
        "INSERT INTO collection_plans(name,start_date,end_date) VALUES ('invalid','2026-03-01','2026-02-28')",
        "INSERT INTO daily_demands(plan_day_id,collection_category_id,category_name_snapshot,task_mode,target_tag_count,sort_order) VALUES (1,1,'invalid','TAG',0,1)",
        "INSERT INTO resource_unavailability(driver_id,vehicle_id,start_date,end_date) VALUES (1,1,'2026-11-04','2026-11-05')",
    ],
)
def test_storage_constraints_reject_invalid_data(database_engine, sql):
    initialize_database(database_engine)
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.exec_driver_sql(sql)


def test_business_unique_constraint_and_autoincrement(database_engine):
    initialize_database(database_engine)
    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO collection_categories(task_mode,name) VALUES ('TAG','unique')"
        )
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO collection_categories(task_mode,name) VALUES ('TAG','unique')"
        )
    with database_engine.begin() as connection:
        connection.exec_driver_sql('DELETE FROM collection_categories WHERE id=1')
        connection.exec_driver_sql("INSERT INTO collection_categories(task_mode,name) VALUES ('TAG','next')")
        assert connection.exec_driver_sql('SELECT id FROM collection_categories').scalar_one() == 2


def test_ephemeral_runtime_database_rejected():
    with pytest.raises(ValueError, match='持久保存'):
        build_engine(RuntimeSettings(database_url='sqlite:///:memory:'))
