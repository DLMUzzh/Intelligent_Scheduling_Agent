from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.runtime import RuntimeSettings
from app.database.foundation import build_engine
from app.main import create_app
from tests.foundation.test_operations import ORIGIN, execute, input_data, prepare, state


def test_context_contract(foundation):
    client, _, _ = foundation
    response = client.get('/api/v1/context')
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'success', 'code', 'message', 'data', 'errors', 'request_id', 'data_revision'}
    assert body['data_revision'] == '1' and body['success'] is True and body['errors'] == []
    assert UUID(body['request_id']).version == 4
    assert response.headers['X-Request-ID'] == body['request_id']
    assert body['data']['actor_code'] == 'LOCAL_CAPTAIN'
    assert body['data']['notification_status'] == 'NOT_CONNECTED'
    assert body['data']['timezone'] == 'Asia/Shanghai'
    assert len(body['data']['business_date']) == 10


@pytest.mark.parametrize(
    'headers',
    [
        {'Host': 'example.org:8000'},
        {'Host': '127.0.0.1:9999'},
        {'Origin': 'https://example.org'},
        {'Origin': 'null'},
        {'Origin': 'http://127.0.0.1:8000.attacker.org'},
    ],
)
def test_source_rejected(foundation, headers):
    client, _, _ = foundation
    response = client.get('/api/v1/context', headers=headers)
    assert response.status_code == 403 and response.json()['code'] == 'ACCESS_DENIED'


def test_forwarded_headers_do_not_expand_access(foundation):
    client, _, _ = foundation
    response = client.get(
        '/api/v1/context',
        headers={
            'Host': 'attacker.org',
            'X-Forwarded-Host': '127.0.0.1:8000',
            'X-Forwarded-For': '127.0.0.1',
        },
    )
    assert response.status_code == 403


def test_missing_write_origin_rejected(foundation):
    client, engine, _ = foundation
    response = client.post('/api/v1/operations', json=input_data())
    assert response.status_code == 403 and response.json()['code'] == 'ACCESS_DENIED'
    assert state(engine)['audits'] == 0


def test_non_loopback_peer_rejected(foundation):
    client, _, _ = foundation
    with TestClient(client.app, base_url='http://127.0.0.1:8000', client=('192.168.1.20', 42000)) as external:
        assert external.get('/api/v1/context').status_code == 403


def test_development_proxy_host_origin_allowed(foundation):
    client, _, _ = foundation
    assert (
        client.get(
            '/api/v1/context',
            headers={
                'Host': '127.0.0.1:5173',
                'Origin': 'http://127.0.0.1:5173',
            },
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    'content',
    [
        '{',
        '{"payload":{},"payload":{}}',
        '{"nested":{"x":1,"x":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        '{"x":1e999}',
    ],
)
def test_malformed_json_rejected(foundation, content):
    client, _, _ = foundation
    response = client.post(
        '/api/v1/operations', content=content, headers=ORIGIN | {'Content-Type': 'application/json'}
    )
    assert response.status_code == 400 and response.json()['code'] == 'MALFORMED_JSON'


@pytest.mark.parametrize('media', ['text/plain', 'application/x-www-form-urlencoded'])
def test_write_media_type(foundation, media):
    client, _, _ = foundation
    response = client.post('/api/v1/operations', content='{}', headers=ORIGIN | {'Content-Type': media})
    assert response.status_code == 415 and response.json()['code'] == 'UNSUPPORTED_MEDIA_TYPE'


@pytest.mark.parametrize(
    'change',
    [
        {'actor_code': 'ADMIN'},
        {'entry_source': 'AGENT'},
        {'action_code': 'RUN_SQL'},
        {'target_id': 1},
        {'target_id': True},
        {'target_id': '01'},
        {'target_id': '9223372036854775808'},
        {'request_key': str(uuid4()).upper()},
        {'request_key': 'not a uuid'},
        {'payload': {'name': True}},
        {'payload': {'name': '新值', 'sql': 'SELECT secret'}},
        {'expected_versions_json': {'business_revision': 1}},
        {'expected_versions_json': {'business_revision': '1'}},
    ],
)
def test_strict_prepare_validation(foundation, change):
    client, _, _ = foundation
    response = client.post('/api/v1/operations', json=input_data() | change, headers=ORIGIN)
    assert response.status_code == 422, response.text
    assert response.json()['code'] == 'VALIDATION_ERROR'
    assert 'SELECT secret' not in response.text


@pytest.mark.parametrize(
    'path',
    [
        '/api/v1/context?unknown=1',
        '/api/v1/context?q=1&q=2',
        '/api/v1/operations',
        '/api/v1/operations?request_key=invalid',
        '/api/v1/operations/01',
        '/api/v1/operations/9223372036854775808',
        '/api/v1/audit-logs?page=0',
        '/api/v1/audit-logs?page_size=101',
        '/api/v1/audit-logs?start_date=2026-01-01',
        '/api/v1/audit-logs?start_date=2026-02-30&end_date=2026-03-01',
        '/api/v1/audit-logs?target_id=1',
        '/api/v1/audit-logs?outcome=RUNNING',
    ],
)
def test_invalid_query_and_identifier(foundation, path):
    client, _, _ = foundation
    response = client.get(path)
    assert response.status_code == 422 and response.json()['code'] == 'VALIDATION_ERROR'


def test_not_found_and_method_response(foundation):
    client, _, _ = foundation
    for path in ['/api/v1/not-found', '/api/v1/operations/999', '/api/v1/audit-logs/999', '/api/drivers']:
        response = client.get(path)
        assert response.status_code == 404 and response.json()['code'] == 'NOT_FOUND'
    response = client.post('/api/v1/context', json={}, headers=ORIGIN)
    assert response.status_code == 405 and response.json()['code'] == 'METHOD_NOT_ALLOWED'
    assert 'GET' in response.headers['Allow']


def test_unhandled_system_error_is_safe(foundation):
    client, _, _ = foundation

    def failure():
        raise RuntimeError('SQL SELECT * secret_api_key=do_not_expose')

    client.app.add_api_route('/api/v1/error-exercise', failure, methods=['GET'])
    response = client.get('/api/v1/error-exercise')
    assert response.status_code == 500 and response.json()['code'] == 'INTERNAL_ERROR'
    assert 'secret_api_key' not in response.text and 'SELECT' not in response.text


def test_constraint_translation_does_not_leak_sql(foundation):
    client, _, _ = foundation

    def failure():
        raise IntegrityError(
            'SELECT secret', {}, RuntimeError('UNIQUE constraint failed: vehicles.plate_key')
        )

    client.app.add_api_route('/api/v1/constraint-exercise', failure, methods=['GET'])
    response = client.get('/api/v1/constraint-exercise')
    assert response.status_code == 409 and response.json()['code'] == 'DUPLICATE_PLATE'
    assert 'SELECT' not in response.text and 'plate_key' not in response.text


def test_storage_unavailable_response(foundation):
    client, _, _ = foundation

    def failure():
        raise OperationalError('SELECT secret', {}, RuntimeError('storage unavailable'))

    client.app.add_api_route('/api/v1/storage-exercise', failure, methods=['GET'])
    response = client.get('/api/v1/storage-exercise')
    assert response.status_code == 503 and response.json()['code'] == 'STORAGE_UNAVAILABLE'
    assert 'SELECT' not in response.text


def test_write_busy_keeps_operation_pending(foundation):
    client, engine, _ = foundation
    operation = prepare(client)

    def fast_timeout(connection, _record):
        connection.execute('PRAGMA busy_timeout=30')

    event.listen(engine, 'connect', fast_timeout)
    with engine.connect().execution_options(write_transaction=True) as held:
        with held.begin():
            response = execute(client, operation)
            assert response.status_code == 503 and response.json()['code'] == 'WRITE_BUSY'
    assert client.get(f'/api/v1/operations/{operation["id"]}').json()['data']['status'] == 'PENDING'
    assert state(engine)['audits'] == 0


def test_production_has_no_business_adapter(tmp_path):
    config = RuntimeSettings(
        database_url=f'sqlite:///{(tmp_path / "production.db").as_posix()}', log_directory=tmp_path / 'logs'
    )
    engine = build_engine(config)
    app = create_app(engine, config=config)
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000)) as client:
        response = client.post('/api/v1/operations', json=input_data(), headers=ORIGIN)
        assert response.status_code == 422 and response.json()['code'] == 'VALIDATION_ERROR'
        assert not app.state.confirmation_service.adapters
    engine.dispose()


def test_audit_filters_pagination_and_detail(foundation):
    client, _, _ = foundation
    operation = prepare(client)
    assert execute(client, operation).status_code == 200
    response = client.get(
        '/api/v1/audit-logs',
        params={
            'business_operation_id': operation['id'],
            'entry_source': 'PAGE',
            'outcome': 'SUCCEEDED',
            'target_type': 'CATEGORY',
            'target_id': '1',
            'q': '测试',
            'page_size': '1',
        },
    )
    assert response.status_code == 200 and response.json()['data']['total'] == '1'
    empty = client.get('/api/v1/audit-logs?page=2&page_size=1').json()['data']
    assert empty['items'] == [] and empty['total'] == '1'
    extreme = client.get('/api/v1/audit-logs?page=999999999999999999&page_size=100').json()['data']
    assert extreme['items'] == [] and extreme['total'] == '1'


def test_get_body_is_rejected(foundation):
    client, _, _ = foundation
    response = client.request('GET', '/api/v1/context', content='{}')
    assert response.status_code == 422 and response.json()['code'] == 'VALIDATION_ERROR'


def test_missing_revision_returns_null(foundation):
    client, engine, _ = foundation
    with engine.begin() as connection:
        connection.exec_driver_sql('DELETE FROM business_state')
    response = client.get('/api/v1/context')
    assert response.status_code == 500 and response.json()['code'] == 'DATA_INTEGRITY_ERROR'
    assert response.json()['data_revision'] is None


def test_pagination_large_out_of_range_and_normalization(foundation):
    client, _, _ = foundation
    response = client.get('/api/v1/audit-logs?page=10000000000000000000&page_size=100')
    assert response.status_code == 200 and response.json()['data']['items'] == []
    normalized = client.get('/api/v1/audit-logs?page=00001&page_size=00020').json()['data']
    assert normalized['page'] == 1 and normalized['page_size'] == 20


def test_complete_calendar_range_for_audit(foundation):
    client, _, _ = foundation
    response = client.get('/api/v1/audit-logs?start_date=0001-01-01&end_date=9999-12-31')
    assert response.status_code == 200 and response.json()['data']['items'] == []
