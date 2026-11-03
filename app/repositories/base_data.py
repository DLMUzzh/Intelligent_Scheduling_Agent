from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.responses import ApiError
from app.models.foundation import CollectionCategory, Driver, ResourceUnavailability, Vehicle
from app.schemas.base_data import CAPACITIES

MODELS = {
    'CATEGORY': CollectionCategory,
    'DRIVER': Driver,
    'VEHICLE': Vehicle,
    'UNAVAILABILITY': ResourceUnavailability,
}
STATE_FIELDS = {
    'CATEGORY': ('task_mode', 'name'),
    'DRIVER': ('name', 'phone', 'efficiency_level', 'is_enabled', 'can_morning', 'can_middle', 'can_evening'),
    'VEHICLE': ('plate_number', 'name', 'notes', 'is_enabled', *CAPACITIES),
    'UNAVAILABILITY': ('driver_id', 'vehicle_id', 'start_date', 'end_date', 'reason'),
}


def require(db: Session, target_type: str, object_id: str | int, *, referenced: bool = False):
    row = db.get(MODELS[target_type], int(object_id))
    if row is None:
        raise ApiError('REFERENCED_OBJECT_NOT_FOUND' if referenced else 'NOT_FOUND', '资料不存在，请刷新列表')
    return row


def state(row, target_type: str) -> dict:
    data = {'id': str(row.id)}
    for field in STATE_FIELDS[target_type]:
        value = getattr(row, field)
        data[field] = (
            str(value) if value is not None and (field.endswith('_id') or field in CAPACITIES) else value
        )
    return data


def view(row, target_type: str) -> dict:
    return state(row, target_type) | {
        'version': str(row.version),
        'created_at': row.created_at,
        'updated_at': row.updated_at,
    }


def page_rows(
    db: Session, model, conditions: list, ordering: tuple, page: int, page_size: int
) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(model).where(*conditions))
    offset = (page - 1) * page_size
    rows = []
    if offset < total:
        rows = list(
            db.scalars(select(model).where(*conditions).order_by(*ordering).offset(offset).limit(page_size))
        )
    return rows, total
