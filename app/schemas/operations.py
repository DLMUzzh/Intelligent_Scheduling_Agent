from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_INTEGER = 9223372036854775807
Id = Annotated[str, Field(pattern=r'^[1-9][0-9]{0,18}$')]
Version = Id
RequestHash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]

ACTION_TARGETS = {
    'CREATE_CATEGORY': 'CATEGORY',
    'UPDATE_CATEGORY': 'CATEGORY',
    'DELETE_CATEGORY': 'CATEGORY',
    'CREATE_PLAN': 'PLAN',
    'UPDATE_PLAN': 'PLAN',
    'DELETE_PLAN': 'PLAN',
    'UPDATE_DEMAND': 'PLAN_DAY',
    'CREATE_DRIVER': 'DRIVER',
    'UPDATE_DRIVER': 'DRIVER',
    'DELETE_DRIVER': 'DRIVER',
    'CREATE_VEHICLE': 'VEHICLE',
    'UPDATE_VEHICLE': 'VEHICLE',
    'DELETE_VEHICLE': 'VEHICLE',
    'CREATE_UNAVAILABILITY': 'UNAVAILABILITY',
    'UPDATE_UNAVAILABILITY': 'UNAVAILABILITY',
    'DELETE_UNAVAILABILITY': 'UNAVAILABILITY',
    'GENERATE_DRAFT': 'PLAN',
    'SAVE_DRAFT': 'DRAFT',
    'CONFIRM_PLAN': 'PLAN',
    'MODIFY_FORMAL_DAY': 'FORMAL_DAY',
    'CANCEL_FORMAL_DAY': 'FORMAL_DAY',
}
VERSION_TABLES = (
    'collection_plans',
    'plan_days',
    'collection_categories',
    'drivers',
    'vehicles',
    'resource_unavailability',
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ObjectVersion(StrictModel):
    id: Id
    version: Version

    @field_validator('id', 'version')
    @classmethod
    def bounded_integer(cls, value: str) -> str:
        if int(value) > MAX_INTEGER:
            raise ValueError('超出 SQLite 整数范围')
        return value


class DayVersion(ObjectVersion):
    formal_version: Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,18})$')]

    @field_validator('formal_version')
    @classmethod
    def bounded_formal_version(cls, value: str) -> str:
        return cls.bounded_integer(value)


class DayRevision(StrictModel):
    plan_day_id: Id
    version: Version
    formal_version: Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,18})$')]


class ExpectedVersions(StrictModel):
    business_revision: Version
    collection_plans: list[ObjectVersion] = Field(default_factory=list)
    plan_days: list[DayVersion] = Field(default_factory=list)
    collection_categories: list[ObjectVersion] = Field(default_factory=list)
    drivers: list[ObjectVersion] = Field(default_factory=list)
    vehicles: list[ObjectVersion] = Field(default_factory=list)
    resource_unavailability: list[ObjectVersion] = Field(default_factory=list)

    @field_validator('business_revision')
    @classmethod
    def bounded_revision(cls, value: str) -> str:
        return ObjectVersion.bounded_integer(value)

    @field_validator(*VERSION_TABLES)
    @classmethod
    def unique_objects(cls, value: list[ObjectVersion]) -> list[ObjectVersion]:
        if len({item.id for item in value}) != len(value):
            raise ValueError('版本依据中对象编号重复')
        return value


class PrepareInput(StrictModel):
    request_key: str
    action_code: str
    target_type: str
    target_id: Id | None
    payload: dict
    expected_versions_json: ExpectedVersions

    @field_validator('request_key')
    @classmethod
    def uuid4_key(cls, value: str) -> str:
        identifier = UUID(value)
        if identifier.version != 4 or str(identifier) != value:
            raise ValueError('必须为规范小写 UUID v4')
        return value

    @field_validator('target_id')
    @classmethod
    def bounded_target(cls, value: str | None) -> str | None:
        return ObjectVersion.bounded_integer(value) if value is not None else None


class ExecuteInput(StrictModel):
    request_hash: RequestHash
    confirmed: bool


class ErrorItem(StrictModel):
    code: str
    message: str
    field: str | None = None
    target_type: str | None = None
    target_id: Id | None = None
    work_date: str | None = None


class Summary(StrictModel):
    schema_version: Literal['1'] = '1'
    action_code: str
    target_type: str
    target_id: Id | None
    title: str
    before: object
    after: object
    affected_dates: list[str] = Field(default_factory=list)
    pending_dates: list[str] = Field(default_factory=list)
    preserved_dates: list[str] = Field(default_factory=list)
    warnings: list[ErrorItem] = Field(default_factory=list)
    changes: list[dict] = Field(default_factory=list)
    related_changes: list[dict] = Field(default_factory=list)


class ExecutionResult(StrictModel):
    schema_version: Literal['1'] = '1'
    code: str
    target_type: str
    target_id: Id | None
    affected_dates: list[str] = Field(default_factory=list)
    preserved_dates: list[str] = Field(default_factory=list)
    resource_ids: list[Id] = Field(default_factory=list)
    plan_day_ids: list[Id] = Field(default_factory=list)
    revisions: list[DayRevision] = Field(default_factory=list)
    errors: list[ErrorItem] = Field(default_factory=list)
