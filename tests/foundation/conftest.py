from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import Field
from sqlalchemy import select

from app.core.responses import ApiError
from app.core.runtime import RuntimeSettings
from app.core.time import business_date
from app.database.foundation import build_engine
from app.main import create_app
from app.models.foundation import CollectionCategory
from app.schemas.operations import ExecutionResult, PrepareInput, StrictModel, Summary
from app.services.confirmation_service import ActionExecution, PreparedAction
from app.services.version_service import advance_object_version


class TestPayload(StrictModel):
    __test__ = False
    name: str = Field(min_length=1, max_length=100)


class TestAdapter:
    """Test-only adapter exercising the common protocol, never registered in production."""

    __test__ = False

    def __init__(self):
        self.executions = 0
        self.failure = None
        self.requires_confirmation = True
        self.dates = []
        self.extra_resolved = None

    def validate_payload(self, payload: dict) -> dict:
        return TestPayload.model_validate(payload).model_dump()

    def prepare(self, db, request: PrepareInput) -> PreparedAction:
        row = db.scalar(select(CollectionCategory).where(CollectionCategory.id == int(request.target_id)))
        if row is None:
            raise ApiError('NOT_FOUND', '测试对象不存在')
        before = {'id': str(row.id), 'task_mode': row.task_mode, 'name': row.name}
        after = before | {'name': request.payload['name']}
        return PreparedAction(
            resolved={
                'target_id': request.target_id,
                'name': request.payload['name'],
                'extra': self.extra_resolved,
            },
            summary=Summary(
                action_code=request.action_code,
                target_type=request.target_type,
                target_id=request.target_id,
                title='测试专用操作',
                before=before,
                after=after,
                affected_dates=self.dates,
                changes=[{'field': 'name', 'label': '名称', 'before': row.name, 'after': after['name']}],
            ),
            expected_versions=request.expected_versions_json,
            requires_confirmation=self.requires_confirmation,
        )

    def execute(self, db, resolved: dict) -> ActionExecution:
        self.executions += 1
        row = db.get(CollectionCategory, int(resolved['target_id']))
        row.name = resolved['name']
        advance_object_version(db, 'collection_categories', row.id, row.version)
        db.info['execution_written'] = True
        if self.failure is not None:
            db.add(CollectionCategory(task_mode='TAG', name='partial business change'))
            db.flush()
            raise self.failure
        return ActionExecution(
            ExecutionResult(
                code='EXECUTED',
                target_type='CATEGORY',
                target_id=resolved['target_id'],
                affected_dates=self.dates,
            ),
            after={'id': str(row.id), 'task_mode': row.task_mode, 'name': row.name},
        )


@pytest.fixture
def foundation(tmp_path):
    config = RuntimeSettings(
        database_url=f'sqlite:///{(tmp_path / "api.db").as_posix()}', log_directory=tmp_path / 'logs'
    )
    engine = build_engine(config)
    adapter = TestAdapter()
    app = create_app(engine, config=config, adapters={'UPDATE_CATEGORY': adapter})
    with TestClient(
        app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000), raise_server_exceptions=False
    ) as client:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO collection_categories(task_mode,name) VALUES ('TAG','原值')"
            )
        yield client, engine, adapter
    engine.dispose()


@pytest.fixture
def future_date():
    return (business_date() + timedelta(days=10)).isoformat()
