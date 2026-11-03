"""New-version ORM mapping. Schema and constraints follow the approved 13-table SQL."""

from sqlalchemy import CheckConstraint, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class FoundationBase(DeclarativeBase):
    pass


class AuditLog(FoundationBase):
    __tablename__ = 'audit_logs'
    __table_args__ = (
        CheckConstraint('plan_day_id > 0'),
        CheckConstraint('formal_version >= 1'),
        CheckConstraint("formal_change_type IN ('INITIAL_CONFIRM', 'MODIFY', 'CANCEL', 'RECONFIRM')"),
        CheckConstraint('snapshot_schema_version >= 1'),
        CheckConstraint('business_operation_id > 0'),
        CheckConstraint("actor_code = 'LOCAL_CAPTAIN'"),
        CheckConstraint('length(trim(actor_name_snapshot)) > 0'),
        CheckConstraint("entry_source IN ('PAGE', 'AGENT')"),
        CheckConstraint('length(trim(action_code)) > 0'),
        CheckConstraint('length(trim(target_type)) > 0'),
        CheckConstraint('target_id > 0'),
        CheckConstraint('length(trim(target_label_snapshot)) > 0'),
        CheckConstraint("outcome IN ('SUCCEEDED', 'FAILED')"),
        CheckConstraint(
            "CASE WHEN json_valid(changes_json) THEN json_type(changes_json) = 'object' ELSE 0 END"
        ),
        CheckConstraint("outcome != 'FAILED' OR (reason IS NOT NULL AND length(trim(reason)) > 0)"),
        CheckConstraint(
            "(plan_day_id IS NULL AND formal_version IS NULL AND formal_change_type IS NULL)\n        OR (plan_day_id IS NOT NULL AND formal_version IS NOT NULL AND formal_change_type IS NOT NULL\n            AND outcome = 'SUCCEEDED' AND business_operation_id IS NOT NULL)"
        ),
        CheckConstraint(
            "formal_change_type IS NULL\n        OR (formal_change_type = 'INITIAL_CONFIRM' AND formal_version = 1)\n        OR (formal_change_type != 'INITIAL_CONFIRM' AND formal_version > 1)"
        ),
        UniqueConstraint('plan_day_id', 'formal_version'),
        Index('ix_audit_logs_created_at', 'created_at', 'id'),
        Index('ix_audit_logs_operation_id', 'business_operation_id'),
        Index('ix_audit_logs_target_created_at', 'target_type', 'target_id', 'created_at'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_day_id: Mapped[int | None] = mapped_column(Integer)
    formal_version: Mapped[int | None] = mapped_column(Integer)
    formal_change_type: Mapped[str | None] = mapped_column(Text)
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    business_operation_id: Mapped[int | None] = mapped_column(Integer)
    actor_code: Mapped[str] = mapped_column(Text, server_default=text("'LOCAL_CAPTAIN'"))
    actor_name_snapshot: Mapped[str] = mapped_column(Text, server_default=text("'车队长'"))
    entry_source: Mapped[str] = mapped_column(Text)
    action_code: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    target_label_snapshot: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    changes_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class BusinessOperation(FoundationBase):
    __tablename__ = 'business_operations'
    __table_args__ = (
        CheckConstraint('length(trim(request_key)) > 0'),
        CheckConstraint("length(request_hash) = 64 AND request_hash NOT GLOB '*[^0-9a-f]*'"),
        CheckConstraint(
            "action_code IN (\n        'CREATE_CATEGORY', 'UPDATE_CATEGORY', 'DELETE_CATEGORY',\n        'CREATE_PLAN', 'UPDATE_PLAN', 'DELETE_PLAN', 'UPDATE_DEMAND',\n        'CREATE_DRIVER', 'UPDATE_DRIVER', 'DELETE_DRIVER',\n        'CREATE_VEHICLE', 'UPDATE_VEHICLE', 'DELETE_VEHICLE',\n        'CREATE_UNAVAILABILITY', 'UPDATE_UNAVAILABILITY', 'DELETE_UNAVAILABILITY',\n        'GENERATE_DRAFT', 'SAVE_DRAFT', 'CONFIRM_PLAN', 'MODIFY_FORMAL_DAY', 'CANCEL_FORMAL_DAY')"
        ),
        CheckConstraint("entry_source IN ('PAGE', 'AGENT')"),
        CheckConstraint("actor_code = 'LOCAL_CAPTAIN'"),
        CheckConstraint(
            "target_type IN ('CATEGORY', 'PLAN', 'PLAN_DAY', 'DRIVER', 'VEHICLE', 'UNAVAILABILITY', 'DRAFT', 'FORMAL_DAY')"
        ),
        CheckConstraint('target_id > 0'),
        CheckConstraint('payload_schema_version >= 1'),
        CheckConstraint(
            "CASE WHEN json_valid(request_payload_json) THEN json_type(request_payload_json) = 'object' ELSE 0 END"
        ),
        CheckConstraint(
            "CASE WHEN json_valid(expected_versions_json) THEN json_type(expected_versions_json) = 'object' ELSE 0 END"
        ),
        CheckConstraint(
            "CASE WHEN json_valid(summary_json) THEN json_type(summary_json) = 'object' ELSE 0 END"
        ),
        CheckConstraint('requires_confirmation IN (0, 1)'),
        CheckConstraint("status IN ('PENDING', 'SUCCEEDED', 'FAILED')"),
        CheckConstraint(
            "CASE WHEN result_json IS NULL THEN 1 WHEN json_valid(result_json) THEN json_type(result_json) = 'object' ELSE 0 END"
        ),
        CheckConstraint(
            "(status = 'PENDING' AND result_code IS NULL AND result_json IS NULL AND error_message IS NULL AND finished_at IS NULL)\n        OR (status = 'SUCCEEDED' AND result_code IS NOT NULL AND result_json IS NOT NULL AND error_message IS NULL AND finished_at IS NOT NULL)\n        OR (status = 'FAILED' AND result_code IS NOT NULL AND result_json IS NOT NULL AND error_message IS NOT NULL AND finished_at IS NOT NULL)"
        ),
        CheckConstraint("status != 'SUCCEEDED' OR requires_confirmation = 0 OR confirmed_at IS NOT NULL"),
        UniqueConstraint('request_key'),
        Index('ix_business_operations_status_created_at', 'status', 'created_at'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_key: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    action_code: Mapped[str] = mapped_column(Text)
    entry_source: Mapped[str] = mapped_column(Text)
    actor_code: Mapped[str] = mapped_column(Text, server_default=text("'LOCAL_CAPTAIN'"))
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(Integer)
    payload_schema_version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    request_payload_json: Mapped[str] = mapped_column(Text)
    expected_versions_json: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[str] = mapped_column(Text)
    requires_confirmation: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    result_code: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class BusinessState(FoundationBase):
    __tablename__ = 'business_state'
    __table_args__ = (
        CheckConstraint("state_key = 'MAIN'"),
        CheckConstraint('revision >= 1'),
        UniqueConstraint('state_key'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state_key: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class CollectionCategory(FoundationBase):
    __tablename__ = 'collection_categories'
    __table_args__ = (
        CheckConstraint("task_mode IN ('TAG', 'ROAD')"),
        CheckConstraint('length(trim(name)) > 0 AND name = trim(name)'),
        CheckConstraint('version >= 1'),
        UniqueConstraint('task_mode', 'name'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_mode: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class CollectionPlan(FoundationBase):
    __tablename__ = 'collection_plans'
    __table_args__ = (
        CheckConstraint('length(trim(name)) > 0'),
        CheckConstraint(
            "length(start_date) = 10 AND start_date >= '0001-01-01' AND date(start_date, '+0 days') IS start_date"
        ),
        CheckConstraint(
            "length(end_date) = 10 AND end_date >= '0001-01-01' AND date(end_date, '+0 days') IS end_date"
        ),
        CheckConstraint('version >= 1'),
        CheckConstraint('end_date >= start_date'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    start_date: Mapped[str] = mapped_column(Text)
    end_date: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class DailyDemand(FoundationBase):
    __tablename__ = 'daily_demands'
    __table_args__ = (
        CheckConstraint('plan_day_id > 0'),
        CheckConstraint('collection_category_id > 0'),
        CheckConstraint('length(trim(category_name_snapshot)) > 0'),
        CheckConstraint("task_mode IN ('TAG', 'ROAD')"),
        CheckConstraint('sort_order >= 1'),
        CheckConstraint(
            "(task_mode = 'TAG' AND target_tag_count IS NOT NULL AND target_tag_count > 0 AND target_road_meters IS NULL)\n        OR (task_mode = 'ROAD' AND target_road_meters IS NOT NULL AND target_road_meters > 0 AND target_tag_count IS NULL)"
        ),
        UniqueConstraint('plan_day_id', 'collection_category_id'),
        UniqueConstraint('plan_day_id', 'task_mode', 'sort_order'),
        Index('ix_daily_demands_category_id', 'collection_category_id'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_day_id: Mapped[int] = mapped_column(Integer)
    collection_category_id: Mapped[int] = mapped_column(Integer)
    category_name_snapshot: Mapped[str] = mapped_column(Text)
    task_mode: Mapped[str] = mapped_column(Text)
    target_tag_count: Mapped[int | None] = mapped_column(Integer)
    target_road_meters: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class Driver(FoundationBase):
    __tablename__ = 'drivers'
    __table_args__ = (
        CheckConstraint('length(trim(name)) > 0'),
        CheckConstraint("efficiency_level IN ('HIGH', 'MEDIUM', 'LOW')"),
        CheckConstraint('is_enabled IN (0, 1)'),
        CheckConstraint('can_morning IN (0, 1)'),
        CheckConstraint('can_middle IN (0, 1)'),
        CheckConstraint('can_evening IN (0, 1)'),
        CheckConstraint('version >= 1'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    efficiency_level: Mapped[str] = mapped_column(Text, server_default=text("'MEDIUM'"))
    is_enabled: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    can_morning: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    can_middle: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    can_evening: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class PlanDay(FoundationBase):
    __tablename__ = 'plan_days'
    __table_args__ = (
        CheckConstraint('collection_plan_id > 0'),
        CheckConstraint(
            "length(work_date) = 10 AND work_date >= '0001-01-01' AND date(work_date, '+0 days') IS work_date"
        ),
        CheckConstraint('version >= 1'),
        CheckConstraint("formal_status IN ('NONE', 'ACTIVE', 'CANCELLED')"),
        CheckConstraint('formal_version >= 0'),
        CheckConstraint(
            "CASE WHEN draft_metadata_json IS NULL THEN 1 WHEN json_valid(draft_metadata_json) THEN json_type(draft_metadata_json) = 'object' ELSE 0 END"
        ),
        CheckConstraint(
            "CASE WHEN json_valid(vehicle_capacities_json) THEN json_type(vehicle_capacities_json) = 'array' ELSE 0 END"
        ),
        CheckConstraint('capacity_basis_revision >= 1'),
        CheckConstraint(
            "(formal_status = 'NONE' AND formal_version = 0) OR (formal_status != 'NONE' AND formal_version >= 1)"
        ),
        CheckConstraint("formal_status != 'ACTIVE' OR draft_metadata_json IS NULL"),
        UniqueConstraint('work_date'),
        Index('ix_plan_days_collection_plan_id', 'collection_plan_id'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_plan_id: Mapped[int] = mapped_column(Integer)
    work_date: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    formal_status: Mapped[str] = mapped_column(Text, server_default=text("'NONE'"))
    formal_version: Mapped[int] = mapped_column(Integer, server_default=text('0'))
    draft_metadata_json: Mapped[str | None] = mapped_column(Text)
    vehicle_capacities_json: Mapped[str] = mapped_column(Text)
    capacity_basis_revision: Mapped[int] = mapped_column(Integer)
    capacity_captured_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class ResourceUnavailability(FoundationBase):
    __tablename__ = 'resource_unavailability'
    __table_args__ = (
        CheckConstraint('driver_id > 0'),
        CheckConstraint('vehicle_id > 0'),
        CheckConstraint(
            "length(start_date) = 10 AND start_date >= '0001-01-01' AND date(start_date, '+0 days') IS start_date"
        ),
        CheckConstraint(
            "length(end_date) = 10 AND end_date >= '0001-01-01' AND date(end_date, '+0 days') IS end_date"
        ),
        CheckConstraint('version >= 1'),
        CheckConstraint(
            '(driver_id IS NOT NULL AND vehicle_id IS NULL) OR (vehicle_id IS NOT NULL AND driver_id IS NULL)'
        ),
        CheckConstraint('end_date >= start_date'),
        Index(
            'ix_unavailability_driver_dates',
            'driver_id',
            'start_date',
            'end_date',
            sqlite_where=text('driver_id IS NOT NULL'),
        ),
        Index(
            'ix_unavailability_vehicle_dates',
            'vehicle_id',
            'start_date',
            'end_date',
            sqlite_where=text('vehicle_id IS NOT NULL'),
        ),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    driver_id: Mapped[int | None] = mapped_column(Integer)
    vehicle_id: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[str] = mapped_column(Text)
    end_date: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )


class SchemaMigration(FoundationBase):
    __tablename__ = 'schema_migrations'
    __table_args__ = (
        CheckConstraint('length(trim(version_num)) > 0'),
        UniqueConstraint('version_num'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_num: Mapped[str] = mapped_column(Text)


class TaskAllocation(FoundationBase):
    __tablename__ = 'task_allocations'
    __table_args__ = (
        CheckConstraint('task_package_id > 0'),
        CheckConstraint('collection_category_id > 0'),
        CheckConstraint('length(trim(category_name_snapshot)) > 0'),
        CheckConstraint("task_mode IN ('TAG', 'ROAD')"),
        CheckConstraint(
            "(task_mode = 'TAG' AND assigned_tag_count IS NOT NULL AND assigned_tag_count > 0 AND assigned_road_meters IS NULL)\n        OR (task_mode = 'ROAD' AND assigned_road_meters IS NOT NULL AND assigned_road_meters > 0 AND assigned_tag_count IS NULL)"
        ),
        UniqueConstraint('task_package_id', 'collection_category_id'),
        Index('ix_task_allocations_category_id', 'collection_category_id'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_package_id: Mapped[int] = mapped_column(Integer)
    collection_category_id: Mapped[int] = mapped_column(Integer)
    category_name_snapshot: Mapped[str] = mapped_column(Text)
    task_mode: Mapped[str] = mapped_column(Text)
    assigned_tag_count: Mapped[int | None] = mapped_column(Integer)
    assigned_road_meters: Mapped[int | None] = mapped_column(Integer)


class TaskPackage(FoundationBase):
    __tablename__ = 'task_packages'
    __table_args__ = (
        CheckConstraint('plan_day_id > 0'),
        CheckConstraint(
            "length(work_date) = 10 AND work_date >= '0001-01-01' AND date(work_date, '+0 days') IS work_date"
        ),
        CheckConstraint("schedule_kind IN ('DRAFT', 'FORMAL')"),
        CheckConstraint('driver_id > 0'),
        CheckConstraint('vehicle_id > 0'),
        CheckConstraint("shift_code IN ('MORNING', 'MIDDLE', 'EVENING')"),
        CheckConstraint("task_mode IN ('TAG', 'ROAD')"),
        CheckConstraint('length(trim(driver_name_snapshot)) > 0'),
        CheckConstraint("efficiency_level_snapshot IN ('HIGH', 'MEDIUM', 'LOW')"),
        CheckConstraint('length(trim(plate_number_snapshot)) > 0'),
        CheckConstraint('max_tag_count_snapshot >= 0'),
        CheckConstraint('max_road_meters_snapshot >= 0'),
        CheckConstraint(
            "(task_mode = 'TAG' AND max_tag_count_snapshot > 0) OR (task_mode = 'ROAD' AND max_road_meters_snapshot > 0)"
        ),
        UniqueConstraint('schedule_kind', 'work_date', 'driver_id'),
        UniqueConstraint('schedule_kind', 'work_date', 'vehicle_id', 'shift_code'),
        Index('ix_task_packages_day_kind', 'plan_day_id', 'schedule_kind'),
        Index('ix_task_packages_driver_kind_date', 'driver_id', 'schedule_kind', 'work_date'),
        Index('ix_task_packages_vehicle_kind_date', 'vehicle_id', 'schedule_kind', 'work_date'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_day_id: Mapped[int] = mapped_column(Integer)
    work_date: Mapped[str] = mapped_column(Text)
    schedule_kind: Mapped[str] = mapped_column(Text)
    driver_id: Mapped[int] = mapped_column(Integer)
    vehicle_id: Mapped[int] = mapped_column(Integer)
    shift_code: Mapped[str] = mapped_column(Text)
    task_mode: Mapped[str] = mapped_column(Text)
    driver_name_snapshot: Mapped[str] = mapped_column(Text)
    efficiency_level_snapshot: Mapped[str] = mapped_column(Text)
    plate_number_snapshot: Mapped[str] = mapped_column(Text)
    vehicle_name_snapshot: Mapped[str | None] = mapped_column(Text)
    max_tag_count_snapshot: Mapped[int] = mapped_column(Integer)
    max_road_meters_snapshot: Mapped[int] = mapped_column(Integer)


class Vehicle(FoundationBase):
    __tablename__ = 'vehicles'
    __table_args__ = (
        CheckConstraint('length(trim(plate_number)) > 0'),
        CheckConstraint('length(trim(plate_key)) > 0'),
        CheckConstraint('morning_max_tag_count >= 0'),
        CheckConstraint('morning_max_road_meters >= 0'),
        CheckConstraint('middle_max_tag_count >= 0'),
        CheckConstraint('middle_max_road_meters >= 0'),
        CheckConstraint('evening_max_tag_count >= 0'),
        CheckConstraint('evening_max_road_meters >= 0'),
        CheckConstraint('is_enabled IN (0, 1)'),
        CheckConstraint('version >= 1'),
        UniqueConstraint('plate_key'),
        {'sqlite_strict': True, 'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate_number: Mapped[str] = mapped_column(Text)
    plate_key: Mapped[str] = mapped_column(Text)
    morning_max_tag_count: Mapped[int] = mapped_column(Integer)
    morning_max_road_meters: Mapped[int] = mapped_column(Integer)
    middle_max_tag_count: Mapped[int] = mapped_column(Integer)
    middle_max_road_meters: Mapped[int] = mapped_column(Integer)
    evening_max_tag_count: Mapped[int] = mapped_column(Integer)
    evening_max_road_meters: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    version: Mapped[int] = mapped_column(Integer, server_default=text('1'))
    created_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, server_default=text("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    )
