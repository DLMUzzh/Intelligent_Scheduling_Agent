-- 司机智能排班 Agent：第三阶段 13 表数据库设计，2026-11-02 用户审核通过。
-- 仅用于新的空 SQLite 数据库；不是旧库迁移或生产升级脚本。
-- SQLite >= 3.38，须支持 STRICT 表与 JSON 函数。不得创建物理外键。
-- 执行器必须遇错立即停止并 ROLLBACK；不使用 IF NOT EXISTS 掩盖结构差异。
-- 运行时每个连接亦须配置同步与有限锁等待；本脚本不确定 busy_timeout 数值。
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;

BEGIN IMMEDIATE;

-- 后续 Alembic 使用此版本表；需按文档适配自增 id，不能恢复默认字符串主键。
-- 不在建表脚本中伪造尚未建立的 Alembic 修订号。
CREATE TABLE schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_num TEXT NOT NULL UNIQUE CHECK (length(trim(version_num)) > 0)
) STRICT;

CREATE TABLE business_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_key TEXT NOT NULL UNIQUE CHECK (state_key = 'MAIN'),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE collection_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_mode TEXT NOT NULL CHECK (task_mode IN ('TAG', 'ROAD')),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND name = trim(name)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (task_mode, name)
) STRICT;

CREATE TABLE collection_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    start_date TEXT NOT NULL CHECK (length(start_date) = 10 AND start_date >= '0001-01-01' AND date(start_date, '+0 days') IS start_date),
    end_date TEXT NOT NULL CHECK (length(end_date) = 10 AND end_date >= '0001-01-01' AND date(end_date, '+0 days') IS end_date),
    notes TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (end_date >= start_date)
) STRICT;

CREATE TABLE plan_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_plan_id INTEGER NOT NULL CHECK (collection_plan_id > 0),
    work_date TEXT NOT NULL UNIQUE CHECK (length(work_date) = 10 AND work_date >= '0001-01-01' AND date(work_date, '+0 days') IS work_date),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    formal_status TEXT NOT NULL DEFAULT 'NONE' CHECK (formal_status IN ('NONE', 'ACTIVE', 'CANCELLED')),
    formal_version INTEGER NOT NULL DEFAULT 0 CHECK (formal_version >= 0),
    draft_metadata_json TEXT CHECK (CASE WHEN draft_metadata_json IS NULL THEN 1 WHEN json_valid(draft_metadata_json) THEN json_type(draft_metadata_json) = 'object' ELSE 0 END),
    vehicle_capacities_json TEXT NOT NULL CHECK (CASE WHEN json_valid(vehicle_capacities_json) THEN json_type(vehicle_capacities_json) = 'array' ELSE 0 END),
    capacity_basis_revision INTEGER NOT NULL CHECK (capacity_basis_revision >= 1),
    capacity_captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((formal_status = 'NONE' AND formal_version = 0) OR (formal_status != 'NONE' AND formal_version >= 1)),
    CHECK (formal_status != 'ACTIVE' OR draft_metadata_json IS NULL)
) STRICT;
CREATE INDEX ix_plan_days_collection_plan_id ON plan_days (collection_plan_id);

CREATE TABLE daily_demands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_day_id INTEGER NOT NULL CHECK (plan_day_id > 0),
    collection_category_id INTEGER NOT NULL CHECK (collection_category_id > 0),
    category_name_snapshot TEXT NOT NULL CHECK (length(trim(category_name_snapshot)) > 0),
    task_mode TEXT NOT NULL CHECK (task_mode IN ('TAG', 'ROAD')),
    target_tag_count INTEGER,
    target_road_meters INTEGER,
    sort_order INTEGER NOT NULL CHECK (sort_order >= 1),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (plan_day_id, collection_category_id),
    UNIQUE (plan_day_id, task_mode, sort_order),
    CHECK ((task_mode = 'TAG' AND target_tag_count IS NOT NULL AND target_tag_count > 0 AND target_road_meters IS NULL)
        OR (task_mode = 'ROAD' AND target_road_meters IS NOT NULL AND target_road_meters > 0 AND target_tag_count IS NULL))
) STRICT;
CREATE INDEX ix_daily_demands_category_id ON daily_demands (collection_category_id);

CREATE TABLE drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    phone TEXT,
    efficiency_level TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (efficiency_level IN ('HIGH', 'MEDIUM', 'LOW')),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    can_morning INTEGER NOT NULL DEFAULT 1 CHECK (can_morning IN (0, 1)),
    can_middle INTEGER NOT NULL DEFAULT 1 CHECK (can_middle IN (0, 1)),
    can_evening INTEGER NOT NULL DEFAULT 1 CHECK (can_evening IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number TEXT NOT NULL CHECK (length(trim(plate_number)) > 0),
    plate_key TEXT NOT NULL UNIQUE CHECK (length(trim(plate_key)) > 0),
    morning_max_tag_count INTEGER NOT NULL CHECK (morning_max_tag_count >= 0),
    morning_max_road_meters INTEGER NOT NULL CHECK (morning_max_road_meters >= 0),
    middle_max_tag_count INTEGER NOT NULL CHECK (middle_max_tag_count >= 0),
    middle_max_road_meters INTEGER NOT NULL CHECK (middle_max_road_meters >= 0),
    evening_max_tag_count INTEGER NOT NULL CHECK (evening_max_tag_count >= 0),
    evening_max_road_meters INTEGER NOT NULL CHECK (evening_max_road_meters >= 0),
    name TEXT,
    notes TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE resource_unavailability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER CHECK (driver_id > 0),
    vehicle_id INTEGER CHECK (vehicle_id > 0),
    start_date TEXT NOT NULL CHECK (length(start_date) = 10 AND start_date >= '0001-01-01' AND date(start_date, '+0 days') IS start_date),
    end_date TEXT NOT NULL CHECK (length(end_date) = 10 AND end_date >= '0001-01-01' AND date(end_date, '+0 days') IS end_date),
    reason TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((driver_id IS NOT NULL AND vehicle_id IS NULL) OR (vehicle_id IS NOT NULL AND driver_id IS NULL)),
    CHECK (end_date >= start_date)
) STRICT;
CREATE INDEX ix_unavailability_driver_dates ON resource_unavailability (driver_id, start_date, end_date) WHERE driver_id IS NOT NULL;
CREATE INDEX ix_unavailability_vehicle_dates ON resource_unavailability (vehicle_id, start_date, end_date) WHERE vehicle_id IS NOT NULL;

-- 草稿与当前有效正式排班共用两张明细表，schedule_kind 明确隔离。
-- 查询正式占用必须限定 FORMAL；取消仅删除 FORMAL，旧内容先写入 audit_logs。
CREATE TABLE task_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_day_id INTEGER NOT NULL CHECK (plan_day_id > 0),
    work_date TEXT NOT NULL CHECK (length(work_date) = 10 AND work_date >= '0001-01-01' AND date(work_date, '+0 days') IS work_date),
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('DRAFT', 'FORMAL')),
    driver_id INTEGER NOT NULL CHECK (driver_id > 0),
    vehicle_id INTEGER NOT NULL CHECK (vehicle_id > 0),
    shift_code TEXT NOT NULL CHECK (shift_code IN ('MORNING', 'MIDDLE', 'EVENING')),
    task_mode TEXT NOT NULL CHECK (task_mode IN ('TAG', 'ROAD')),
    driver_name_snapshot TEXT NOT NULL CHECK (length(trim(driver_name_snapshot)) > 0),
    efficiency_level_snapshot TEXT NOT NULL CHECK (efficiency_level_snapshot IN ('HIGH', 'MEDIUM', 'LOW')),
    plate_number_snapshot TEXT NOT NULL CHECK (length(trim(plate_number_snapshot)) > 0),
    vehicle_name_snapshot TEXT,
    max_tag_count_snapshot INTEGER NOT NULL CHECK (max_tag_count_snapshot >= 0),
    max_road_meters_snapshot INTEGER NOT NULL CHECK (max_road_meters_snapshot >= 0),
    UNIQUE (schedule_kind, work_date, driver_id),
    UNIQUE (schedule_kind, work_date, vehicle_id, shift_code),
    CHECK ((task_mode = 'TAG' AND max_tag_count_snapshot > 0) OR (task_mode = 'ROAD' AND max_road_meters_snapshot > 0))
) STRICT;
CREATE INDEX ix_task_packages_day_kind ON task_packages (plan_day_id, schedule_kind);
CREATE INDEX ix_task_packages_driver_kind_date ON task_packages (driver_id, schedule_kind, work_date);
CREATE INDEX ix_task_packages_vehicle_kind_date ON task_packages (vehicle_id, schedule_kind, work_date);

CREATE TABLE task_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_package_id INTEGER NOT NULL CHECK (task_package_id > 0),
    collection_category_id INTEGER NOT NULL CHECK (collection_category_id > 0),
    category_name_snapshot TEXT NOT NULL CHECK (length(trim(category_name_snapshot)) > 0),
    task_mode TEXT NOT NULL CHECK (task_mode IN ('TAG', 'ROAD')),
    assigned_tag_count INTEGER,
    assigned_road_meters INTEGER,
    UNIQUE (task_package_id, collection_category_id),
    CHECK ((task_mode = 'TAG' AND assigned_tag_count IS NOT NULL AND assigned_tag_count > 0 AND assigned_road_meters IS NULL)
        OR (task_mode = 'ROAD' AND assigned_road_meters IS NOT NULL AND assigned_road_meters > 0 AND assigned_tag_count IS NULL))
) STRICT;
CREATE INDEX ix_task_allocations_category_id ON task_allocations (collection_category_id);

CREATE TABLE business_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_key TEXT NOT NULL UNIQUE CHECK (length(trim(request_key)) > 0),
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64 AND request_hash NOT GLOB '*[^0-9a-f]*'),
    action_code TEXT NOT NULL CHECK (action_code IN (
        'CREATE_CATEGORY', 'UPDATE_CATEGORY', 'DELETE_CATEGORY',
        'CREATE_PLAN', 'UPDATE_PLAN', 'DELETE_PLAN', 'UPDATE_DEMAND',
        'CREATE_DRIVER', 'UPDATE_DRIVER', 'DELETE_DRIVER',
        'CREATE_VEHICLE', 'UPDATE_VEHICLE', 'DELETE_VEHICLE',
        'CREATE_UNAVAILABILITY', 'UPDATE_UNAVAILABILITY', 'DELETE_UNAVAILABILITY',
        'GENERATE_DRAFT', 'SAVE_DRAFT', 'CONFIRM_PLAN', 'MODIFY_FORMAL_DAY', 'CANCEL_FORMAL_DAY')),
    entry_source TEXT NOT NULL CHECK (entry_source IN ('PAGE', 'AGENT')),
    actor_code TEXT NOT NULL DEFAULT 'LOCAL_CAPTAIN' CHECK (actor_code = 'LOCAL_CAPTAIN'),
    target_type TEXT NOT NULL CHECK (target_type IN ('CATEGORY', 'PLAN', 'PLAN_DAY', 'DRIVER', 'VEHICLE', 'UNAVAILABILITY', 'DRAFT', 'FORMAL_DAY')),
    target_id INTEGER CHECK (target_id > 0),
    payload_schema_version INTEGER NOT NULL DEFAULT 1 CHECK (payload_schema_version >= 1),
    request_payload_json TEXT NOT NULL CHECK (CASE WHEN json_valid(request_payload_json) THEN json_type(request_payload_json) = 'object' ELSE 0 END),
    expected_versions_json TEXT NOT NULL CHECK (CASE WHEN json_valid(expected_versions_json) THEN json_type(expected_versions_json) = 'object' ELSE 0 END),
    summary_json TEXT NOT NULL CHECK (CASE WHEN json_valid(summary_json) THEN json_type(summary_json) = 'object' ELSE 0 END),
    requires_confirmation INTEGER NOT NULL CHECK (requires_confirmation IN (0, 1)),
    confirmed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED')),
    result_code TEXT,
    result_json TEXT CHECK (CASE WHEN result_json IS NULL THEN 1 WHEN json_valid(result_json) THEN json_type(result_json) = 'object' ELSE 0 END),
    error_message TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((status = 'PENDING' AND result_code IS NULL AND result_json IS NULL AND error_message IS NULL AND finished_at IS NULL)
        OR (status = 'SUCCEEDED' AND result_code IS NOT NULL AND result_json IS NOT NULL AND error_message IS NULL AND finished_at IS NOT NULL)
        OR (status = 'FAILED' AND result_code IS NOT NULL AND result_json IS NOT NULL AND error_message IS NOT NULL AND finished_at IS NOT NULL)),
    CHECK (status != 'SUCCEEDED' OR requires_confirmation = 0 OR confirmed_at IS NOT NULL)
) STRICT;
CREATE INDEX ix_business_operations_status_created_at ON business_operations (status, created_at);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_day_id INTEGER CHECK (plan_day_id > 0),
    formal_version INTEGER CHECK (formal_version >= 1),
    formal_change_type TEXT CHECK (formal_change_type IN ('INITIAL_CONFIRM', 'MODIFY', 'CANCEL', 'RECONFIRM')),
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1 CHECK (snapshot_schema_version >= 1),
    business_operation_id INTEGER CHECK (business_operation_id > 0),
    actor_code TEXT NOT NULL DEFAULT 'LOCAL_CAPTAIN' CHECK (actor_code = 'LOCAL_CAPTAIN'),
    actor_name_snapshot TEXT NOT NULL DEFAULT '车队长' CHECK (length(trim(actor_name_snapshot)) > 0),
    entry_source TEXT NOT NULL CHECK (entry_source IN ('PAGE', 'AGENT')),
    action_code TEXT NOT NULL CHECK (length(trim(action_code)) > 0),
    target_type TEXT NOT NULL CHECK (length(trim(target_type)) > 0),
    target_id INTEGER CHECK (target_id > 0),
    target_label_snapshot TEXT NOT NULL CHECK (length(trim(target_label_snapshot)) > 0),
    outcome TEXT NOT NULL CHECK (outcome IN ('SUCCEEDED', 'FAILED')),
    changes_json TEXT NOT NULL CHECK (CASE WHEN json_valid(changes_json) THEN json_type(changes_json) = 'object' ELSE 0 END),
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (outcome != 'FAILED' OR (reason IS NOT NULL AND length(trim(reason)) > 0)),
    UNIQUE (plan_day_id, formal_version),
    CHECK ((plan_day_id IS NULL AND formal_version IS NULL AND formal_change_type IS NULL)
        OR (plan_day_id IS NOT NULL AND formal_version IS NOT NULL AND formal_change_type IS NOT NULL
            AND outcome = 'SUCCEEDED' AND business_operation_id IS NOT NULL)),
    CHECK (formal_change_type IS NULL
        OR (formal_change_type = 'INITIAL_CONFIRM' AND formal_version = 1)
        OR (formal_change_type != 'INITIAL_CONFIRM' AND formal_version > 1))
) STRICT;
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at, id);
CREATE INDEX ix_audit_logs_target_created_at ON audit_logs (target_type, target_id, created_at);
CREATE INDEX ix_audit_logs_operation_id ON audit_logs (business_operation_id);

-- 唯一初始化行是并发控制元数据；不创建账号、类别、司机、车辆、计划或演示数据。
INSERT INTO business_state (state_key, revision) VALUES ('MAIN', 1);

COMMIT;
