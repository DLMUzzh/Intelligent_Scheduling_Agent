from datetime import date
from typing import Annotated, ClassVar, Literal, Self

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from app.schemas.operations import MAX_INTEGER, Id, ObjectVersion, StrictModel


def trimmed(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def optional_text(value: object) -> object:
    return trimmed(value) or None if isinstance(value, str) else value


def valid_date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('日期必须为 YYYY-MM-DD')
    return value


def bounded_uint(value: str) -> str:
    if int(value) > MAX_INTEGER:
        raise ValueError('超出 SQLite 整数范围')
    return value


Name = Annotated[str, BeforeValidator(trimmed), Field(min_length=1, max_length=100)]
Plate = Annotated[str, BeforeValidator(trimmed), Field(min_length=1, max_length=30)]
Phone = Annotated[Annotated[str, Field(max_length=40)] | None, BeforeValidator(optional_text)]
Notes = Annotated[Annotated[str, Field(max_length=2000)] | None, BeforeValidator(optional_text)]
OptionalName = Annotated[Annotated[str, Field(max_length=100)] | None, BeforeValidator(optional_text)]
Flag = Annotated[int, Field(strict=True, ge=0, le=1)]
UInt = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,18})$'), AfterValidator(bounded_uint)]
DateText = Annotated[str, AfterValidator(valid_date)]
Identifier = Annotated[Id, AfterValidator(ObjectVersion.bounded_integer)]
Mode = Literal['TAG', 'ROAD']
Efficiency = Literal['HIGH', 'MEDIUM', 'LOW']
SHIFTS = ('MORNING', 'MIDDLE', 'EVENING')
CAPACITIES = tuple(f'{shift.lower()}_max_{unit}' for shift in SHIFTS for unit in ('tag_count', 'road_meters'))


class EmptyPayload(StrictModel):
    pass


class CategoryCreate(StrictModel):
    task_mode: Mode
    name: Name


class CategoryUpdate(StrictModel):
    name: Name


class DriverCreate(StrictModel):
    name: Name
    phone: Phone = None
    efficiency_level: Efficiency = 'MEDIUM'
    is_enabled: Flag = 1
    can_morning: Flag = 1
    can_middle: Flag = 1
    can_evening: Flag = 1


class Patch(StrictModel):
    nullable_fields: ClassVar[set[str]] = set()

    @model_validator(mode='after')
    def nonempty_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError('修改字段不能为空')
        for field in self.model_fields_set - self.nullable_fields:
            if getattr(self, field) is None:
                raise ValueError(f'{field} 不允许为 null')
        return self


class DriverUpdate(Patch):
    nullable_fields = {'phone'}
    name: Name | None = None
    phone: Phone = None
    efficiency_level: Efficiency | None = None
    is_enabled: Flag | None = None
    can_morning: Flag | None = None
    can_middle: Flag | None = None
    can_evening: Flag | None = None


class VehicleCreate(StrictModel):
    plate_number: Plate
    name: OptionalName = None
    notes: Notes = None
    is_enabled: Flag = 1
    morning_max_tag_count: UInt
    morning_max_road_meters: UInt
    middle_max_tag_count: UInt
    middle_max_road_meters: UInt
    evening_max_tag_count: UInt
    evening_max_road_meters: UInt


class VehicleUpdate(Patch):
    nullable_fields = {'name', 'notes'}
    plate_number: Plate | None = None
    name: OptionalName = None
    notes: Notes = None
    is_enabled: Flag | None = None
    morning_max_tag_count: UInt | None = None
    morning_max_road_meters: UInt | None = None
    middle_max_tag_count: UInt | None = None
    middle_max_road_meters: UInt | None = None
    evening_max_tag_count: UInt | None = None
    evening_max_road_meters: UInt | None = None


class UnavailabilityCreate(StrictModel):
    driver_id: Identifier | None = None
    vehicle_id: Identifier | None = None
    start_date: DateText
    end_date: DateText
    reason: Notes = None

    @model_validator(mode='after')
    def valid_range(self) -> Self:
        if (self.driver_id is None) == (self.vehicle_id is None):
            raise ValueError('司机与车辆必须且只能选择一个')
        if self.start_date > self.end_date:
            raise ValueError('结束日期不得早于开始日期')
        return self


class UnavailabilityUpdate(Patch):
    nullable_fields = {'reason'}
    start_date: DateText | None = None
    end_date: DateText | None = None
    reason: Notes = None

    @model_validator(mode='after')
    def paired_dates(self) -> Self:
        if ('start_date' in self.model_fields_set) != ('end_date' in self.model_fields_set):
            raise ValueError('开始和结束日期须一起修改')
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError('结束日期不得早于开始日期')
        return self


PAYLOAD_MODELS = {
    'CREATE_CATEGORY': CategoryCreate,
    'UPDATE_CATEGORY': CategoryUpdate,
    'DELETE_CATEGORY': EmptyPayload,
    'CREATE_DRIVER': DriverCreate,
    'UPDATE_DRIVER': DriverUpdate,
    'DELETE_DRIVER': EmptyPayload,
    'CREATE_VEHICLE': VehicleCreate,
    'UPDATE_VEHICLE': VehicleUpdate,
    'DELETE_VEHICLE': EmptyPayload,
    'CREATE_UNAVAILABILITY': UnavailabilityCreate,
    'UPDATE_UNAVAILABILITY': UnavailabilityUpdate,
    'DELETE_UNAVAILABILITY': EmptyPayload,
}
