from collections import defaultdict

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.time import business_date
from app.database.foundation import transaction
from app.models.foundation import PlanDay, ResourceUnavailability, TaskPackage
from app.repositories.base_data import MODELS, page_rows, require, view
from app.services.confirmation_service import OperationReply
from app.services.version_service import revision


class BaseDataQueries:
    def __init__(self, factory):
        self.factory = factory

    def list_records(self, target_type: str, filters) -> OperationReply:
        model = MODELS[target_type]
        with transaction(self.factory) as db:
            conditions = []
            work_date = getattr(filters, 'work_date', None) or business_date().isoformat()
            if hasattr(filters, 'q') and filters.q is not None:
                fields = [model.name, cast(model.id, String)]
                if target_type == 'VEHICLE':
                    fields.append(model.plate_number)
                conditions.append(
                    or_(*(field.contains(filters.q.strip(), autoescape=True) for field in fields))
                )
            for field in ('task_mode', 'efficiency_level', 'is_enabled', 'driver_id', 'vehicle_id'):
                value = getattr(filters, field, None)
                if value is not None:
                    conditions.append(
                        getattr(model, field)
                        == (int(value) if field.endswith('_id') or field == 'is_enabled' else value)
                    )
            if target_type in ('DRIVER', 'VEHICLE') and filters.is_available is not None:
                off_field = getattr(ResourceUnavailability, f'{target_type.lower()}_id')
                blocked = exists(
                    select(ResourceUnavailability.id).where(
                        off_field == model.id,
                        ResourceUnavailability.start_date <= work_date,
                        ResourceUnavailability.end_date >= work_date,
                    )
                )
                available = (model.is_enabled == 1) & ~blocked
                conditions.append(available if filters.is_available == '1' else ~available)
            if target_type == 'UNAVAILABILITY' and filters.start_date is not None:
                conditions.extend(
                    [model.start_date <= filters.end_date, model.end_date >= filters.start_date]
                )
            ordering = (model.id,)
            if target_type == 'CATEGORY':
                ordering = (model.task_mode, model.id)
            elif target_type == 'UNAVAILABILITY':
                ordering = (model.start_date, model.id)
            rows, total = page_rows(
                db, model, conditions, ordering, int(filters.page), int(filters.page_size)
            )
            data = [view(row, target_type) for row in rows]
            if target_type in ('DRIVER', 'VEHICLE'):
                data = self._resource_views(db, rows, target_type, work_date)
            return OperationReply(
                {
                    'items': data,
                    'page': int(filters.page),
                    'page_size': int(filters.page_size),
                    'total': str(total),
                },
                revision(db),
            )

    def detail(self, target_type: str, object_id: int, work_date: str | None = None) -> OperationReply:
        with transaction(self.factory) as db:
            row = require(db, target_type, object_id)
            data = view(row, target_type)
            if target_type in ('DRIVER', 'VEHICLE'):
                data = self._resource_views(db, [row], target_type, work_date or business_date().isoformat())[
                    0
                ]
            return OperationReply(data, revision(db))

    @staticmethod
    def _resource_views(db: Session, rows: list, target_type: str, work_date: str) -> list[dict]:
        ids = [row.id for row in rows]
        if not ids:
            return []
        field = f'{target_type.lower()}_id'
        unavailable = defaultdict(list)
        for record in db.scalars(
            select(ResourceUnavailability)
            .where(
                getattr(ResourceUnavailability, field).in_(ids),
                ResourceUnavailability.start_date <= work_date,
                ResourceUnavailability.end_date >= work_date,
            )
            .order_by(ResourceUnavailability.id)
        ):
            unavailable[getattr(record, field)].append(str(record.id))
        counts = dict(
            db.execute(
                select(getattr(TaskPackage, field), func.count())
                .join(PlanDay, PlanDay.id == TaskPackage.plan_day_id)
                .where(
                    getattr(TaskPackage, field).in_(ids),
                    TaskPackage.schedule_kind == 'FORMAL',
                    PlanDay.formal_status == 'ACTIVE',
                )
                .group_by(getattr(TaskPackage, field))
            ).all()
        )
        return [
            view(row, target_type)
            | {
                'work_date': work_date,
                'is_available': int(bool(row.is_enabled) and not unavailable[row.id]),
                'unavailability_ids': unavailable[row.id],
                'scheduled_shift_count': str(counts.get(row.id, 0)),
            }
            for row in rows
        ]
