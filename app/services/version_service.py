from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.responses import ApiError
from app.core.time import utc_timestamp
from app.models.foundation import BusinessState, FoundationBase
from app.schemas.operations import VERSION_TABLES, ExpectedVersions


def revision(db: Session) -> str:
    value = db.scalar(select(BusinessState.revision).where(BusinessState.state_key == 'MAIN'))
    if value is None:
        raise ApiError('DATA_INTEGRITY_ERROR', '业务修订元数据缺失')
    return str(value)


def check_versions(db: Session, expected: ExpectedVersions) -> None:
    if revision(db) != expected.business_revision:
        raise ApiError('VERSION_CONFLICT', '数据已变化，请刷新后重新准备操作')
    for name in VERSION_TABLES:
        table = FoundationBase.metadata.tables[name]
        items = getattr(expected, name)
        if not items:
            continue
        rows = {
            str(row['id']): row
            for row in db.execute(
                select(table).where(table.c.id.in_([int(item.id) for item in items]))
            ).mappings()
        }
        for item in items:
            row = rows.get(item.id)
            if row is None or str(row['version']) != item.version:
                raise ApiError('VERSION_CONFLICT', '对象已变化或已删除，请刷新后重新准备操作')
            if name == 'plan_days' and str(row['formal_version']) != item.formal_version:
                raise ApiError('VERSION_CONFLICT', '正式版本已变化，请刷新后重新准备操作')


def advance_revision(db: Session, expected: str) -> str:
    result = db.execute(
        update(BusinessState)
        .where(
            BusinessState.state_key == 'MAIN',
            BusinessState.revision == int(expected),
        )
        .values(revision=BusinessState.revision + 1, updated_at=utc_timestamp())
    )
    if result.rowcount != 1:
        raise ApiError('VERSION_CONFLICT', '业务版本冲突，请刷新后重新准备操作')
    return str(int(expected) + 1)


def advance_object_version(db: Session, table_name: str, object_id: int, expected_version: int) -> int:
    if table_name not in VERSION_TABLES:
        raise ApiError('DATA_INTEGRITY_ERROR', '对象不支持版本更新')
    table = FoundationBase.metadata.tables[table_name]
    db.flush()
    result = db.execute(
        update(table)
        .where(table.c.id == object_id, table.c.version == expected_version)
        .values(version=table.c.version + 1, updated_at=utc_timestamp())
    )
    if result.rowcount != 1:
        raise ApiError('VERSION_CONFLICT', '对象版本冲突，请刷新后重新准备操作')
    return expected_version + 1
