from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models import (
    Driver,
    DriverShiftQualification,
    ResourceUnavailability,
    ScheduleAssignment,
    Shift,
    Vehicle,
    VehicleShiftCapacity,
)
from app.repositories.scheduling_repository import require
from app.schemas import (
    DriverCreate,
    ShiftUpdate,
    UnavailabilityCreate,
    VehicleCreate,
    km_to_meters,
    meters_to_km,
)
from app.services.audit_service import audit


class ResourceService:
    def __init__(self, db: Session):
        self.db = db

    def shifts(self) -> list[dict]:
        return [
            {
                'id': s.id,
                'code': s.code,
                'name': s.name,
                'start_time': s.start_time,
                'end_time': s.end_time,
                'enabled': s.enabled,
            }
            for s in self.db.scalars(select(Shift).order_by(Shift.id))
        ]

    def update_shift(self, code: str, payload: ShiftUpdate) -> dict:
        row = self.db.scalar(select(Shift).where(Shift.code == code))
        if row is None:
            raise BusinessError('NOT_FOUND', '班次不存在', 404)
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        audit(self.db, 'UPDATE_SHIFT', 'shift', row.id, after=payload.model_dump())
        self.db.flush()
        return next(s for s in self.shifts() if s['code'] == code)

    def drivers(self) -> list[dict]:
        shifts = {r.id: r.code for r in self.db.scalars(select(Shift))}
        quals: dict[int, list] = {}
        for q in self.db.scalars(select(DriverShiftQualification)):
            quals.setdefault(q.driver_id, []).append(shifts[q.shift_id])
        return [
            {
                'id': d.id,
                'name': d.name,
                'phone': d.phone,
                'efficiency_level': d.efficiency_level,
                'status': d.status,
                'available_shifts': quals.get(d.id, []),
            }
            for d in self.db.scalars(select(Driver).order_by(Driver.id))
        ]

    def vehicles(self) -> list[dict]:
        shifts = {r.id: r.code for r in self.db.scalars(select(Shift))}
        capacities: dict[int, list] = {}
        for c in self.db.scalars(select(VehicleShiftCapacity)):
            capacities.setdefault(c.vehicle_id, []).append(
                {
                    'shift': shifts[c.shift_id],
                    'max_tag_count': c.max_tag_count,
                    'max_road_km': meters_to_km(c.max_road_meters),
                }
            )
        return [
            {
                'id': v.id,
                'plate_number': v.plate_number,
                'vehicle_name': v.vehicle_name,
                'status': v.status,
                'capacities': capacities.get(v.id, []),
            }
            for v in self.db.scalars(select(Vehicle).order_by(Vehicle.id))
        ]

    def save_driver(self, payload: DriverCreate, identifier: int | None = None) -> dict:
        row = require(self.db, Driver, identifier) if identifier else Driver()
        before = next((d for d in self.drivers() if d['id'] == identifier), None)
        for key, value in payload.model_dump(exclude={'available_shifts'}).items():
            setattr(row, key, value)
        self.db.add(row)
        self.db.flush()
        self.db.execute(delete(DriverShiftQualification).where(DriverShiftQualification.driver_id == row.id))
        for shift in self.db.scalars(select(Shift).where(Shift.code.in_(payload.available_shifts))):
            self.db.add(DriverShiftQualification(driver_id=row.id, shift_id=shift.id))
        audit(
            self.db,
            'UPDATE_DRIVER' if identifier else 'CREATE_DRIVER',
            'driver',
            row.id,
            before,
            payload.model_dump(mode='json'),
        )
        self.db.flush()
        return next(d for d in self.drivers() if d['id'] == row.id)

    def save_vehicle(self, payload: VehicleCreate, identifier: int | None = None) -> dict:
        duplicate = self.db.scalar(select(Vehicle).where(Vehicle.plate_number == payload.plate_number))
        if duplicate and duplicate.id != identifier:
            raise BusinessError('DUPLICATE_PLATE', '该车牌号已存在')
        row = require(self.db, Vehicle, identifier) if identifier else Vehicle()
        before = next((v for v in self.vehicles() if v['id'] == identifier), None)
        for key, value in payload.model_dump(exclude={'capacities'}).items():
            setattr(row, key, value)
        self.db.add(row)
        self.db.flush()
        self.db.execute(delete(VehicleShiftCapacity).where(VehicleShiftCapacity.vehicle_id == row.id))
        shifts = {s.code: s.id for s in self.db.scalars(select(Shift))}
        for item in payload.capacities:
            self.db.add(
                VehicleShiftCapacity(
                    vehicle_id=row.id,
                    shift_id=shifts[item.shift],
                    max_tag_count=item.max_tag_count,
                    max_road_meters=km_to_meters(item.max_road_km),
                )
            )
        audit(
            self.db,
            'UPDATE_VEHICLE' if identifier else 'CREATE_VEHICLE',
            'vehicle',
            row.id,
            before,
            payload.model_dump(mode='json'),
        )
        self.db.flush()
        return next(v for v in self.vehicles() if v['id'] == row.id)

    def unavailability(self, kind: str, identifier: int) -> list[dict]:
        require(self.db, Driver if kind == 'driver' else Vehicle, identifier)
        field = ResourceUnavailability.driver_id if kind == 'driver' else ResourceUnavailability.vehicle_id
        return [
            {
                'id': r.id,
                'start_date': r.start_date.isoformat(),
                'end_date': r.end_date.isoformat(),
                'reason': r.reason,
            }
            for r in self.db.scalars(
                select(ResourceUnavailability)
                .where(field == identifier)
                .order_by(ResourceUnavailability.start_date)
            )
        ]

    def add_unavailability(self, kind: str, identifier: int, payload: UnavailabilityCreate) -> dict:
        require(self.db, Driver if kind == 'driver' else Vehicle, identifier)
        field = ScheduleAssignment.driver_id if kind == 'driver' else ScheduleAssignment.vehicle_id
        if self.db.scalar(
            select(ScheduleAssignment.id)
            .where(
                field == identifier,
                ScheduleAssignment.work_date.between(payload.start_date, payload.end_date),
                ScheduleAssignment.status == 'ACTIVE',
            )
            .limit(1)
        ):
            raise BusinessError('CONFIRMED_RESOURCE_IN_USE', '该资源在所选日期已有正式排班，不能登记不可用')
        row = ResourceUnavailability(**{f'{kind}_id': identifier}, **payload.model_dump())
        self.db.add(row)
        self.db.flush()
        audit(self.db, 'ADD_UNAVAILABILITY', kind, identifier, after=payload.model_dump(mode='json'))
        return {'id': row.id, **payload.model_dump(mode='json')}

    def delete_unavailability(self, identifier: int) -> None:
        row = require(self.db, ResourceUnavailability, identifier)
        audit(self.db, 'DELETE_UNAVAILABILITY', 'unavailability', identifier)
        self.db.delete(row)

    def available(
        self, kind: str, day: date, shift: str | None = None, mode: str | None = None
    ) -> list[dict]:
        rows = self.drivers() if kind == 'driver' else self.vehicles()
        field = ResourceUnavailability.driver_id if kind == 'driver' else ResourceUnavailability.vehicle_id
        blocked = set(
            self.db.scalars(
                select(field).where(
                    ResourceUnavailability.start_date <= day, ResourceUnavailability.end_date >= day
                )
            )
        )
        assignments = self.db.scalars(
            select(ScheduleAssignment).where(
                ScheduleAssignment.work_date == day, ScheduleAssignment.status == 'ACTIVE'
            )
        ).all()
        shifts = {s.id: s.code for s in self.db.scalars(select(Shift).where(Shift.enabled.is_(True)))}
        result = []
        for row in rows:
            if row['status'] != 'ACTIVE' or row['id'] in blocked:
                continue
            if kind == 'driver':
                if any(a.driver_id == row['id'] for a in assignments):
                    continue
                available_shifts = [s for s in row['available_shifts'] if s in shifts.values()]
            else:
                own = [a for a in assignments if a.vehicle_id == row['id']]
                if mode and any(a.task_mode != mode for a in own):
                    continue
                occupied = {shifts.get(a.shift_id) for a in own}
                available_shifts = [
                    c['shift']
                    for c in row['capacities']
                    if c['shift'] in shifts.values()
                    and c['shift'] not in occupied
                    and (
                        c['max_tag_count'] > 0
                        if mode == 'TAG'
                        else km_to_meters(c['max_road_km']) > 0
                        if mode == 'ROAD'
                        else c['max_tag_count'] > 0 or km_to_meters(c['max_road_km']) > 0
                    )
                ]
            if available_shifts and (shift is None or shift in available_shifts):
                result.append({**row, 'available_shifts_on_date': available_shifts})
        return result


class DriverService(ResourceService):
    pass


class VehicleService(ResourceService):
    pass
