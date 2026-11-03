import json
from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.responses import ApiError
from app.core.time import business_date, utc_timestamp
from app.models.foundation import (
    AuditLog,
    CollectionPlan,
    DailyDemand,
    PlanDay,
    TaskAllocation,
    TaskPackage,
)
from app.schemas.base_data import SHIFTS
from app.schemas.operations import DayRevision, DayVersion, ObjectVersion
from app.schemas.resource_snapshots import (
    DraftMetadata,
    FormalChanges,
    category_ids,
    parse_capacities,
    parse_snapshot,
    public_capacity,
)
from app.services.confirmation_service import canonical
from app.services.version_service import advance_object_version


def field_changes(before: dict | None, after: dict | None) -> list[dict]:
    first, last = before or {}, after or {}
    return [
        {'field': field, 'label': field, 'before': first.get(field), 'after': last.get(field)}
        for field in sorted(first.keys() | last.keys())
        if field != 'id' and (first.get(field) != last.get(field) or before is None or after is None)
    ]


def check_references(db: Session, target_type: str, target_id: int) -> None:
    if target_type == 'CATEGORY':
        direct = db.scalar(
            select(DailyDemand.id).where(DailyDemand.collection_category_id == target_id).limit(1)
        )
        allocated = db.scalar(
            select(TaskAllocation.id).where(TaskAllocation.collection_category_id == target_id).limit(1)
        )
        if direct or allocated:
            raise ApiError('RESOURCE_REFERENCED', '类别已有需求或任务引用，不能删除')
        for raw in db.scalars(
            select(PlanDay.draft_metadata_json).where(PlanDay.draft_metadata_json.is_not(None))
        ):
            metadata = parse_snapshot(DraftMetadata, raw)
            if target_id in category_ids(metadata.validation_basis) or any(
                item.collection_category_id == target_id for item in metadata.shortage_reasons
            ):
                raise ApiError('RESOURCE_REFERENCED', '类别已有草稿依据引用，不能删除')
    else:
        field = TaskPackage.driver_id if target_type == 'DRIVER' else TaskPackage.vehicle_id
        if db.scalar(select(TaskPackage.id).where(field == target_id).limit(1)):
            raise ApiError('RESOURCE_REFERENCED', '资料已有草稿或正式任务引用，不能删除')
    # Every formal event is checked, including cancelled/replaced arrangements and both sides.
    for event in db.scalars(
        select(AuditLog).where(AuditLog.formal_version.is_not(None)).order_by(AuditLog.id)
    ):
        if event.snapshot_schema_version != 1:
            raise ApiError('DATA_INTEGRITY_ERROR', '正式历史版本尚不支持')
        changes = parse_snapshot(FormalChanges, event.changes_json)
        for snapshot in (changes.before, changes.after):
            if snapshot is None:
                continue
            if target_type == 'CATEGORY':
                referenced = any(
                    item.collection_category_id == target_id for item in snapshot.demands
                ) or any(
                    item.collection_category_id == target_id
                    for pack in snapshot.packages
                    for item in pack.allocations
                )
            else:
                field = 'driver_id' if target_type == 'DRIVER' else 'vehicle_id'
                referenced = any(getattr(pack, field) == target_id for pack in snapshot.packages)
            if referenced:
                raise ApiError('RESOURCE_REFERENCED', '资料存在正式任务历史，不能删除')


def check_future_formal(
    db: Session, target_type: str, target_id: int, after: dict | None, unavailable: list[dict]
) -> None:
    if after is None:
        return
    field = TaskPackage.driver_id if target_type == 'DRIVER' else TaskPackage.vehicle_id
    packages = list(
        db.scalars(
            select(TaskPackage)
            .join(PlanDay, PlanDay.id == TaskPackage.plan_day_id)
            .where(
                field == target_id,
                TaskPackage.schedule_kind == 'FORMAL',
                PlanDay.formal_status == 'ACTIVE',
                TaskPackage.work_date > business_date().isoformat(),
            )
            .order_by(TaskPackage.work_date, TaskPackage.id)
        )
    )
    amounts = defaultdict(int)
    if target_type == 'VEHICLE' and packages:
        for allocation in db.scalars(
            select(TaskAllocation).where(TaskAllocation.task_package_id.in_([pack.id for pack in packages]))
        ):
            amounts[allocation.task_package_id] += (
                allocation.assigned_tag_count or allocation.assigned_road_meters or 0
            )
    errors = []
    for package in packages:
        code, message = None, None
        if not after['is_enabled'] or any(
            item['start_date'] <= package.work_date <= item['end_date'] for item in unavailable
        ):
            code, message = 'RESOURCE_UNAVAILABLE', '资源在正式安排日不可用'
        elif target_type == 'DRIVER' and not after[f'can_{package.shift_code.lower()}']:
            code, message = 'SHIFT_NOT_QUALIFIED', '司机不具备正式安排所需的班次资格'
        elif target_type == 'VEHICLE':
            unit = 'tag_count' if package.task_mode == 'TAG' else 'road_meters'
            capacity = int(after[f'{package.shift_code.lower()}_max_{unit}'])
            if capacity <= 0 or amounts[package.id] > capacity:
                code, message = 'CAPACITY_EXCEEDED', '车辆新容量不足以承接正式任务包合计数量'
        if code:
            errors.append(
                {
                    'code': code,
                    'message': message,
                    'target_type': target_type,
                    'target_id': str(target_id),
                    'work_date': package.work_date,
                }
            )
    if errors:
        raise ApiError('FUTURE_SCHEDULE_INVALID', '变更会使未来正式安排非法，请先调整对应日期的排班', errors)


def capacity_rows(vehicles: list[dict], unavailable: list[dict], work_date: str) -> list[dict]:
    return [
        {
            'vehicle_id': int(vehicle['id']) if vehicle['id'] is not None else None,
            'plate_number_snapshot': vehicle['plate_number'],
            'vehicle_name_snapshot': vehicle['name'],
            'shift_code': shift,
            'is_available': int(
                bool(vehicle['is_enabled'])
                and not any(
                    item['vehicle_id'] == vehicle['id']
                    and item['start_date'] <= work_date <= item['end_date']
                    for item in unavailable
                )
            ),
            'max_tag_count': int(vehicle[f'{shift.lower()}_max_tag_count']),
            'max_road_meters': int(vehicle[f'{shift.lower()}_max_road_meters']),
        }
        for vehicle in vehicles
        for shift in SHIFTS
    ]


def related_changes(
    db: Session,
    *,
    category: dict | None = None,
    vehicles: list[dict] | None = None,
    unavailable: list[dict] | None = None,
    mark_drafts: bool = False,
    draft_dates: set[str] | None = None,
) -> list[dict]:
    result = []
    demands_by_day, allocations_by_day = defaultdict(list), defaultdict(list)
    if category is not None:
        for demand in db.scalars(
            select(DailyDemand)
            .join(PlanDay, PlanDay.id == DailyDemand.plan_day_id)
            .where(
                PlanDay.work_date > business_date().isoformat(),
                DailyDemand.collection_category_id == int(category['id']),
            )
            .order_by(DailyDemand.id)
        ):
            demands_by_day[demand.plan_day_id].append(demand)
        for allocation, day_id in db.execute(
            select(TaskAllocation, TaskPackage.plan_day_id)
            .join(TaskPackage, TaskPackage.id == TaskAllocation.task_package_id)
            .join(PlanDay, PlanDay.id == TaskPackage.plan_day_id)
            .where(
                PlanDay.work_date > business_date().isoformat(),
                TaskPackage.schedule_kind == 'DRAFT',
                TaskAllocation.collection_category_id == int(category['id']),
            )
            .order_by(TaskAllocation.id)
        ):
            allocations_by_day[day_id].append(allocation)
    for day in db.scalars(
        select(PlanDay)
        .where(PlanDay.work_date > business_date().isoformat())
        .order_by(PlanDay.work_date, PlanDay.id)
    ):
        changes = []
        if category is not None:
            for demand in demands_by_day[day.id]:
                changes += field_changes(
                    {f'daily_demands[{demand.id}].category_name_snapshot': demand.category_name_snapshot},
                    {f'daily_demands[{demand.id}].category_name_snapshot': category['name']},
                )
            for allocation in allocations_by_day[day.id]:
                changes += field_changes(
                    {
                        f'task_allocations[{allocation.id}].category_name_snapshot': allocation.category_name_snapshot
                    },
                    {f'task_allocations[{allocation.id}].category_name_snapshot': category['name']},
                )
        if vehicles is not None:
            old_capacity = parse_capacities(day.vehicle_capacities_json)
            new_capacity = capacity_rows(vehicles, unavailable, day.work_date)
            # Auto-assigned IDs are shown as pending for a newly created vehicle.
            changes += field_changes(
                {'vehicle_capacities_json': public_capacity(old_capacity)},
                {'vehicle_capacities_json': public_capacity(new_capacity)},
            )
        if day.draft_metadata_json is not None:
            metadata = parse_snapshot(DraftMetadata, day.draft_metadata_json)
            category_in_basis = category is not None and int(category['id']) in category_ids(
                metadata.validation_basis
            )
            draft_affected = mark_drafts and (draft_dates is None or day.work_date in draft_dates)
            if (draft_affected or changes or category_in_basis) and not metadata.needs_revalidation:
                changes += field_changes(
                    {'draft_metadata_json.needs_revalidation': 0},
                    {'draft_metadata_json.needs_revalidation': 1},
                )
        if changes:
            result.append({'plan_day_id': str(day.id), 'work_date': day.work_date, 'changes': changes})
    return result


def enrich_versions(db: Session, expected, related: list[dict]):
    enriched = expected.model_copy(deep=True)
    existing_days = {item.id for item in enriched.plan_days}
    existing_plans = {item.id for item in enriched.collection_plans}
    days = list(
        db.scalars(
            select(PlanDay)
            .where(PlanDay.id.in_([int(item['plan_day_id']) for item in related]))
            .order_by(PlanDay.id)
        )
    )
    plans = {
        plan.id: plan
        for plan in db.scalars(
            select(CollectionPlan).where(CollectionPlan.id.in_({day.collection_plan_id for day in days}))
        )
    }
    for day in days:
        if str(day.id) not in existing_days:
            enriched.plan_days.append(
                DayVersion(id=str(day.id), version=str(day.version), formal_version=str(day.formal_version))
            )
            existing_days.add(str(day.id))
        if str(day.collection_plan_id) not in existing_plans:
            plan = plans.get(day.collection_plan_id)
            if plan is None:
                raise ApiError('DATA_INTEGRITY_ERROR', '日期所属计划缺失')
            enriched.collection_plans.append(ObjectVersion(id=str(plan.id), version=str(plan.version)))
            existing_plans.add(str(plan.id))
    return enriched


def apply_related(
    db: Session, related: list[dict], next_revision: int, created_vehicle_id: int | None = None
) -> tuple[list[DayRevision], list[dict]]:
    revisions, audit_changes, plans = [], [], set()
    timestamp = utc_timestamp()
    days = {
        day.id: day
        for day in db.scalars(
            select(PlanDay).where(PlanDay.id.in_([int(item['plan_day_id']) for item in related]))
        )
    }
    plan_rows = {
        plan.id: plan
        for plan in db.scalars(
            select(CollectionPlan).where(
                CollectionPlan.id.in_({day.collection_plan_id for day in days.values()})
            )
        )
    }
    for item in related:
        day = days[int(item['plan_day_id'])]
        plans.add(day.collection_plan_id)
        for change in item['changes']:
            field, value = change['field'], change['after']
            if field == 'vehicle_capacities_json':
                rows = [
                    row
                    | {
                        'vehicle_id': int(row['vehicle_id'])
                        if row['vehicle_id'] is not None
                        else created_vehicle_id,
                        'max_tag_count': int(row['max_tag_count']),
                        'max_road_meters': int(row['max_road_meters']),
                    }
                    for row in value
                ]
                validated = parse_capacities(canonical(rows))
                day.vehicle_capacities_json = canonical(validated)
                day.capacity_basis_revision = next_revision
                day.capacity_captured_at = timestamp
                value = public_capacity(validated)
            elif field == 'draft_metadata_json.needs_revalidation':
                metadata = json.loads(day.draft_metadata_json)
                metadata['needs_revalidation'], metadata['updated_at'] = 1, timestamp
                day.draft_metadata_json = canonical(metadata)
            else:
                table_name, identifier = field.split('[', 1)
                row_id = int(identifier.split(']', 1)[0])
                model = DailyDemand if table_name == 'daily_demands' else TaskAllocation
                values = {'category_name_snapshot': value}
                if model is DailyDemand:
                    values['updated_at'] = timestamp
                db.execute(update(model).where(model.id == row_id).values(**values))
            audit_changes.append(change | {'field': f'plan_days[{day.id}].{field}', 'after': value})
        new_version = advance_object_version(db, 'plan_days', day.id, day.version)
        revisions.append(
            DayRevision(
                plan_day_id=str(day.id), version=str(new_version), formal_version=str(day.formal_version)
            )
        )
    for plan_id in sorted(plans):
        plan = plan_rows[plan_id]
        advance_object_version(db, 'collection_plans', plan.id, plan.version)
    return revisions, audit_changes
