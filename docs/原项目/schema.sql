-- SQLite initial schema; initialize a new database only.
PRAGMA foreign_keys=ON;

CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	operator_type VARCHAR(20) NOT NULL, 
	operator_id VARCHAR(80) NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	target_type VARCHAR(50) NOT NULL, 
	target_id VARCHAR(80) NOT NULL, 
	before_data JSON, 
	after_data JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE collection_plans (
	id INTEGER NOT NULL, 
	title VARCHAR(150) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	notes TEXT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (end_date >= start_date)
);

CREATE TABLE confirmation_operations (
	idempotency_key VARCHAR(120) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (idempotency_key)
);

CREATE TABLE drivers (
	id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	phone VARCHAR(40) NOT NULL, 
	efficiency_level VARCHAR(10) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (efficiency_level IN ('HIGH','MEDIUM','LOW')), 
	CHECK (status IN ('ACTIVE','DISABLED'))
);

CREATE TABLE shifts (
	id INTEGER NOT NULL, 
	code VARCHAR(15) NOT NULL, 
	name VARCHAR(30) NOT NULL, 
	start_time VARCHAR(5) NOT NULL, 
	end_time VARCHAR(5) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (code IN ('MORNING','AFTERNOON','NIGHT')), 
	UNIQUE (code)
);

CREATE TABLE vehicles (
	id INTEGER NOT NULL, 
	plate_number VARCHAR(30) NOT NULL, 
	vehicle_name VARCHAR(80) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (status IN ('ACTIVE','DISABLED')), 
	UNIQUE (plate_number)
);

CREATE TABLE daily_schedules (
	id INTEGER NOT NULL, 
	plan_id INTEGER NOT NULL, 
	schedule_date DATE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	version INTEGER NOT NULL, 
	algorithm_name VARCHAR(30) NOT NULL, 
	confirmed_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (plan_id, schedule_date), 
	FOREIGN KEY(plan_id) REFERENCES collection_plans (id)
);

CREATE INDEX ix_daily_schedules_schedule_date ON daily_schedules (schedule_date);

CREATE TABLE daily_tasks (
	id INTEGER NOT NULL, 
	plan_id INTEGER NOT NULL, 
	work_date DATE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (plan_id, work_date), 
	FOREIGN KEY(plan_id) REFERENCES collection_plans (id)
);

CREATE INDEX ix_daily_tasks_work_date ON daily_tasks (work_date);

CREATE TABLE driver_shift_qualifications (
	driver_id INTEGER NOT NULL, 
	shift_id INTEGER NOT NULL, 
	PRIMARY KEY (driver_id, shift_id), 
	FOREIGN KEY(driver_id) REFERENCES drivers (id), 
	FOREIGN KEY(shift_id) REFERENCES shifts (id)
);

CREATE TABLE plan_road_requirements (
	id INTEGER NOT NULL, 
	plan_id INTEGER NOT NULL, 
	road_type VARCHAR(80) NOT NULL, 
	daily_target_meters INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (plan_id, road_type), 
	CHECK (daily_target_meters > 0), 
	FOREIGN KEY(plan_id) REFERENCES collection_plans (id)
);

CREATE TABLE plan_tag_requirements (
	id INTEGER NOT NULL, 
	plan_id INTEGER NOT NULL, 
	tag_type VARCHAR(80) NOT NULL, 
	daily_target_count INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (plan_id, tag_type), 
	CHECK (daily_target_count > 0), 
	FOREIGN KEY(plan_id) REFERENCES collection_plans (id)
);

CREATE TABLE resource_unavailability (
	id INTEGER NOT NULL, 
	driver_id INTEGER, 
	vehicle_id INTEGER, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	reason VARCHAR(200) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK ((driver_id IS NOT NULL AND vehicle_id IS NULL) OR (driver_id IS NULL AND vehicle_id IS NOT NULL)), 
	CHECK (end_date >= start_date), 
	FOREIGN KEY(driver_id) REFERENCES drivers (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE INDEX ix_unavailable_vehicle_dates ON resource_unavailability (vehicle_id, start_date, end_date);

CREATE INDEX ix_unavailable_driver_dates ON resource_unavailability (driver_id, start_date, end_date);

CREATE TABLE schedule_previews (
	id VARCHAR(40) NOT NULL, 
	plan_id INTEGER NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	algorithm_name VARCHAR(30) NOT NULL, 
	preview_version INTEGER NOT NULL, 
	preview_content JSON NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_id) REFERENCES collection_plans (id)
);

CREATE INDEX ix_schedule_previews_plan_id ON schedule_previews (plan_id);

CREATE TABLE vehicle_day_modes (
	vehicle_id INTEGER NOT NULL, 
	work_date DATE NOT NULL, 
	task_mode VARCHAR(10) NOT NULL, 
	PRIMARY KEY (vehicle_id, work_date), 
	CHECK (task_mode IN ('TAG','ROAD')), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
);

CREATE TABLE vehicle_shift_capacities (
	id INTEGER NOT NULL, 
	vehicle_id INTEGER NOT NULL, 
	shift_id INTEGER NOT NULL, 
	max_tag_count INTEGER NOT NULL, 
	max_road_meters INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vehicle_id, shift_id), 
	CHECK (max_tag_count >= 0 AND max_road_meters >= 0), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
	FOREIGN KEY(shift_id) REFERENCES shifts (id)
);

CREATE TABLE daily_road_requirements (
	id INTEGER NOT NULL, 
	daily_task_id INTEGER NOT NULL, 
	road_type VARCHAR(80) NOT NULL, 
	target_meters INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (daily_task_id, road_type), 
	CHECK (target_meters > 0), 
	FOREIGN KEY(daily_task_id) REFERENCES daily_tasks (id)
);

CREATE TABLE daily_tag_requirements (
	id INTEGER NOT NULL, 
	daily_task_id INTEGER NOT NULL, 
	tag_type VARCHAR(80) NOT NULL, 
	target_count INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (daily_task_id, tag_type), 
	CHECK (target_count > 0), 
	FOREIGN KEY(daily_task_id) REFERENCES daily_tasks (id)
);

CREATE TABLE preview_day_claims (
	plan_id INTEGER NOT NULL, 
	work_date DATE NOT NULL, 
	preview_id VARCHAR(40) NOT NULL, 
	PRIMARY KEY (plan_id, work_date), 
	FOREIGN KEY(plan_id) REFERENCES collection_plans (id), 
	FOREIGN KEY(preview_id) REFERENCES schedule_previews (id)
);

CREATE TABLE schedule_assignments (
	id INTEGER NOT NULL, 
	schedule_id INTEGER NOT NULL, 
	work_date DATE NOT NULL, 
	vehicle_id INTEGER NOT NULL, 
	driver_id INTEGER NOT NULL, 
	shift_id INTEGER NOT NULL, 
	task_mode VARCHAR(10) NOT NULL, 
	status VARCHAR(15) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (work_date, driver_id), 
	UNIQUE (work_date, vehicle_id, shift_id), 
	CHECK (task_mode IN ('TAG','ROAD')), 
	FOREIGN KEY(schedule_id) REFERENCES daily_schedules (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
	FOREIGN KEY(driver_id) REFERENCES drivers (id), 
	FOREIGN KEY(shift_id) REFERENCES shifts (id)
);

CREATE INDEX ix_schedule_assignments_work_date ON schedule_assignments (work_date);

CREATE TABLE assignment_road_allocations (
	id INTEGER NOT NULL, 
	assignment_id INTEGER NOT NULL, 
	daily_road_requirement_id INTEGER NOT NULL, 
	assigned_meters INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (assignment_id, daily_road_requirement_id), 
	CHECK (assigned_meters > 0), 
	FOREIGN KEY(assignment_id) REFERENCES schedule_assignments (id), 
	FOREIGN KEY(daily_road_requirement_id) REFERENCES daily_road_requirements (id)
);

CREATE TABLE assignment_tag_allocations (
	id INTEGER NOT NULL, 
	assignment_id INTEGER NOT NULL, 
	daily_tag_requirement_id INTEGER NOT NULL, 
	assigned_count INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (assignment_id, daily_tag_requirement_id), 
	CHECK (assigned_count > 0), 
	FOREIGN KEY(assignment_id) REFERENCES schedule_assignments (id), 
	FOREIGN KEY(daily_tag_requirement_id) REFERENCES daily_tag_requirements (id)
);

CREATE TABLE notifications (
	id INTEGER NOT NULL, 
	assignment_id INTEGER NOT NULL, 
	driver_id INTEGER NOT NULL, 
	notification_type VARCHAR(20) NOT NULL, 
	schedule_version INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	status VARCHAR(15) NOT NULL, 
	idempotency_key VARCHAR(150) NOT NULL, 
	retry_count INTEGER NOT NULL, 
	error_message TEXT, 
	sent_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(assignment_id) REFERENCES schedule_assignments (id), 
	FOREIGN KEY(driver_id) REFERENCES drivers (id), 
	UNIQUE (idempotency_key)
);

CREATE INDEX ix_notifications_status ON notifications (status);
