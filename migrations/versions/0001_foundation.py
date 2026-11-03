"""Approved 13-table initial schema, without business seed data."""

import sqlite3
from pathlib import Path

from alembic import op

revision = '0001_foundation'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    source = Path(__file__).with_suffix('.sql').read_text(encoding='utf-8')
    statement = ''
    for line in source.splitlines():
        if line.lstrip().startswith('--'):
            continue
        statement += line + '\n'
        if not sqlite3.complete_statement(statement):
            continue
        sql = statement.strip()
        statement = ''
        if sql.startswith(('PRAGMA ', 'BEGIN ', 'COMMIT', 'CREATE TABLE schema_migrations')):
            continue
        op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    raise RuntimeError('初始版本不支持删除数据式降级，请通过已验证备份恢复')
