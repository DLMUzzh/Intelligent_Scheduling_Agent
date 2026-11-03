from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.responses import ApiError
from app.models.foundation import ResourceUnavailability
from app.repositories.base_data import MODELS, STATE_FIELDS, require, state
from app.schemas.base_data import CAPACITIES, PAYLOAD_MODELS, Patch, VehicleCreate
from app.schemas.operations import ExecutionResult, ObjectVersion, PrepareInput, Summary
from app.services.base_data_effects import (
    apply_related,
    check_future_formal,
    check_references,
    enrich_versions,
    field_changes,
    related_changes,
)
from app.services.confirmation_service import ActionExecution, PreparedAction, check_dates
from app.services.version_service import advance_object_version

TABLES = {key: model.__tablename__ for key, model in MODELS.items()}
TITLES = {'CATEGORY': '采集类别', 'DRIVER': '司机', 'VEHICLE': '车辆', 'UNAVAILABILITY': '不可用记录'}
VERBS = {'CREATE': '新增', 'UPDATE': '修改', 'DELETE': '删除'}


def plate_key(value: str) -> str:
    return ''.join(value.split()).upper()


def interval_dates(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


def add_dependency(expected, table: str, row, *, required: bool = False) -> None:
    items = getattr(expected, table)
    if str(row.id) in {item.id for item in items}:
        return
    if required:
        raise ApiError(
            'VALIDATION_ERROR',
            '不可用操作须提供所属资源的版本依据',
            [
                {
                    'code': 'VALIDATION_ERROR',
                    'message': '缺少所属资源版本',
                    'field': f'expected_versions_json.{table}',
                }
            ],
        )
    items.append(ObjectVersion(id=str(row.id), version=str(row.version)))


class BaseDataAdapter:
    """The twelve approved single-record actions. Shared service owns commit and audit."""

    def __init__(self, action_code: str):
        self.action_code = action_code
        self.verb, self.target_type = action_code.split('_', 1)

    def validate_payload(self, payload: dict) -> dict:
        model = PAYLOAD_MODELS[self.action_code].model_validate(payload)
        return model.model_dump(exclude_unset=isinstance(model, Patch))

    def prepare(self, db: Session, request: PrepareInput) -> PreparedAction:
        target_type = self.target_type
        row = require(db, target_type, request.target_id) if request.target_id else None
        before = state(row, target_type) if row else None
        after = None if self.verb == 'DELETE' else (before or {'id': None}) | request.payload
        expected = request.expected_versions_json.model_copy(deep=True)
        changes = field_changes(before, after)
        related, affected_dates = [], []
        resource_type, resource_id = target_type, request.target_id
        unavailable_rows = {
            item.id: item
            for item in db.scalars(select(ResourceUnavailability).order_by(ResourceUnavailability.id))
        }
        all_unavailable = [state(item, 'UNAVAILABILITY') for item in unavailable_rows.values()]
        cleanup = []

        if target_type == 'CATEGORY':
            if after is not None:
                duplicate = db.scalar(
                    select(MODELS['CATEGORY'].id)
                    .where(
                        MODELS['CATEGORY'].task_mode == after['task_mode'],
                        MODELS['CATEGORY'].name == after['name'],
                        MODELS['CATEGORY'].id != (row.id if row else 0),
                    )
                    .limit(1)
                )
                if duplicate:
                    raise ApiError('DUPLICATE_CATEGORY', '同模式下已有同名采集类别')
            if self.verb == 'UPDATE':
                related = related_changes(db, category=after)
            if self.verb == 'DELETE':
                check_references(db, target_type, row.id)
        else:
            resource_after = after
            if target_type == 'UNAVAILABILITY':
                reference = after or before
                resource_type = 'DRIVER' if reference['driver_id'] is not None else 'VEHICLE'
                resource_id = reference[f'{resource_type.lower()}_id']
                resource = require(db, resource_type, resource_id, referenced=True)
                resource_after = state(resource, resource_type)
                add_dependency(expected, TABLES[resource_type], resource, required=True)
                intervals = [value for value in (before, after) if value is not None]
                for value in intervals:
                    check_dates([value['start_date'], value['end_date']])
                affected_dates = sorted(
                    {
                        day
                        for value in intervals
                        for day in interval_dates(value['start_date'], value['end_date'])
                    }
                )
                all_unavailable = [value for value in all_unavailable if value['id'] != request.target_id]
                if after is not None:
                    all_unavailable.append(after)
            if self.verb == 'DELETE' and target_type != 'UNAVAILABILITY':
                check_references(db, target_type, row.id)
                cleanup = [
                    value
                    for value in all_unavailable
                    if value[f'{target_type.lower()}_id'] == request.target_id
                ]
                all_unavailable = [value for value in all_unavailable if value not in cleanup]
                if cleanup:
                    changes.append(
                        {
                            'field': 'resource_unavailability',
                            'label': '关联不可用记录清理',
                            'before': cleanup,
                            'after': [],
                        }
                    )
                    for value in cleanup:
                        add_dependency(
                            expected, 'resource_unavailability', unavailable_rows[int(value['id'])]
                        )
            if resource_type == 'VEHICLE' and target_type == 'VEHICLE' and after is not None:
                VehicleCreate.model_validate({field: after[field] for field in STATE_FIELDS['VEHICLE']})
                key = plate_key(after['plate_number'])
                if not key:
                    raise ApiError('VALIDATION_ERROR', '车牌号不能全为空白')
                duplicate = db.scalar(
                    select(MODELS['VEHICLE'].id)
                    .where(MODELS['VEHICLE'].plate_key == key, MODELS['VEHICLE'].id != (row.id if row else 0))
                    .limit(1)
                )
                if duplicate:
                    raise ApiError('DUPLICATE_PLATE', '归一化后的车牌号已存在')
            if resource_id is not None:
                blocked = [
                    value for value in all_unavailable if value[f'{resource_type.lower()}_id'] == resource_id
                ]
                check_future_formal(db, resource_type, int(resource_id), resource_after, blocked)
            vehicles = None
            if resource_type == 'VEHICLE':
                vehicle_rows = list(db.scalars(select(MODELS['VEHICLE']).order_by(MODELS['VEHICLE'].id)))
                vehicles = [state(value, 'VEHICLE') for value in vehicle_rows]
                for value in vehicle_rows:
                    add_dependency(expected, 'vehicles', value)
                if target_type == 'VEHICLE':
                    vehicles = [value for value in vehicles if value['id'] != request.target_id]
                    if after is not None:
                        vehicles.append(after)
                    vehicles.sort(key=lambda value: int(value['id']) if value['id'] is not None else 2**63)
            for value in all_unavailable:
                if value['id'] is not None:
                    add_dependency(expected, 'resource_unavailability', unavailable_rows[int(value['id'])])
            related = related_changes(
                db,
                vehicles=vehicles,
                unavailable=all_unavailable,
                mark_drafts=True,
                draft_dates=set(affected_dates) if target_type == 'UNAVAILABILITY' else None,
            )
        affected_dates = sorted(set(affected_dates) | {value['work_date'] for value in related})
        expected = enrich_versions(db, expected, related)
        label = (
            (after or before).get('name') or (after or before).get('plate_number') or request.target_id or ''
        )
        summary = Summary(
            action_code=request.action_code,
            target_type=target_type,
            target_id=request.target_id,
            title=f'{VERBS[self.verb]}{TITLES[target_type]} {label}'.strip(),
            before=before,
            after=after,
            changes=changes,
            related_changes=related,
            affected_dates=affected_dates,
        )
        return PreparedAction(
            resolved={
                'verb': self.verb,
                'target_type': target_type,
                'target_id': request.target_id,
                'after': after,
                'related': related,
                'affected_dates': affected_dates,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'cleanup': cleanup,
                'changes': changes,
                'next_revision': int(expected.business_revision) + 1,
            },
            summary=summary,
            expected_versions=expected,
        )

    def execute(self, db: Session, resolved: dict) -> ActionExecution:
        target_type, target_id = resolved['target_type'], resolved['target_id']
        verb, after = resolved['verb'], resolved['after']
        row = require(db, target_type, target_id) if target_id else None
        if verb == 'DELETE':
            if target_type in ('DRIVER', 'VEHICLE'):
                field = getattr(ResourceUnavailability, f'{target_type.lower()}_id')
                db.execute(delete(ResourceUnavailability).where(field == int(target_id)))
            db.delete(row)
        else:
            values = {field: after[field] for field in STATE_FIELDS[target_type]}
            for field in (*CAPACITIES, 'driver_id', 'vehicle_id'):
                if field in values and values[field] is not None:
                    values[field] = int(values[field])
            if target_type == 'VEHICLE':
                values['plate_key'] = plate_key(values['plate_number'])
            if row is None:
                row = MODELS[target_type](**values)
                db.add(row)
                db.flush()
                target_id = str(row.id)
            else:
                for field, value in values.items():
                    setattr(row, field, value)
                advance_object_version(db, TABLES[target_type], row.id, row.version)
        if target_type == 'UNAVAILABILITY':
            resource = require(db, resolved['resource_type'], resolved['resource_id'])
            advance_object_version(db, TABLES[resolved['resource_type']], resource.id, resource.version)
        created_vehicle_id = int(target_id) if target_type == 'VEHICLE' and verb == 'CREATE' else None
        revisions, audit_related = apply_related(
            db, resolved['related'], resolved['next_revision'], created_vehicle_id
        )
        db.flush()
        return ActionExecution(
            ExecutionResult(
                code='EXECUTED',
                target_type=target_type,
                target_id=target_id,
                resource_ids=([resolved['resource_id']] if target_type == 'UNAVAILABILITY' else [target_id]),
                affected_dates=resolved['affected_dates'],
                plan_day_ids=[value.plan_day_id for value in revisions],
                revisions=revisions,
            ),
            after=None if verb == 'DELETE' else state(row, target_type),
            audit_changes=resolved['changes'] + audit_related,
        )


def base_data_adapters() -> dict[str, BaseDataAdapter]:
    return {action: BaseDataAdapter(action) for action in PAYLOAD_MODELS}
