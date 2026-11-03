from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class ShiftCode(StrEnum):
    MORNING = 'MORNING'
    AFTERNOON = 'AFTERNOON'
    NIGHT = 'NIGHT'


class Efficiency(StrEnum):
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'


class ResourceStatus(StrEnum):
    ACTIVE = 'ACTIVE'
    DISABLED = 'DISABLED'


def km_to_meters(value: str) -> int:
    if not isinstance(value, str) or len(value) > 30:
        raise ValueError('道路公里数必须使用十进制字符串')
    try:
        km = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('无效的道路公里数') from exc
    if not km.is_finite() or km < 0 or km > 1_000_000:
        raise ValueError('公里数须在 0 到 1000000 之间')
    meters = km * 1000
    if meters != meters.to_integral_value():
        raise ValueError('道路公里数最多保留三位小数（精确到米）')
    return int(meters)


def meters_to_km(value: int) -> str:
    return format(Decimal(value) / 1000, 'f').rstrip('0').rstrip('.') if value % 1000 else str(value // 1000)


PositiveCount = Annotated[StrictInt, Field(gt=0, le=100_000_000)]
NonnegativeCount = Annotated[StrictInt, Field(ge=0, le=100_000_000)]
Name = Annotated[str, Field(min_length=1, max_length=80)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class TagRequirement(InputModel):
    tag_type: Name
    daily_count: PositiveCount


class RoadRequirement(InputModel):
    road_type: Name
    daily_km: str

    @field_validator('daily_km')
    @classmethod
    def valid_km(cls, value: str) -> str:
        if km_to_meters(value) <= 0:
            raise ValueError('道路需求必须大于 0')
        return value


class Requirements(InputModel):
    tag_requirements: list[TagRequirement] = Field(default_factory=list, max_length=100)
    road_requirements: list[RoadRequirement] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_requirements(self) -> Self:
        if not self.tag_requirements and not self.road_requirements:
            raise ValueError('至少填写一项 Tag 或道路采集需求')
        for items, key in [(self.tag_requirements, 'tag_type'), (self.road_requirements, 'road_type')]:
            values = [getattr(item, key) for item in items]
            if len(values) != len(set(values)):
                raise ValueError('同一天不能重复填写同一任务类型')
        return self


class DailyOverride(Requirements):
    date: date


class DateRange(InputModel):
    start_date: date
    end_date: date

    @model_validator(mode='after')
    def validate_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError('结束日期不能早于开始日期')
        if (self.end_date - self.start_date).days > 365:
            raise ValueError('单次日期范围最多 366 天')
        return self


class PlanCreate(DateRange, Requirements):
    title: Annotated[str, Field(min_length=1, max_length=150)]
    notes: Annotated[str, Field(max_length=3000)] = ''
    daily_overrides: list[DailyOverride] = Field(default_factory=list, max_length=366)

    @model_validator(mode='after')
    def validate_overrides(self) -> Self:
        dates = [item.date for item in self.daily_overrides]
        if len(set(dates)) != len(dates):
            raise ValueError('每日覆盖配置中日期不能重复')
        if any(not self.start_date <= day <= self.end_date for day in dates):
            raise ValueError('每日配置日期必须位于计划日期范围内')
        return self


class DriverCreate(InputModel):
    name: Name
    phone: Annotated[str, Field(max_length=40)] = ''
    efficiency_level: Efficiency = Efficiency.MEDIUM
    status: ResourceStatus = ResourceStatus.ACTIVE
    available_shifts: list[ShiftCode] = Field(
        default_factory=lambda: list(ShiftCode), min_length=1, max_length=3
    )

    @field_validator('available_shifts')
    @classmethod
    def unique_shifts(cls, value: list[ShiftCode]) -> list[ShiftCode]:
        if len(set(value)) != len(value):
            raise ValueError('班次不能重复')
        return value


class CapacityInput(InputModel):
    shift: ShiftCode
    max_tag_count: NonnegativeCount
    max_road_km: str

    @field_validator('max_road_km')
    @classmethod
    def valid_km(cls, value: str) -> str:
        km_to_meters(value)
        return value


class VehicleCreate(InputModel):
    plate_number: Annotated[str, Field(min_length=1, max_length=30)]
    vehicle_name: Name
    status: ResourceStatus = ResourceStatus.ACTIVE
    capacities: list[CapacityInput] = Field(min_length=1, max_length=3)

    @field_validator('capacities')
    @classmethod
    def unique_capacities(cls, value: list[CapacityInput]) -> list[CapacityInput]:
        if len({item.shift for item in value}) != len(value):
            raise ValueError('车辆班次容量不能重复')
        return value


class UnavailabilityCreate(DateRange):
    reason: Annotated[str, Field(max_length=200)] = ''


class ShiftUpdate(InputModel):
    name: Name
    start_time: Annotated[str, Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
    end_time: Annotated[str, Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
    enabled: bool


class PreviewCreate(DateRange):
    plan_id: int = Field(gt=0)
    algorithm: Literal['GREEDY_V1'] = 'GREEDY_V1'


class TagAllocation(InputModel):
    tag_type: Name
    count: PositiveCount


class RoadAllocation(InputModel):
    road_type: Name
    km: str

    @field_validator('km')
    @classmethod
    def valid_km(cls, value: str) -> str:
        if km_to_meters(value) <= 0:
            raise ValueError('分配公里数必须大于 0')
        return value


class AssignmentInput(InputModel):
    vehicle_id: int = Field(gt=0)
    driver_id: int = Field(gt=0)
    shift: ShiftCode
    task_mode: Literal['TAG', 'ROAD']
    tag_allocations: list[TagAllocation] = Field(default_factory=list, max_length=100)
    road_allocations: list[RoadAllocation] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def valid_allocations(self) -> Self:
        if self.task_mode == 'TAG' and (not self.tag_allocations or self.road_allocations):
            raise ValueError('TAG 排班必须且只能包含 Tag 任务')
        if self.task_mode == 'ROAD' and (not self.road_allocations or self.tag_allocations):
            raise ValueError('ROAD 排班必须且只能包含道路任务')
        for items, key in [(self.tag_allocations, 'tag_type'), (self.road_allocations, 'road_type')]:
            if len({getattr(item, key) for item in items}) != len(items):
                raise ValueError('分配任务类型不能重复')
        return self


class AssignmentChanges(InputModel):
    vehicle_id: int | None = Field(default=None, gt=0)
    driver_id: int | None = Field(default=None, gt=0)
    shift: ShiftCode | None = None
    task_mode: Literal['TAG', 'ROAD'] | None = None
    tag_allocations: list[TagAllocation] | None = Field(default=None, max_length=100)
    road_allocations: list[RoadAllocation] | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def non_null_changes(self) -> Self:
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError('修改内容不能为空或 null')
        return self


class VersionInput(InputModel):
    expected_version: int = Field(ge=1)


class AssignmentPatch(VersionInput):
    changes: AssignmentChanges


class AssignmentAdd(VersionInput, AssignmentInput):
    date: date


class ConfirmInput(VersionInput):
    preview_id: Annotated[str, Field(min_length=1, max_length=40)]
    confirm_dates: list[date] = Field(min_length=1, max_length=366)
    idempotency_key: Annotated[str, Field(min_length=1, max_length=120)]

    @field_validator('confirm_dates')
    @classmethod
    def unique_dates(cls, value: list[date]) -> list[date]:
        if len(set(value)) != len(value):
            raise ValueError('确认日期不能重复')
        return sorted(value)
