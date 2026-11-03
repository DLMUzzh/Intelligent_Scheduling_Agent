from alembic import context
from alembic.ddl.sqlite import SQLiteImpl

from app.models.foundation import FoundationBase, SchemaMigration


class FoundationSQLiteImpl(SQLiteImpl):
    __dialect__ = 'sqlite'
    transactional_ddl = True

    def version_table_impl(self, **_kwargs):
        return SchemaMigration.__table__


connection = context.config.attributes.get('connection')
if connection is None:
    raise RuntimeError('请使用 python -m app.database.migrate 执行经过路径及结构检查的迁移')

context.configure(
    connection=connection,
    target_metadata=FoundationBase.metadata,
    version_table='schema_migrations',
    transactional_ddl=True,
)
with context.begin_transaction():
    context.run_migrations()
