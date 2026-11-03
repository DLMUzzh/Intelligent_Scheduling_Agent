"""Read contracts for existing draft/history references and capacity maintenance."""

import json
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from app.core.responses import ApiError
from app.schemas.base_data import DateText, Efficiency, Flag, Mode
from app.schemas.operations import MAX_INTEGER, StrictModel

StoredUInt = Annotated[int, Field(strict=True, ge=0, le=MAX_INTEGER)]
StoredId = Annotated[int, Field(strict=True, ge=1, le=MAX_INTEGER)]
Shift = Literal['MORNING', 'MIDDLE', 'EVENING']


class CapacityRow(StrictModel):
    vehicle_id: StoredId
    plate_number_snapshot: Annotated[str, Field(min_length=1)]
    vehicle_name_snapshot: str | None
    shift_code: Shift
    is_available: Flag
    max_tag_count: StoredUInt
    max_road_meters: StoredUInt


class DemandSnapshot(StrictModel):
    collection_category_id: StoredId
    category_name_snapshot: str
    task_mode: Mode
    target_tag_count: StoredId | None
    target_road_meters: StoredId | None
    sort_order: StoredId
    notes: str | None

    @model_validator(mode='after')
    def mode_quantity(self):
        if (self.task_mode == 'TAG') != (self.target_tag_count is not None) or (self.task_mode == 'ROAD') != (
            self.target_road_meters is not None
        ):
            raise ValueError('需求数量与模式不一致')
        return self


class AllocationSnapshot(StrictModel):
    id: StoredId
    task_package_id: StoredId
    collection_category_id: StoredId
    category_name_snapshot: str
    task_mode: Mode
    assigned_tag_count: StoredId | None
    assigned_road_meters: StoredId | None

    @model_validator(mode='after')
    def mode_quantity(self):
        if (self.task_mode == 'TAG') != (self.assigned_tag_count is not None) or (
            self.task_mode == 'ROAD'
        ) != (self.assigned_road_meters is not None):
            raise ValueError('分配数量与模式不一致')
        return self


class PackageSnapshot(StrictModel):
    id: StoredId
    plan_day_id: StoredId
    work_date: DateText
    schedule_kind: Literal['FORMAL']
    driver_id: StoredId
    vehicle_id: StoredId
    shift_code: Shift
    task_mode: Mode
    driver_name_snapshot: str
    efficiency_level_snapshot: Efficiency
    plate_number_snapshot: str
    vehicle_name_snapshot: str | None
    max_tag_count_snapshot: StoredUInt
    max_road_meters_snapshot: StoredUInt
    allocations: list[AllocationSnapshot] = Field(min_length=1)


class FormalHeader(StrictModel):
    collection_plan_id: StoredId
    plan_name_snapshot: str
    plan_day_id: StoredId
    work_date: DateText
    formal_status: Literal['ACTIVE', 'CANCELLED']
    formal_version: StoredId


class CapacityBasis(StrictModel):
    capacity_basis_revision: StoredId
    capacity_captured_at: str
    vehicle_capacities_json: list[CapacityRow]

    @model_validator(mode='after')
    def complete_capacity(self):
        validate_capacity_rows(self.vehicle_capacities_json)
        return self


class GenerationSnapshot(StrictModel):
    algorithm_code: str
    algorithm_version: str
    input_revision: StoredId
    is_manually_modified: Flag


class ShortageSnapshot(StrictModel):
    collection_category_id: StoredId
    task_mode: Mode
    unallocated_tag_count: StoredId | None
    unallocated_road_meters: StoredId | None
    reason_codes: list[
        Literal[
            'DRIVER_SHORTAGE',
            'QUALIFICATION_LIMIT',
            'VEHICLE_UNAVAILABLE',
            'CAPACITY_SHORTAGE',
            'VEHICLE_MODE_LIMIT',
        ]
    ]
    message: str


class FormalSnapshot(StrictModel):
    header: FormalHeader
    demands: list[DemandSnapshot]
    packages: list[PackageSnapshot]
    capacity_basis: CapacityBasis
    generation: GenerationSnapshot
    shortages: list[ShortageSnapshot]


class FormalChanges(StrictModel):
    schema_version: Literal[1, '1']
    before: FormalSnapshot | None
    after: FormalSnapshot


class DraftMetadata(GenerationSnapshot):
    schema_version: Literal[1, '1']
    needs_revalidation: Flag
    validation_basis: dict
    shortage_reasons: list[ShortageSnapshot]
    generated_at: str
    updated_at: str


def parse_snapshot(model, value: str):
    try:
        return TypeAdapter(model).validate_python(json.loads(value))
    except (ValueError, TypeError, ValidationError):
        raise ApiError('DATA_INTEGRITY_ERROR', '已有快照结构不完整，请核查资料关联') from None


def validate_capacity_rows(rows: list[CapacityRow]) -> None:
    pairs = {(row.vehicle_id, row.shift_code) for row in rows}
    vehicle_ids = {row.vehicle_id for row in rows}
    if len(pairs) != len(rows) or len(rows) != len(vehicle_ids) * 3:
        raise ValueError('车辆容量快照必须包含每车唯一的早中晚三班')


def parse_capacities(value: str) -> list[dict]:
    rows = parse_snapshot(list[CapacityRow], value)
    try:
        validate_capacity_rows(rows)
    except ValueError:
        raise ApiError('DATA_INTEGRITY_ERROR', '车辆容量快照三班不完整或重复') from None
    return [row.model_dump() for row in rows]


def category_ids(value: object) -> set[int]:
    """The draft basis permits extra inputs, but every category reference is a strict integer."""
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'collection_category_id':
                try:
                    result.add(TypeAdapter(StoredId).validate_python(child))
                except ValidationError:
                    raise ApiError('DATA_INTEGRITY_ERROR', '草稿类别引用不完整') from None
            else:
                result.update(category_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(category_ids(child))
    return result


def public_capacity(rows: list[dict]) -> list[dict]:
    return [
        row
        | {
            field: str(row[field]) if row[field] is not None else None
            for field in ('vehicle_id', 'max_tag_count', 'max_road_meters')
        }
        for row in rows
    ]
