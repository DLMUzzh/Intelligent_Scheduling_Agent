from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Driver(TimestampMixin, Base):
    __tablename__ = 'drivers'
    __table_args__ = (
        CheckConstraint("efficiency_level IN ('HIGH','MEDIUM','LOW')"),
        CheckConstraint("status IN ('ACTIVE','DISABLED')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(40), default='')
    efficiency_level: Mapped[str] = mapped_column(String(10), default='MEDIUM')
    status: Mapped[str] = mapped_column(String(10), default='ACTIVE')


class Vehicle(TimestampMixin, Base):
    __tablename__ = 'vehicles'
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','DISABLED')"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(30), unique=True)
    vehicle_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10), default='ACTIVE')


class Shift(Base):
    __tablename__ = 'shifts'
    __table_args__ = (CheckConstraint("code IN ('MORNING','AFTERNOON','NIGHT')"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(15), unique=True)
    name: Mapped[str] = mapped_column(String(30))
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class DriverShiftQualification(Base):
    __tablename__ = 'driver_shift_qualifications'
    driver_id: Mapped[int] = mapped_column(ForeignKey('drivers.id'), primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey('shifts.id'), primary_key=True)


class VehicleShiftCapacity(Base):
    __tablename__ = 'vehicle_shift_capacities'
    __table_args__ = (
        UniqueConstraint('vehicle_id', 'shift_id'),
        CheckConstraint('max_tag_count >= 0 AND max_road_meters >= 0'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey('vehicles.id'))
    shift_id: Mapped[int] = mapped_column(ForeignKey('shifts.id'))
    max_tag_count: Mapped[int] = mapped_column(Integer)
    max_road_meters: Mapped[int] = mapped_column(Integer)


class ResourceUnavailability(Base):
    __tablename__ = 'resource_unavailability'
    __table_args__ = (
        CheckConstraint(
            '(driver_id IS NOT NULL AND vehicle_id IS NULL) OR (driver_id IS NULL AND vehicle_id IS NOT NULL)'
        ),
        CheckConstraint('end_date >= start_date'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey('drivers.id'))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey('vehicles.id'))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(200), default='')


class CollectionPlan(TimestampMixin, Base):
    __tablename__ = 'collection_plans'
    __table_args__ = (CheckConstraint('end_date >= start_date'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(30), default='CREATED')
    version: Mapped[int] = mapped_column(Integer, default=1)


class PlanTagRequirement(Base):
    __tablename__ = 'plan_tag_requirements'
    __table_args__ = (UniqueConstraint('plan_id', 'tag_type'), CheckConstraint('daily_target_count > 0'))
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('collection_plans.id'))
    tag_type: Mapped[str] = mapped_column(String(80))
    daily_target_count: Mapped[int] = mapped_column(Integer)


class PlanRoadRequirement(Base):
    __tablename__ = 'plan_road_requirements'
    __table_args__ = (UniqueConstraint('plan_id', 'road_type'), CheckConstraint('daily_target_meters > 0'))
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('collection_plans.id'))
    road_type: Mapped[str] = mapped_column(String(80))
    daily_target_meters: Mapped[int] = mapped_column(Integer)


class DailyTask(Base):
    __tablename__ = 'daily_tasks'
    __table_args__ = (UniqueConstraint('plan_id', 'work_date'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('collection_plans.id'))
    work_date: Mapped[date] = mapped_column(Date, index=True)


class DailyTagRequirement(Base):
    __tablename__ = 'daily_tag_requirements'
    __table_args__ = (UniqueConstraint('daily_task_id', 'tag_type'), CheckConstraint('target_count > 0'))
    id: Mapped[int] = mapped_column(primary_key=True)
    daily_task_id: Mapped[int] = mapped_column(ForeignKey('daily_tasks.id'))
    tag_type: Mapped[str] = mapped_column(String(80))
    target_count: Mapped[int] = mapped_column(Integer)


class DailyRoadRequirement(Base):
    __tablename__ = 'daily_road_requirements'
    __table_args__ = (UniqueConstraint('daily_task_id', 'road_type'), CheckConstraint('target_meters > 0'))
    id: Mapped[int] = mapped_column(primary_key=True)
    daily_task_id: Mapped[int] = mapped_column(ForeignKey('daily_tasks.id'))
    road_type: Mapped[str] = mapped_column(String(80))
    target_meters: Mapped[int] = mapped_column(Integer)


class SchedulePreview(TimestampMixin, Base):
    __tablename__ = 'schedule_previews'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('collection_plans.id'), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    algorithm_name: Mapped[str] = mapped_column(String(30))
    preview_version: Mapped[int] = mapped_column(Integer, default=1)
    preview_content: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default='PENDING')
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class PreviewDayClaim(Base):
    """A pending preview owns the plan/day, but does not reserve fleet resources."""

    __tablename__ = 'preview_day_claims'
    plan_id: Mapped[int] = mapped_column(ForeignKey('collection_plans.id'), primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, primary_key=True)
    preview_id: Mapped[str] = mapped_column(ForeignKey('schedule_previews.id'))


class DailySchedule(Base):
    __tablename__ = 'daily_schedules'
    __table_args__ = (UniqueConstraint('plan_id', 'schedule_date'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('collection_plans.id'))
    schedule_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default='CONFIRMED')
    version: Mapped[int] = mapped_column(Integer)
    algorithm_name: Mapped[str] = mapped_column(String(30))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScheduleAssignment(TimestampMixin, Base):
    __tablename__ = 'schedule_assignments'
    __table_args__ = (
        UniqueConstraint('work_date', 'driver_id'),
        UniqueConstraint('work_date', 'vehicle_id', 'shift_id'),
        CheckConstraint("task_mode IN ('TAG','ROAD')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey('daily_schedules.id'))
    work_date: Mapped[date] = mapped_column(Date, index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey('vehicles.id'))
    driver_id: Mapped[int] = mapped_column(ForeignKey('drivers.id'))
    shift_id: Mapped[int] = mapped_column(ForeignKey('shifts.id'))
    task_mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(15), default='ACTIVE')


class AssignmentTagAllocation(Base):
    __tablename__ = 'assignment_tag_allocations'
    __table_args__ = (
        UniqueConstraint('assignment_id', 'daily_tag_requirement_id'),
        CheckConstraint('assigned_count > 0'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('schedule_assignments.id'))
    daily_tag_requirement_id: Mapped[int] = mapped_column(ForeignKey('daily_tag_requirements.id'))
    assigned_count: Mapped[int] = mapped_column(Integer)


class AssignmentRoadAllocation(Base):
    __tablename__ = 'assignment_road_allocations'
    __table_args__ = (
        UniqueConstraint('assignment_id', 'daily_road_requirement_id'),
        CheckConstraint('assigned_meters > 0'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('schedule_assignments.id'))
    daily_road_requirement_id: Mapped[int] = mapped_column(ForeignKey('daily_road_requirements.id'))
    assigned_meters: Mapped[int] = mapped_column(Integer)


class VehicleDayMode(Base):
    __tablename__ = 'vehicle_day_modes'
    __table_args__ = (CheckConstraint("task_mode IN ('TAG','ROAD')"),)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey('vehicles.id'), primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, primary_key=True)
    task_mode: Mapped[str] = mapped_column(String(10))


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('schedule_assignments.id'))
    driver_id: Mapped[int] = mapped_column(ForeignKey('drivers.id'))
    notification_type: Mapped[str] = mapped_column(String(20), default='SCHEDULE_CONFIRMED')
    schedule_version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default='PENDING', index=True)
    idempotency_key: Mapped[str] = mapped_column(String(150), unique=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConfirmationOperation(Base):
    __tablename__ = 'confirmation_operations'
    idempotency_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_type: Mapped[str] = mapped_column(String(20), default='USER')
    operator_id: Mapped[str] = mapped_column(String(80), default='local-manager')
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(80))
    before_data: Mapped[dict | None] = mapped_column(JSON)
    after_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


Index(
    'ix_unavailable_driver_dates',
    ResourceUnavailability.driver_id,
    ResourceUnavailability.start_date,
    ResourceUnavailability.end_date,
)
Index(
    'ix_unavailable_vehicle_dates',
    ResourceUnavailability.vehicle_id,
    ResourceUnavailability.start_date,
    ResourceUnavailability.end_date,
)
