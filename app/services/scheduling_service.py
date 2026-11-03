import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, timedelta
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.models import (
    AssignmentRoadAllocation,
    AssignmentTagAllocation,
    CollectionPlan,
    ConfirmationOperation,
    DailySchedule,
    Driver,
    Notification,
    PreviewDayClaim,
    ScheduleAssignment,
    SchedulePreview,
    Shift,
    Vehicle,
    VehicleDayMode,
    VehicleShiftCapacity,
    utcnow,
)
from app.repositories.scheduling_repository import SchedulingRepository, require
from app.scheduling.constraints import ConstraintValidator
from app.scheduling.evaluator import dispersion, evaluate
from app.scheduling.registry import get_strategy
from app.schemas import (
    AssignmentAdd,
    AssignmentInput,
    AssignmentPatch,
    ConfirmInput,
    PreviewCreate,
    km_to_meters,
    meters_to_km,
)
from app.services.audit_service import audit


def assignment_to_internal(payload: AssignmentInput, identifier: str | None = None) -> dict:
    return {
        'assignment_id': identifier or f'A-{uuid4().hex[:12]}',
        'vehicle_id': payload.vehicle_id,
        'driver_id': payload.driver_id,
        'shift': str(payload.shift),
        'task_mode': payload.task_mode,
        'tags': {a.tag_type: a.count for a in payload.tag_allocations},
        'roads': {a.road_type: km_to_meters(a.km) for a in payload.road_allocations},
    }


def assignment_to_public(item: dict) -> dict:
    return {key: value for key, value in item.items() if key not in ('tags', 'roads')} | {
        'tag_allocations': [{'tag_type': key, 'count': value} for key, value in item['tags'].items()],
        'road_allocations': [
            {'road_type': key, 'km': meters_to_km(value)} for key, value in item['roads'].items()
        ],
    }


class SchedulingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SchedulingRepository(db)
        self.validator = ConstraintValidator()

    def _confirmed(self, plan_id: int) -> dict[str, DailySchedule]:
        return {
            s.schedule_date.isoformat(): s
            for s in self.db.scalars(select(DailySchedule).where(DailySchedule.plan_id == plan_id))
        }

    def _expire(self) -> None:
        for row in self.db.scalars(
            select(SchedulePreview).where(
                SchedulePreview.status.in_(['PENDING', 'PARTIALLY_CONFIRMED']),
                SchedulePreview.expires_at <= utcnow(),
            )
        ):
            row.status = 'EXPIRED'
            self.db.execute(delete(PreviewDayClaim).where(PreviewDayClaim.preview_id == row.id))

    def generate(self, payload: PreviewCreate) -> dict:
        plan = require(self.db, CollectionPlan, payload.plan_id)
        if payload.start_date < plan.start_date or payload.end_date > plan.end_date:
            raise BusinessError('DATE_OUT_OF_PLAN', '排班日期必须位于采集计划范围内', 422)
        self._expire()
        confirmed = self._confirmed(plan.id)
        claims = {
            r.work_date.isoformat(): r.preview_id
            for r in self.db.scalars(select(PreviewDayClaim).where(PreviewDayClaim.plan_id == plan.id))
        }
        current, missing, existing_ids, existing_schedules = payload.start_date, [], set(), []
        while current <= payload.end_date:
            key = current.isoformat()
            if key in confirmed:
                existing_schedules.append(confirmed[key])
            elif key in claims:
                existing_ids.add(claims[key])
            else:
                missing.append(current)
            current += timedelta(days=1)
        if missing:
            # All dates of the plan's range participate in same-grade driver balancing.
            workloads = self.repo.workloads(plan.start_date, plan.end_date)
            for preview in self.db.scalars(
                select(SchedulePreview).where(
                    SchedulePreview.plan_id == plan.id,
                    SchedulePreview.status.in_(['PENDING', 'PARTIALLY_CONFIRMED']),
                )
            ):
                for day in preview.preview_content['days']:
                    if day['date'] not in confirmed:
                        for assignment in day['assignments']:
                            workloads[assignment['driver_id']] = workloads.get(assignment['driver_id'], 0) + 1
            days = []
            for work_date in missing:
                data = self.repo.input(plan.id, work_date, workloads)
                started = perf_counter()
                assignments = get_strategy(payload.algorithm).generate(data)
                runtime_ms = round((perf_counter() - started) * 1000, 3)
                self.validator.validate(data, assignments)
                days.append(
                    {
                        'date': work_date.isoformat(),
                        'assignments': assignments,
                        'algorithm_runtime_ms': runtime_ms,
                    }
                )
                for assignment in assignments:
                    workloads[assignment['driver_id']] = workloads.get(assignment['driver_id'], 0) + 1
            row = SchedulePreview(
                id=f'PREV-{uuid4().hex[:24]}',
                plan_id=plan.id,
                start_date=missing[0],
                end_date=missing[-1],
                algorithm_name=payload.algorithm,
                preview_content={'days': days},
                expires_at=utcnow() + timedelta(hours=settings.preview_ttl_hours),
            )
            self.db.add(row)
            self.db.flush()
            for work_date in missing:
                self.db.add(PreviewDayClaim(plan_id=plan.id, work_date=work_date, preview_id=row.id))
            existing_ids.add(row.id)
            audit(
                self.db,
                'GENERATE_PREVIEW',
                'schedule_preview',
                row.id,
                after={'dates': [d.isoformat() for d in missing], 'algorithm': payload.algorithm},
            )
            self.db.flush()
        return {
            'operation_status': 'CREATED'
            if missing
            else ('EXISTING_PREVIEW' if existing_ids else 'ALREADY_CONFIRMED'),
            'previews': [self.preview(identifier) for identifier in sorted(existing_ids)],
            'confirmed_schedules': [self.schedule(s) for s in existing_schedules],
        }

    def _day_view(
        self, plan_id: int, day: dict, confirmed: bool = False, schedule_id: int | None = None
    ) -> dict:
        work_date = date.fromisoformat(day['date'])
        data = self.repo.input(plan_id, work_date, exclude_schedule_id=schedule_id)
        metrics = evaluate(data, day['assignments'])
        drivers = {d.id: d for d in self.db.scalars(select(Driver))}
        vehicles = {v.id: v for v in self.db.scalars(select(Vehicle))}
        shifts = {s.id: s.code for s in self.db.scalars(select(Shift))}
        capacities = {
            (c.vehicle_id, shifts[c.shift_id]): c for c in self.db.scalars(select(VehicleShiftCapacity))
        }
        assignments, utilization = [], defaultdict(lambda: {'assigned': 0, 'capacity': 0})
        for item in day['assignments']:
            driver, vehicle = drivers[item['driver_id']], vehicles[item['vehicle_id']]
            capacity = capacities.get((vehicle.id, item['shift']))
            maximum = (
                (capacity.max_tag_count if item['task_mode'] == 'TAG' else capacity.max_road_meters)
                if capacity
                else 0
            )
            amount = sum(item['tags'].values()) if item['task_mode'] == 'TAG' else sum(item['roads'].values())
            assignments.append(
                assignment_to_public(item)
                | {
                    'driver_name': driver.name,
                    'driver_efficiency': driver.efficiency_level,
                    'vehicle_name': vehicle.vehicle_name,
                    'plate_number': vehicle.plate_number,
                    'capacity': maximum if item['task_mode'] == 'TAG' else meters_to_km(maximum),
                    'capacity_utilization': round(amount / maximum * 100, 2) if maximum else 0,
                }
            )
            aggregate = utilization[(vehicle.id, item['task_mode'])]
            aggregate['assigned'] += amount
            aggregate['capacity'] += maximum
        errors = []
        if not confirmed:
            try:
                self.validator.validate(data, day['assignments'])
            except BusinessError as exc:
                errors.append({'code': exc.code, 'message': exc.message})
        return {
            'date': day['date'],
            'confirmed': confirmed,
            'schedule_id': schedule_id,
            'assignments': assignments,
            'coverage_status': metrics['coverage_status'],
            'requirements': {
                'tags': [{'tag_type': k, 'count': v} for k, v in data.tag_requirements.items()],
                'roads': [{'road_type': k, 'km': meters_to_km(v)} for k, v in data.road_requirements.items()],
            },
            'unallocated': {
                'tags': [{'tag_type': k, 'count': v} for k, v in metrics['remaining_tags'].items()],
                'roads': [
                    {'road_type': k, 'km': meters_to_km(v)} for k, v in metrics['remaining_roads'].items()
                ],
            },
            'metrics': {
                'tag_target': metrics['tag_target'],
                'tag_assigned': metrics['tag_assigned'],
                'tag_coverage_rate': metrics['tag_coverage_rate'],
                'road_target_km': meters_to_km(metrics['road_target_meters']),
                'road_assigned_km': meters_to_km(metrics['road_assigned_meters']),
                'road_coverage_rate': metrics['road_coverage_rate'],
            },
            'vehicle_utilization': [
                {
                    'vehicle_id': key[0],
                    'task_mode': key[1],
                    'utilization': round(value['assigned'] / value['capacity'] * 100, 2)
                    if value['capacity']
                    else 0,
                }
                for key, value in utilization.items()
            ],
            'constraint_validation': {'valid': not errors, 'errors': errors},
            'quality': {
                'algorithm_runtime_ms': day.get('algorithm_runtime_ms'),
                'manually_modified': day.get('manually_modified', False),
                'driver_efficiency_distribution': dict(
                    Counter(drivers[a['driver_id']].efficiency_level for a in day['assignments'])
                ),
                'vehicle_utilization_dispersion_by_mode': {
                    mode: dispersion(
                        [
                            round(v['assigned'] / v['capacity'] * 100, 4) if v['capacity'] else 0
                            for (vehicle_id, task_mode), v in utilization.items()
                            if task_mode == mode
                        ]
                    )
                    for mode in ('TAG', 'ROAD')
                },
                'hard_constraint_violations_detected': len(errors),
                'validation_stops_at_first_error': True,
            },
            'reasons': metrics['reasons'],
            'auto_carry_forward': False,
        }

    def preview(self, identifier: str) -> dict:
        row = require(self.db, SchedulePreview, identifier)
        confirmed = self._confirmed(row.plan_id)
        days = [
            self._day_view(
                row.plan_id,
                d,
                d['date'] in confirmed,
                confirmed[d['date']].id if d['date'] in confirmed else None,
            )
            for d in row.preview_content['days']
        ]
        status = (
            'EXPIRED'
            if row.expires_at <= utcnow() and row.status in ('PENDING', 'PARTIALLY_CONFIRMED')
            else row.status
        )
        plan = require(self.db, CollectionPlan, row.plan_id)
        workloads = Counter(self.repo.workloads(plan.start_date, plan.end_date))
        for day in row.preview_content['days']:
            if day['date'] not in confirmed:
                workloads.update(a['driver_id'] for a in day['assignments'])
        driver_metrics = self._driver_metrics(workloads)
        return {
            'preview_id': row.id,
            'preview_version': row.preview_version,
            'plan_id': row.plan_id,
            'plan_title': require(self.db, CollectionPlan, row.plan_id).title,
            'start_date': row.start_date.isoformat(),
            'end_date': row.end_date.isoformat(),
            'algorithm': row.algorithm_name,
            'lifecycle_status': status,
            'status': 'FULL'
            if all(d['coverage_status'] == 'FULL' for d in days)
            else ('NO_ASSIGNMENT' if all(not d['assignments'] for d in days) else 'PARTIAL'),
            'expires_at': row.expires_at.isoformat() + 'Z',
            'daily_results': days,
            'quality': {
                **driver_metrics,
                'algorithm_runtime_ms': round(
                    sum(day.get('algorithm_runtime_ms', 0) for day in row.preview_content['days']), 3
                ),
                'hard_constraint_violations_detected': sum(
                    len(d['constraint_validation']['errors']) for d in days
                ),
            },
            'explanation': '先满足任务覆盖，再按 HIGH → MEDIUM → LOW 选择司机；同等级参考累计班次，同模式按容量比例均衡。预览不占用正式资源。',
        }

    def list_previews(self, plan_id: int | None = None) -> list[dict]:
        query = select(SchedulePreview).order_by(SchedulePreview.created_at.desc()).limit(100)
        if plan_id is not None:
            query = query.where(SchedulePreview.plan_id == plan_id)
        return [
            {
                'preview_id': row.id,
                'plan_id': row.plan_id,
                'preview_version': row.preview_version,
                'start_date': row.start_date.isoformat(),
                'end_date': row.end_date.isoformat(),
                'lifecycle_status': 'EXPIRED'
                if row.expires_at <= utcnow() and row.status in ('PENDING', 'PARTIALLY_CONFIRMED')
                else row.status,
            }
            for row in self.db.scalars(query)
        ]

    def _editable(self, row: SchedulePreview, expected_version: int) -> None:
        if row.preview_version != expected_version:
            raise BusinessError(
                'VERSION_CONFLICT',
                '预览已被修改，请刷新后重试',
                details={'current_version': row.preview_version},
            )
        if row.status not in ('PENDING', 'PARTIALLY_CONFIRMED') or row.expires_at <= utcnow():
            raise BusinessError('PREVIEW_NOT_EDITABLE', '预览已确认、放弃或过期，请重新查看当前状态')

    def edit(
        self,
        identifier: str,
        expected_version: int,
        operation: str,
        assignment_id: str | None = None,
        payload: AssignmentAdd | AssignmentPatch | None = None,
    ) -> dict:
        row = require(self.db, SchedulePreview, identifier)
        self._editable(row, expected_version)
        content = deepcopy(row.preview_content)
        confirmed = self._confirmed(row.plan_id)
        target_day = None
        if operation == 'ADD':
            assert isinstance(payload, AssignmentAdd)
            target_day = next((d for d in content['days'] if d['date'] == payload.date.isoformat()), None)
            if target_day is None:
                raise BusinessError('DATE_OUT_OF_PREVIEW', '新增排班日期不属于该预览', 422)
            target_day['assignments'].append(assignment_to_internal(payload))
        else:
            for day in content['days']:
                for index, item in enumerate(day['assignments']):
                    if item['assignment_id'] != assignment_id:
                        continue
                    target_day = day
                    if operation == 'DELETE':
                        day['assignments'].pop(index)
                    else:
                        assert isinstance(payload, AssignmentPatch)
                        existing = assignment_to_public(item)
                        existing.pop('assignment_id')
                        existing.update(payload.changes.model_dump(exclude_unset=True, mode='json'))
                        # Re-run the full schema, including task mode and duplicate-type checks.
                        day['assignments'][index] = assignment_to_internal(
                            AssignmentInput.model_validate(existing), assignment_id
                        )
                    break
                if target_day:
                    break
            if target_day is None:
                raise BusinessError('NOT_FOUND', '预览明细不存在', 404)
        if target_day['date'] in confirmed:
            raise BusinessError('DAY_ALREADY_CONFIRMED', '该日期已正式确认，不能修改')
        target_day['manually_modified'] = True
        # Validate every pending day, using the same rules as confirmation.
        for day in content['days']:
            if day['date'] not in confirmed:
                self.validator.validate(
                    self.repo.input(row.plan_id, date.fromisoformat(day['date'])), day['assignments']
                )
        before = row.preview_content
        row.preview_content = content
        row.preview_version += 1
        audit(self.db, f'{operation}_PREVIEW_ASSIGNMENT', 'schedule_preview', identifier, before, content)
        self.db.flush()
        return self.preview(identifier)

    def discard(self, identifier: str, expected_version: int) -> dict:
        row = require(self.db, SchedulePreview, identifier)
        if row.preview_version != expected_version:
            raise BusinessError('VERSION_CONFLICT', '预览版本已变化，请刷新')
        if row.status == 'CONFIRMED':
            raise BusinessError('DAY_ALREADY_CONFIRMED', '正式排班不能通过放弃预览覆盖')
        if row.status != 'DISCARDED':
            row.status = 'DISCARDED'
            row.preview_version += 1
            self.db.execute(delete(PreviewDayClaim).where(PreviewDayClaim.preview_id == identifier))
            audit(self.db, 'DISCARD_PREVIEW', 'schedule_preview', identifier)
        self.db.flush()
        return self.preview(identifier)

    def confirm(self, payload: ConfirmInput) -> tuple[dict, list[int]]:
        fingerprint = hashlib.sha256(
            json.dumps(payload.model_dump(mode='json'), sort_keys=True).encode()
        ).hexdigest()
        previous = self.db.get(ConfirmationOperation, payload.idempotency_key)
        if previous:
            if previous.request_hash != fingerprint:
                raise BusinessError('IDEMPOTENCY_KEY_REUSED', '该幂等键已用于不同的确认请求')
            return {
                **previous.response,
                'operation_status': 'ALREADY_CONFIRMED',
                'newly_confirmed_dates': [],
                'skipped_dates': [d.isoformat() for d in payload.confirm_dates],
                'notification_triggered': False,
                'replayed': True,
            }, []
        row = require(self.db, SchedulePreview, payload.preview_id)
        days = {d['date']: d for d in row.preview_content['days']}
        requested = [d.isoformat() for d in payload.confirm_dates]
        if any(d not in days for d in requested):
            raise BusinessError('DATE_OUT_OF_PREVIEW', '确认日期不属于当前预览', 422)
        confirmed = self._confirmed(row.plan_id)
        skipped = [d for d in requested if d in confirmed]
        pending = [d for d in requested if d not in confirmed]
        if not pending:
            return {
                'operation_status': 'ALREADY_CONFIRMED',
                'newly_confirmed_dates': [],
                'skipped_dates': skipped,
                'notification_triggered': False,
            }, []
        self._editable(row, payload.expected_version)
        for key in pending:
            if not days[key]['assignments']:
                raise BusinessError('NO_ASSIGNMENT', f'{key} 没有可执行排班，不能确认空排班')
            claim = self.db.get(PreviewDayClaim, (row.plan_id, date.fromisoformat(key)))
            if claim is None or claim.preview_id != row.id:
                raise BusinessError('PREVIEW_NOT_CURRENT', '该预览已不是当前有效预览')
            self.validator.validate(
                self.repo.input(row.plan_id, date.fromisoformat(key)), days[key]['assignments']
            )
        notification_ids = []
        shifts = {s.code: s.id for s in self.db.scalars(select(Shift))}
        for key in pending:
            work_date = date.fromisoformat(key)
            schedule = DailySchedule(
                plan_id=row.plan_id,
                schedule_date=work_date,
                version=row.preview_version,
                algorithm_name=row.algorithm_name,
            )
            self.db.add(schedule)
            self.db.flush()
            _, _, tag_ids, road_ids = self.repo.requirements(row.plan_id, work_date)
            for item in days[key]['assignments']:
                assignment = ScheduleAssignment(
                    schedule_id=schedule.id,
                    work_date=work_date,
                    vehicle_id=item['vehicle_id'],
                    driver_id=item['driver_id'],
                    shift_id=shifts[item['shift']],
                    task_mode=item['task_mode'],
                )
                self.db.add(assignment)
                mode = self.db.get(VehicleDayMode, (item['vehicle_id'], work_date))
                if mode is None:
                    self.db.add(
                        VehicleDayMode(
                            vehicle_id=item['vehicle_id'], work_date=work_date, task_mode=item['task_mode']
                        )
                    )
                elif mode.task_mode != item['task_mode']:
                    raise BusinessError('VEHICLE_MODE_CONFLICT', f'{key} 车辆任务模式冲突')
                self.db.flush()
                for task, amount in item['tags'].items():
                    self.db.add(
                        AssignmentTagAllocation(
                            assignment_id=assignment.id,
                            daily_tag_requirement_id=tag_ids[task],
                            assigned_count=amount,
                        )
                    )
                for task, amount in item['roads'].items():
                    self.db.add(
                        AssignmentRoadAllocation(
                            assignment_id=assignment.id,
                            daily_road_requirement_id=road_ids[task],
                            assigned_meters=amount,
                        )
                    )
                driver = require(self.db, Driver, item['driver_id'])
                vehicle = require(self.db, Vehicle, item['vehicle_id'])
                detail = '\n'.join(
                    [f'{k}：{v} 个' for k, v in item['tags'].items()]
                    + [f'{k}：{meters_to_km(v)} km' for k, v in item['roads'].items()]
                )
                shift_name = {'MORNING': '早班', 'AFTERNOON': '中班', 'NIGHT': '晚班'}[item['shift']]
                notice = Notification(
                    assignment_id=assignment.id,
                    driver_id=driver.id,
                    schedule_version=schedule.version,
                    content=f'【采集任务通知】\n司机：{driver.name}\n采集日期：{key}\n车辆：{vehicle.plate_number}\n班次：{shift_name}\n采集模式：{item["task_mode"]}\n{detail}\n排班状态：已确认',
                    idempotency_key=f'assignment:{assignment.id}:version:{schedule.version}:confirmed',
                )
                self.db.add(notice)
                self.db.flush()
                notification_ids.append(notice.id)
            self.db.execute(
                delete(PreviewDayClaim).where(
                    PreviewDayClaim.plan_id == row.plan_id, PreviewDayClaim.work_date == work_date
                )
            )
        all_confirmed = set(confirmed) | set(pending)
        row.status = 'CONFIRMED' if set(days).issubset(all_confirmed) else 'PARTIALLY_CONFIRMED'
        row.preview_version += 1
        plan = require(self.db, CollectionPlan, row.plan_id)
        plan.version += 1
        coverage = (
            'FULL'
            if all(
                evaluate(self.repo.input(row.plan_id, date.fromisoformat(k)), days[k]['assignments'])[
                    'coverage_status'
                ]
                == 'FULL'
                for k in pending
            )
            else 'PARTIAL'
        )
        result = {
            'operation_status': 'SUCCESS',
            'newly_confirmed_dates': pending,
            'skipped_dates': skipped,
            'coverage_status': coverage,
            'notification_status': 'PENDING',
            'notification_triggered': bool(notification_ids),
            'preview_version': row.preview_version,
        }
        self.db.add(
            ConfirmationOperation(
                idempotency_key=payload.idempotency_key, request_hash=fingerprint, response=result
            )
        )
        audit(self.db, 'CONFIRM_SCHEDULE', 'schedule_preview', row.id, after=result)
        self.db.flush()
        return result, notification_ids

    def schedule(self, row: DailySchedule) -> dict:
        assignments = [
            a
            for a in self.repo.assignments(row.schedule_date, row.schedule_date)
            if a['schedule_id'] == row.id
        ]
        result = self._day_view(
            row.plan_id, {'date': row.schedule_date.isoformat(), 'assignments': assignments}, True, row.id
        )
        return result | {
            'schedule_id': row.id,
            'plan_id': row.plan_id,
            'plan_title': require(self.db, CollectionPlan, row.plan_id).title,
            'version': row.version,
            'algorithm': row.algorithm_name,
            'confirmed_at': row.confirmed_at.isoformat() + 'Z',
        }

    def schedules(
        self,
        start: date | None = None,
        end: date | None = None,
        plan_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        query = select(DailySchedule).order_by(DailySchedule.schedule_date, DailySchedule.id)
        if start:
            query = query.where(DailySchedule.schedule_date >= start)
        if end:
            query = query.where(DailySchedule.schedule_date <= end)
        if plan_id is not None:
            query = query.where(DailySchedule.plan_id == plan_id)
        return [self.schedule(s) for s in self.db.scalars(query.limit(limit).offset(offset))]

    def statistics(
        self, start: date | None = None, end: date | None = None, plan_id: int | None = None
    ) -> dict:
        query = select(DailySchedule)
        if start:
            query = query.where(DailySchedule.schedule_date >= start)
        if end:
            query = query.where(DailySchedule.schedule_date <= end)
        if plan_id is not None:
            query = query.where(DailySchedule.plan_id == plan_id)
        schedules = [self.schedule(row) for row in self.db.scalars(query)]
        drivers = {d.id: d for d in self.db.scalars(select(Driver))}
        counts, vehicle_stats = (
            Counter(),
            defaultdict(lambda: {'tag_count': 0, 'road_meters': 0, 'shift_count': 0}),
        )
        tag_target = tag_assigned = road_target = road_assigned = 0
        for day in schedules:
            m = day['metrics']
            tag_target += m['tag_target']
            tag_assigned += m['tag_assigned']
            road_target += km_to_meters(m['road_target_km'])
            road_assigned += km_to_meters(m['road_assigned_km'])
            for a in day['assignments']:
                counts[a['driver_id']] += 1
                v = vehicle_stats[a['vehicle_id']]
                v['shift_count'] += 1
                v['tag_count'] += sum(t['count'] for t in a['tag_allocations'])
                v['road_meters'] += sum(km_to_meters(r['km']) for r in a['road_allocations'])
        return {
            **self._driver_metrics(counts),
            'confirmed_days': len(schedules),
            'assignment_count': sum(counts.values()),
            'active_drivers': sum(d.status == 'ACTIVE' for d in drivers.values()),
            'active_vehicles': len(list(self.db.scalars(select(Vehicle).where(Vehicle.status == 'ACTIVE')))),
            'tag_target': tag_target,
            'tag_assigned': tag_assigned,
            'tag_coverage_rate': round(tag_assigned / tag_target * 100, 2) if tag_target else None,
            'road_target_km': meters_to_km(road_target),
            'road_assigned_km': meters_to_km(road_assigned),
            'road_coverage_rate': round(road_assigned / road_target * 100, 2) if road_target else None,
            'driver_workloads': [
                {
                    'driver_id': d.id,
                    'name': d.name,
                    'efficiency_level': d.efficiency_level,
                    'shift_count': counts[d.id],
                }
                for d in drivers.values()
            ],
            'vehicle_workloads': [
                {
                    'vehicle_id': key,
                    'shift_count': value['shift_count'],
                    'tag_count': value['tag_count'],
                    'road_km': meters_to_km(value['road_meters']),
                }
                for key, value in vehicle_stats.items()
            ],
            'unallocated': [
                {'plan_id': d['plan_id'], 'date': d['date'], **d['unallocated'], 'auto_carry_forward': False}
                for d in schedules
                if d['coverage_status'] != 'FULL'
            ],
        }

    def _driver_metrics(self, counts: dict[int, int]) -> dict:
        drivers = list(self.db.scalars(select(Driver).order_by(Driver.id)))
        return {
            'driver_efficiency_distribution': {
                level: sum(counts.get(d.id, 0) for d in drivers if d.efficiency_level == level)
                for level in ('HIGH', 'MEDIUM', 'LOW')
            },
            'driver_shift_dispersion_by_efficiency': {
                level: dispersion(
                    [
                        counts.get(d.id, 0)
                        for d in drivers
                        if d.efficiency_level == level and (d.status == 'ACTIVE' or counts.get(d.id, 0))
                    ]
                )
                for level in ('HIGH', 'MEDIUM', 'LOW')
            },
            'driver_cumulative_workloads': [
                {
                    'driver_id': d.id,
                    'name': d.name,
                    'efficiency_level': d.efficiency_level,
                    'shift_count': counts.get(d.id, 0),
                }
                for d in drivers
            ],
        }
