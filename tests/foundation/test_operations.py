import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.responses import ApiError
from app.database.foundation import transaction
from app.models.foundation import AuditLog, BusinessOperation, CollectionCategory
from app.schemas.operations import ExecuteInput, PrepareInput
from app.services.confirmation_service import ConfirmationService

ORIGIN = {'Origin': 'http://127.0.0.1:8000'}


def input_data(key=None, name='新值', business_revision='1', version='1'):
    return {
        'request_key': key or str(uuid4()),
        'action_code': 'UPDATE_CATEGORY',
        'target_type': 'CATEGORY',
        'target_id': '1',
        'payload': {'name': name},
        'expected_versions_json': {
            'business_revision': business_revision,
            'collection_categories': [{'id': '1', 'version': version}],
        },
    }


def prepare(client, data=None):
    response = client.post('/api/v1/operations', json=data or input_data(), headers=ORIGIN)
    assert response.status_code == 201, response.text
    return response.json()['data']


def execute(client, operation, **changes):
    return client.post(
        f'/api/v1/operations/{operation["id"]}/executions',
        headers=ORIGIN,
        json={'request_hash': operation['request_hash'], 'confirmed': True} | changes,
    )


def state(engine):
    with engine.connect() as connection:
        return {
            'name': connection.exec_driver_sql(
                'SELECT name FROM collection_categories WHERE id=1'
            ).scalar_one(),
            'version': connection.exec_driver_sql(
                'SELECT version FROM collection_categories WHERE id=1'
            ).scalar_one(),
            'revision': connection.exec_driver_sql('SELECT revision FROM business_state').scalar_one(),
            'rows': connection.exec_driver_sql('SELECT count(*) FROM collection_categories').scalar_one(),
            'audits': connection.exec_driver_sql('SELECT count(*) FROM audit_logs').scalar_one(),
        }


def test_prepare_confirm_audit_and_persistent_replay(foundation):
    client, engine, adapter = foundation
    data = input_data()
    operation = prepare(client, data)
    assert operation['status'] == 'PENDING' and operation['requires_confirmation'] == 1
    assert 'request_payload_json' not in operation and 'actor_code' not in operation
    assert state(engine) == {'name': '原值', 'version': 1, 'revision': 1, 'rows': 1, 'audits': 0}
    response = execute(client, operation)
    assert response.status_code == 200, response.text
    view = response.json()['data']
    assert view['status'] == 'SUCCEEDED' and view['confirmed_at']
    assert response.json()['data_revision'] == '2'
    assert state(engine) == {'name': '新值', 'version': 2, 'revision': 2, 'rows': 1, 'audits': 1}
    assert execute(client, operation).json()['data'] == view
    replay = client.post('/api/v1/operations', json=data, headers=ORIGIN)
    assert replay.status_code == 200 and replay.json()['code'] == 'OPERATION_REPLAY'
    assert replay.json()['data'] == view
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    restarted = ConfirmationService(factory, {'UPDATE_CATEGORY': adapter})
    assert (
        restarted.execute(
            int(view['id']), ExecuteInput(request_hash=view['request_hash'], confirmed=True)
        ).data
        == view
    )
    assert adapter.executions == 1
    audit = client.get('/api/v1/audit-logs').json()['data']
    assert audit['total'] == '1' and 'changes_json' not in audit['items'][0]
    detail = client.get(f'/api/v1/audit-logs/{audit["items"][0]["id"]}').json()['data']
    assert detail['actor_code'] == 'LOCAL_CAPTAIN' and detail['entry_source'] == 'PAGE'
    assert detail['business_operation_id'] == operation['id']
    assert detail['changes_json']['before']['name'] == '原值'
    assert detail['changes_json']['after']['name'] == '新值'
    assert detail['formal_version'] is None and detail['outcome'] == 'SUCCEEDED'


def test_same_key_changed_request_rejected(foundation):
    client, engine, _ = foundation
    data = input_data()
    prepare(client, data)
    response = client.post('/api/v1/operations', json=data | {'payload': {'name': '其他值'}}, headers=ORIGIN)
    assert response.status_code == 409 and response.json()['code'] == 'IDEMPOTENCY_KEY_REUSED'
    assert state(engine)['name'] == '原值'


@pytest.mark.parametrize(
    'changes,code',
    [({'confirmed': False}, 'CONFIRMATION_REQUIRED'), ({'request_hash': 'a' * 64}, 'CONFIRMATION_MISMATCH')],
)
def test_confirmation_rejection_keeps_pending(foundation, changes, code):
    client, _, _ = foundation
    operation = prepare(client)
    response = execute(client, operation, **changes)
    assert response.status_code == 409 and response.json()['code'] == code
    assert client.get(f'/api/v1/operations/{operation["id"]}').json()['data']['status'] == 'PENDING'
    assert execute(client, operation).status_code == 200


def test_version_conflict_persists_failed_and_replays_error(foundation):
    client, engine, _ = foundation
    first, stale = prepare(client), prepare(client, input_data(name='旧页面修改'))
    assert execute(client, first).status_code == 200
    response = execute(client, stale)
    assert response.status_code == 409 and response.json()['code'] == 'VERSION_CONFLICT'
    assert response.json()['data']['status'] == 'FAILED'
    assert execute(client, stale).json()['data'] == response.json()['data']
    query = client.get(f'/api/v1/operations/{stale["id"]}').json()
    assert query['success'] and query['data']['status'] == 'FAILED'
    assert state(engine)['revision'] == 2 and state(engine)['audits'] == 2
    with Session(engine) as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.business_operation_id == int(stale['id'])))
        changes = json.loads(audit.changes_json)
        assert changes['before']['name'] == changes['after']['name'] == '新值'


@pytest.mark.parametrize(
    'failure,code,status',
    [
        (ApiError('CAPACITY_EXCEEDED', '测试业务拒绝'), 'CAPACITY_EXCEEDED', 409),
        (RuntimeError('SQL SELECT secret_api_key'), 'INTERNAL_ERROR', 500),
    ],
)
def test_partial_failure_rolls_back_and_records_failure(foundation, failure, code, status):
    client, engine, adapter = foundation
    operation = prepare(client)
    adapter.failure = failure
    response = execute(client, operation)
    assert response.status_code == status and response.json()['code'] == code
    assert 'secret_api_key' not in response.text and 'SELECT' not in response.text
    assert response.json()['data']['status'] == 'FAILED'
    assert state(engine) == {'name': '原值', 'version': 1, 'revision': 1, 'rows': 1, 'audits': 1}
    with Session(engine) as db:
        audit = db.scalar(select(AuditLog))
        assert audit.outcome == 'FAILED' and audit.reason
        assert json.loads(audit.changes_json)['after']['name'] == '原值'


def test_concurrent_same_operation_executes_once(foundation):
    client, engine, adapter = foundation
    operation = prepare(client)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: execute(client, operation), range(4)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()['data']['finished_at'] for response in responses}) == 1
    assert adapter.executions == 1 and state(engine)['audits'] == 1


def test_concurrent_prepare_same_key_one_record(foundation):
    client, engine, _ = foundation
    data = input_data()
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: client.post('/api/v1/operations', json=data, headers=ORIGIN), range(4))
        )
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    assert len({response.json()['data']['id'] for response in responses}) == 1
    with Session(engine) as db:
        assert len(db.scalars(select(BusinessOperation)).all()) == 1


def test_concurrent_different_keys_same_version_one_winner(foundation):
    client, engine, _ = foundation
    operations = [prepare(client, input_data(name=f'并发{i}')) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda op: execute(client, op), operations))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert state(engine)['version'] == 2 and state(engine)['revision'] == 2


def test_changed_resolution_rejected(foundation):
    client, engine, adapter = foundation
    operation = prepare(client)
    adapter.extra_resolved = 'algorithm configuration changed'
    response = execute(client, operation)
    assert response.status_code == 409 and response.json()['code'] == 'INPUT_CHANGED'
    assert state(engine)['name'] == '原值'


def test_cross_midnight_rolls_back(foundation, future_date, monkeypatch):
    client, engine, adapter = foundation
    adapter.dates = [future_date]
    operation = prepare(client)
    dates = iter([date(2026, 1, 1), date.fromisoformat(future_date)])
    monkeypatch.setattr('app.services.confirmation_service.business_date', lambda: next(dates))
    response = execute(client, operation)
    assert response.status_code == 409 and response.json()['code'] == 'DATE_LOCKED'
    assert state(engine)['version'] == 1 and state(engine)['name'] == '原值'


def test_no_manual_confirmation_validation():
    operation = BusinessOperation(request_hash='a' * 64, requires_confirmation=0)
    ConfirmationService._check_confirmation(operation, ExecuteInput(request_hash='a' * 64, confirmed=False))
    with pytest.raises(ApiError, match='无需人工确认'):
        ConfirmationService._check_confirmation(
            operation, ExecuteInput(request_hash='a' * 64, confirmed=True)
        )


def test_business_adapter_cannot_skip_confirmation(foundation):
    client, engine, adapter = foundation
    adapter.requires_confirmation = False
    response = client.post('/api/v1/operations', json=input_data(), headers=ORIGIN)
    assert response.status_code == 500 and response.json()['code'] == 'DATA_INTEGRITY_ERROR'
    assert state(engine)['name'] == '原值'


@pytest.mark.parametrize('after_commit', [True, False])
def test_commit_acknowledgement_requires_fresh_status_lookup(foundation, after_commit):
    client, engine, adapter = foundation
    operation = prepare(client)

    class CommitSession(Session):
        def commit(self):
            if self.info.get('execution_written') and not after_commit:
                raise RuntimeError('commit acknowledgement unavailable')
            super().commit()
            if self.info.get('execution_written') and after_commit:
                raise RuntimeError('acknowledgement lost after actual commit')

    factory = sessionmaker(bind=engine, class_=CommitSession, expire_on_commit=False)
    client.app.state.confirmation_service = ConfirmationService(factory, {'UPDATE_CATEGORY': adapter})
    response = execute(client, operation)
    if after_commit:
        assert response.status_code == 200 and response.json()['data']['status'] == 'SUCCEEDED'
        assert state(engine)['audits'] == 1 and state(engine)['revision'] == 2
    else:
        assert response.status_code == 503 and response.json()['code'] == 'STORAGE_UNAVAILABLE'
        assert state(engine)['audits'] == 0 and state(engine)['revision'] == 1
        assert client.get(f'/api/v1/operations/{operation["id"]}').json()['data']['status'] == 'PENDING'


def test_agent_source_from_trusted_service_only(foundation):
    client, engine, _ = foundation
    service = client.app.state.confirmation_service
    operation = service.prepare(PrepareInput.model_validate(input_data()), source='AGENT').data
    assert execute(client, operation).status_code == 200
    with Session(engine) as db:
        assert db.scalar(select(AuditLog.entry_source)) == 'AGENT'


def test_queries_have_no_business_writes(foundation):
    client, engine, _ = foundation
    before = state(engine)
    for path in ['/api/v1/context', '/api/v1/audit-logs', '/api/v1/operations?request_key=' + str(uuid4())]:
        assert client.get(path).status_code == 200
    assert state(engine) == before


def test_audit_failure_rolls_back_business(foundation, monkeypatch):
    client, engine, _ = foundation
    operation = prepare(client)
    original = __import__('app.services.confirmation_service', fromlist=['record_operation']).record_operation

    def fail_success_audit(db, row, **kwargs):
        if kwargs['outcome'] == 'SUCCEEDED':
            raise RuntimeError('audit insert exercise')
        return original(db, row, **kwargs)

    monkeypatch.setattr('app.services.confirmation_service.record_operation', fail_success_audit)
    assert execute(client, operation).status_code == 500
    assert state(engine)['name'] == '原值' and state(engine)['revision'] == 1


def test_prepare_is_enforced_read_only(foundation, monkeypatch):
    client, engine, adapter = foundation

    def invalid_prepare(db, request):
        db.execute(CollectionCategory.__table__.update().values(name='should fail'))

    monkeypatch.setattr(adapter, 'prepare', invalid_prepare)
    response = client.post('/api/v1/operations', json=input_data(), headers=ORIGIN)
    assert response.status_code == 503
    assert state(engine)['name'] == '原值'
    with transaction(client.app.state.session_factory) as db:
        assert not db.scalars(select(BusinessOperation)).all()


def test_prepare_rejects_unflushed_orm_changes(foundation, monkeypatch):
    client, engine, adapter = foundation
    original = adapter.prepare

    def invalid_prepare(db, request):
        prepared = original(db, request)
        db.get(CollectionCategory, 1).name = 'unflushed mutation'
        return prepared

    monkeypatch.setattr(adapter, 'prepare', invalid_prepare)
    response = client.post('/api/v1/operations', json=input_data(), headers=ORIGIN)
    assert response.status_code == 500 and response.json()['code'] == 'DATA_INTEGRITY_ERROR'
    assert state(engine)['name'] == '原值'
    with Session(engine) as db:
        assert not db.scalars(select(BusinessOperation)).all()


@pytest.mark.parametrize('field', ['request_payload_json', 'summary_json', 'expected_versions_json'])
def test_stored_frozen_content_cannot_change(foundation, field):
    client, engine, _ = foundation
    operation = prepare(client)
    with Session(engine) as db:
        row = db.get(BusinessOperation, int(operation['id']))
        data = json.loads(getattr(row, field))
        if field == 'request_payload_json':
            data['resolved']['name'] = 'tampered'
        elif field == 'summary_json':
            data['title'] = 'tampered summary'
        else:
            data['collection_categories'] = []
        setattr(row, field, json.dumps(data))
        db.commit()
    response = execute(client, operation)
    assert response.status_code == 409 and response.json()['code'] == 'INPUT_CHANGED'
    assert state(engine)['name'] == '原值'


def test_shared_object_version_compare_and_swap(foundation):
    from app.services.version_service import advance_object_version

    client, engine, _ = foundation
    with transaction(client.app.state.session_factory, write=True) as db:
        assert advance_object_version(db, 'collection_categories', 1, 1) == 2
    with (
        pytest.raises(ApiError, match='对象版本冲突'),
        transaction(client.app.state.session_factory, write=True) as db,
    ):
        advance_object_version(db, 'collection_categories', 1, 1)
    assert state(engine)['version'] == 2


def test_confirmation_policy_cannot_change_after_prepare(foundation):
    client, engine, _ = foundation
    operation = prepare(client)
    with engine.begin() as connection:
        connection.exec_driver_sql('UPDATE business_operations SET requires_confirmation=0')
    response = execute(client, operation, confirmed=False)
    assert response.status_code == 409 and response.json()['code'] == 'INPUT_CHANGED'
    assert state(engine)['name'] == '原值'


def test_preparation_commit_acknowledgement_recovery(foundation):
    client, engine, adapter = foundation

    class CommitOnceSession(Session):
        interrupted = False

        def commit(self):
            prepared = any(isinstance(row, BusinessOperation) for row in self.identity_map.values())
            super().commit()
            if prepared and not type(self).interrupted:
                type(self).interrupted = True
                raise RuntimeError('preparation acknowledgement lost')

    factory = sessionmaker(bind=engine, class_=CommitOnceSession, expire_on_commit=False)
    client.app.state.confirmation_service = ConfirmationService(factory, {'UPDATE_CATEGORY': adapter})
    data = input_data()
    response = client.post('/api/v1/operations', json=data, headers=ORIGIN)
    assert response.status_code == 200 and response.json()['code'] == 'OPERATION_REPLAY'
    assert response.json()['data']['status'] == 'PENDING'
    assert state(engine)['revision'] == 1
    assert execute(client, response.json()['data']).status_code == 200


def test_new_object_id_matches_preview_and_audit_keeps_actual_id(foundation):
    from typing import Literal

    from app.schemas.operations import ExecutionResult, Summary
    from app.services.confirmation_service import ActionExecution, PreparedAction
    from tests.foundation.conftest import TestAdapter, TestPayload

    client, engine, _ = foundation

    class CreatePayload(TestPayload):
        task_mode: Literal['TAG', 'ROAD']

    class CreateAdapter(TestAdapter):
        def validate_payload(self, payload):
            return CreatePayload.model_validate(payload).model_dump()

        def prepare(self, db, request):
            after = {'id': None, 'task_mode': request.payload['task_mode'], 'name': request.payload['name']}
            return PreparedAction(
                resolved=request.payload,
                summary=Summary(
                    action_code='CREATE_CATEGORY',
                    target_type='CATEGORY',
                    target_id=None,
                    title='测试新增对象',
                    before=None,
                    after=after,
                ),
                expected_versions=request.expected_versions_json,
            )

        def execute(self, db, resolved):
            row = CollectionCategory(task_mode=resolved['task_mode'], name=resolved['name'])
            db.add(row)
            db.flush()
            return ActionExecution(
                ExecutionResult(
                    code='EXECUTED', target_type='CATEGORY', target_id=str(row.id), resource_ids=[str(row.id)]
                ),
                after={'id': str(row.id), 'task_mode': row.task_mode, 'name': row.name},
            )

    client.app.state.confirmation_service.adapters['CREATE_CATEGORY'] = CreateAdapter()
    data = input_data(name='新增对象') | {
        'action_code': 'CREATE_CATEGORY',
        'target_id': None,
        'payload': {'name': '新增对象', 'task_mode': 'TAG'},
        'expected_versions_json': {'business_revision': '1'},
    }
    operation = prepare(client, data)
    assert operation['summary_json']['after']['id'] is None
    response = execute(client, operation)
    assert response.status_code == 200 and response.json()['data']['target_id'] == '2'
    assert execute(client, operation).json()['data']['target_id'] == '2'
    with Session(engine) as db:
        audit = db.scalar(select(AuditLog))
        assert json.loads(audit.changes_json)['after']['id'] == '2'
    assert state(engine)['rows'] == 2 and state(engine)['revision'] == 2


def test_auto_id_projection_preserves_other_business_values():
    from app.services.confirmation_service import canonical, confirmation_projection

    preview = {'days': [{'id': None, 'notes': None}, {'id': '7', 'notes': 'keep'}]}
    actual = {'days': [{'id': '99', 'notes': None}, {'id': '7', 'notes': 'keep'}]}
    assert confirmation_projection(preview, actual) == preview
    actual['days'][0]['notes'] = 'unconfirmed change'
    assert canonical(confirmation_projection(preview, actual)) != canonical(preview)
    actual['days'][0]['notes'] = None
    actual['days'][1]['id'] = '8'
    assert canonical(confirmation_projection(preview, actual)) != canonical(preview)
