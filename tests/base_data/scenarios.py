from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_timestamp
from app.models.foundation import (
    AuditLog,
    BusinessOperation,
    CollectionPlan,
    DailyDemand,
    PlanDay,
    TaskAllocation,
    TaskPackage,
    Vehicle,
)
from app.repositories.base_data import state
from app.services.base_data_effects import capacity_rows
from app.services.confirmation_service import canonical


def draft_metadata(category_id: int) -> dict:
    return {
        'schema_version': 1,
        'algorithm_code': 'GREEDY_V1',
        'algorithm_version': '1',
        'input_revision': 1,
        'is_manually_modified': 0,
        'needs_revalidation': 0,
        'validation_basis': {'demands': [{'collection_category_id': category_id}]},
        'shortage_reasons': [],
        'generated_at': utc_timestamp(),
        'updated_at': utc_timestamp(),
    }


def seed_days(engine, dates, category_id: int, driver_id: int, vehicle_id: int, kind='DRAFT', mode='TAG'):
    with Session(engine) as db:
        plan = CollectionPlan(name='关联测试计划', start_date=min(dates), end_date=max(dates))
        db.add(plan)
        db.flush()
        vehicles = [state(value, 'VEHICLE') for value in db.scalars(select(Vehicle).order_by(Vehicle.id))]
        days = []
        for work_date in dates:
            day = PlanDay(
                collection_plan_id=plan.id,
                work_date=work_date,
                draft_metadata_json=canonical(draft_metadata(category_id)) if kind == 'DRAFT' else None,
                formal_status='ACTIVE' if kind == 'FORMAL' else 'NONE',
                formal_version=1 if kind == 'FORMAL' else 0,
                vehicle_capacities_json=canonical(capacity_rows(vehicles, [], work_date)),
                capacity_basis_revision=1,
                capacity_captured_at=utc_timestamp(),
            )
            db.add(day)
            db.flush()
            db.add(
                DailyDemand(
                    plan_day_id=day.id,
                    collection_category_id=category_id,
                    category_name_snapshot='原类别',
                    task_mode=mode,
                    target_tag_count=20 if mode == 'TAG' else None,
                    target_road_meters=10000 if mode == 'ROAD' else None,
                    sort_order=1,
                )
            )
            package = TaskPackage(
                plan_day_id=day.id,
                work_date=work_date,
                schedule_kind=kind,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                shift_code='MORNING',
                task_mode=mode,
                driver_name_snapshot='原司机',
                efficiency_level_snapshot='MEDIUM',
                plate_number_snapshot='原车牌',
                vehicle_name_snapshot=None,
                max_tag_count_snapshot=10,
                max_road_meters_snapshot=12500,
            )
            db.add(package)
            db.flush()
            db.add(
                TaskAllocation(
                    task_package_id=package.id,
                    collection_category_id=category_id,
                    category_name_snapshot='原类别',
                    task_mode=mode,
                    assigned_tag_count=5 if mode == 'TAG' else None,
                    assigned_road_meters=5000 if mode == 'ROAD' else None,
                )
            )
            days.append(day.id)
        db.commit()
        return plan.id, days


def formal_snapshot(db, day_id):
    day = db.get(PlanDay, day_id)
    plan = db.get(CollectionPlan, day.collection_plan_id)
    demands = [
        {
            column.name: getattr(value, column.name)
            for column in DailyDemand.__table__.columns
            if column.name not in ('id', 'plan_day_id', 'created_at', 'updated_at')
        }
        for value in db.scalars(select(DailyDemand).where(DailyDemand.plan_day_id == day_id))
    ]
    packages = []
    for value in db.scalars(select(TaskPackage).where(TaskPackage.plan_day_id == day_id)):
        data = {column.name: getattr(value, column.name) for column in TaskPackage.__table__.columns}
        data['schedule_kind'] = 'FORMAL'
        data['allocations'] = [
            {column.name: getattr(allocation, column.name) for column in TaskAllocation.__table__.columns}
            for allocation in db.scalars(
                select(TaskAllocation).where(TaskAllocation.task_package_id == value.id)
            )
        ]
        packages.append(data)
    import json

    return {
        'header': {
            'collection_plan_id': plan.id,
            'plan_name_snapshot': plan.name,
            'plan_day_id': day.id,
            'work_date': day.work_date,
            'formal_status': 'ACTIVE',
            'formal_version': 1,
        },
        'demands': demands,
        'packages': packages,
        'capacity_basis': {
            'capacity_basis_revision': day.capacity_basis_revision,
            'capacity_captured_at': day.capacity_captured_at,
            'vehicle_capacities_json': json.loads(day.vehicle_capacities_json),
        },
        'generation': {
            'algorithm_code': 'GREEDY_V1',
            'algorithm_version': '1',
            'input_revision': 1,
            'is_manually_modified': 0,
        },
        'shortages': [],
    }


def add_formal_history(db, day_id, before, after, version=2):
    operation = BusinessOperation(
        request_key=str(uuid4()),
        request_hash='a' * 64,
        action_code='CANCEL_FORMAL_DAY',
        entry_source='PAGE',
        target_type='FORMAL_DAY',
        target_id=day_id,
        request_payload_json='{}',
        expected_versions_json='{}',
        summary_json='{}',
        requires_confirmation=1,
        confirmed_at=utc_timestamp(),
        status='SUCCEEDED',
        result_code='EXECUTED',
        result_json='{}',
        finished_at=utc_timestamp(),
    )
    db.add(operation)
    db.flush()
    event = AuditLog(
        business_operation_id=operation.id,
        plan_day_id=day_id,
        formal_version=version,
        formal_change_type='CANCEL',
        entry_source='PAGE',
        action_code='CANCEL_FORMAL_DAY',
        target_type='FORMAL_DAY',
        target_id=day_id,
        target_label_snapshot='正式历史测试',
        outcome='SUCCEEDED',
        changes_json=canonical({'schema_version': 1, 'before': before, 'after': after}),
    )
    db.add(event)
    db.flush()
    return event.id
