from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.base_data import DateText, Efficiency, Identifier, Mode
from app.schemas.operations import StrictModel

QueryFlag = Literal['0', '1']
PageNumber = Annotated[str, Field(pattern=r'^[0-9]+$')]


class Pagination(StrictModel):
    page: PageNumber = '1'
    page_size: PageNumber = '20'

    @model_validator(mode='after')
    def valid_pagination(self) -> Self:
        if int(self.page) < 1 or not 1 <= int(self.page_size) <= 100:
            raise ValueError('分页参数超出范围')
        return self


class CategoryQuery(Pagination):
    q: str | None = Field(default=None, max_length=100)
    task_mode: Mode | None = None


class ResourceDateQuery(StrictModel):
    work_date: DateText | None = None


class ResourceQuery(Pagination, ResourceDateQuery):
    q: str | None = Field(default=None, max_length=100)
    is_enabled: QueryFlag | None = None
    is_available: QueryFlag | None = None


class DriverQuery(ResourceQuery):
    efficiency_level: Efficiency | None = None


class UnavailabilityQuery(Pagination):
    driver_id: Identifier | None = None
    vehicle_id: Identifier | None = None
    start_date: DateText | None = None
    end_date: DateText | None = None

    @model_validator(mode='after')
    def valid_filters(self) -> Self:
        if self.driver_id is not None and self.vehicle_id is not None:
            raise ValueError('资源筛选只能选择司机或车辆之一')
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError('日期范围须成对提供')
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError('结束日期不得早于开始日期')
        return self
