from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models import (
    AssignmentRoadAllocation,
    AssignmentTagAllocation,
    DailyRoadRequirement,
    DailyTagRequirement,
    DailyTask,
    Driver,
    DriverShiftQualification,
    ResourceUnavailability,
    ScheduleAssignment,
    Shift,
    Vehicle,
    VehicleShiftCapacity,
)
from app.scheduling.interfaces import DriverResource, SchedulingInput, VehicleResource


def require(db: Session, model, identifier):
    row = db.get(model, identifier)
    if row is None:
        raise BusinessError('NOT_FOUND', '记录不存在', 404)
    return row


class SchedulingRepository:
    def __init__(self, db: Session):
        self.db = db

    def requirements(self, plan_id: int, day: date) -> tuple[dict, dict, dict, dict]:
        task = self.db.scalar(
            select(DailyTask).where(DailyTask.plan_id == plan_id, DailyTask.work_date == day)
        )
        if task is None:
            raise BusinessError('DATE_OUT_OF_PLAN', '所选日期不存在采集需求', 422)
        tags = self.db.scalars(
            select(DailyTagRequirement).where(DailyTagRequirement.daily_task_id == task.id)
        ).all()
        roads = self.db.scalars(
            select(DailyRoadRequirement).where(DailyRoadRequirement.daily_task_id == task.id)
        ).all()
        return (
            {r.tag_type: r.target_count for r in tags},
            {r.road_type: r.target_meters for r in roads},
            {r.tag_type: r.id for r in tags},
            {r.road_type: r.id for r in roads},
        )

    def assignments(self, start: date, end: date, exclude_schedule_id: int | None = None) -> list[dict]:
        query = select(ScheduleAssignment).where(
            ScheduleAssignment.work_date.between(start, end), ScheduleAssignment.status == 'ACTIVE'
        )
        if exclude_schedule_id is not None:
            query = query.where(ScheduleAssignment.schedule_id != exclude_schedule_id)
        shifts = {s.id: s.code for s in self.db.scalars(select(Shift))}
        rows = self.db.scalars(query.order_by(ScheduleAssignment.id)).all()
        if not rows:
            return []
        identifiers = [r.id for r in rows]
        tags: dict[int, dict] = {}
        roads: dict[int, dict] = {}
        for alloc, requirement in self.db.execute(
            select(AssignmentTagAllocation, DailyTagRequirement)
            .join(
                DailyTagRequirement,
                AssignmentTagAllocation.daily_tag_requirement_id == DailyTagRequirement.id,
            )
            .where(AssignmentTagAllocation.assignment_id.in_(identifiers))
        ):
            tags.setdefault(alloc.assignment_id, {})[requirement.tag_type] = alloc.assigned_count
        for alloc, requirement in self.db.execute(
            select(AssignmentRoadAllocation, DailyRoadRequirement)
            .join(
                DailyRoadRequirement,
                AssignmentRoadAllocation.daily_road_requirement_id == DailyRoadRequirement.id,
            )
            .where(AssignmentRoadAllocation.assignment_id.in_(identifiers))
        ):
            roads.setdefault(alloc.assignment_id, {})[requirement.road_type] = alloc.assigned_meters
        return [
            {
                'assignment_id': r.id,
                'schedule_id': r.schedule_id,
                'date': r.work_date.isoformat(),
                'vehicle_id': r.vehicle_id,
                'driver_id': r.driver_id,
                'shift': shifts[r.shift_id],
                'task_mode': r.task_mode,
                'tags': tags.get(r.id, {}),
                'roads': roads.get(r.id, {}),
            }
            for r in rows
        ]

    def input(
        self,
        plan_id: int,
        day: date,
        workloads: dict[int, int] | None = None,
        exclude_schedule_id: int | None = None,
    ) -> SchedulingInput:
        tags, roads, _, _ = self.requirements(plan_id, day)
        blocked = self.db.scalars(
            select(ResourceUnavailability).where(
                ResourceUnavailability.start_date <= day, ResourceUnavailability.end_date >= day
            )
        ).all()
        blocked_drivers = {r.driver_id for r in blocked if r.driver_id is not None}
        blocked_vehicles = {r.vehicle_id for r in blocked if r.vehicle_id is not None}
        shifts = {s.id: s for s in self.db.scalars(select(Shift).order_by(Shift.id))}
        qualifications: dict[int, list[str]] = {}
        for row in self.db.scalars(select(DriverShiftQualification)):
            if shifts[row.shift_id].enabled:
                qualifications.setdefault(row.driver_id, []).append(shifts[row.shift_id].code)
        capacities: dict[int, dict] = {}
        for row in self.db.scalars(select(VehicleShiftCapacity)):
            if shifts[row.shift_id].enabled:
                capacities.setdefault(row.vehicle_id, {})[shifts[row.shift_id].code] = {
                    'TAG': row.max_tag_count,
                    'ROAD': row.max_road_meters,
                }
        drivers = [
            DriverResource(d.id, d.name, d.efficiency_level, tuple(qualifications.get(d.id, [])))
            for d in self.db.scalars(select(Driver).where(Driver.status == 'ACTIVE').order_by(Driver.id))
            if d.id not in blocked_drivers
        ]
        vehicles = [
            VehicleResource(v.id, v.vehicle_name, v.plate_number, capacities.get(v.id, {}))
            for v in self.db.scalars(select(Vehicle).where(Vehicle.status == 'ACTIVE').order_by(Vehicle.id))
            if v.id not in blocked_vehicles
        ]
        return SchedulingInput(
            day.isoformat(),
            tags,
            roads,
            drivers,
            vehicles,
            self.assignments(day, day, exclude_schedule_id),
            workloads or {},
            tuple(s.code for s in shifts.values() if s.enabled),
        )

    def workloads(self, start: date, end: date) -> dict[int, int]:
        return dict(Counter(item['driver_id'] for item in self.assignments(start, end)))
