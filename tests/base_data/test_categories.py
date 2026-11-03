from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from tests.base_data.conftest import ORIGIN, execute, prepare, version, write


def test_category_crud_unique_and_confirmation(base_data):
    client, engine = base_data
    request_key = str(uuid4())
    response = prepare(client, 'CREATE_CATEGORY', {'task_mode': 'TAG', 'name': '  城区  '}, key=request_key)
    assert response.status_code == 201, response.text
    operation = response.json()['data']
    assert operation['summary_json']['after'] == {'id': None, 'task_mode': 'TAG', 'name': '城区'}
    assert client.get('/api/v1/collection-categories').json()['data']['total'] == '0'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(client, operation), range(2)))
    assert all(result.status_code == 200 for result in results)
    result = results[0].json()['data']
    assert results[1].json()['data'] == result
    row = client.get('/api/v1/collection-categories').json()['data']['items'][0]
    assert row['name'] == '城区' and row['version'] == '1'
    assert (
        prepare(client, 'CREATE_CATEGORY', {'task_mode': 'TAG', 'name': '城区'}).json()['code']
        == 'DUPLICATE_CATEGORY'
    )
    write(client, 'CREATE_CATEGORY', {'task_mode': 'ROAD', 'name': '城区'})
    renamed = write(
        client, 'UPDATE_CATEGORY', {'name': '新城区'}, row['id'], version(row, 'collection_categories')
    )
    assert renamed['summary_json']['before']['name'] == '城区'
    row = client.get('/api/v1/collection-categories?task_mode=TAG').json()['data']['items'][0]
    assert row['name'] == '新城区' and row['version'] == '2'
    write(client, 'DELETE_CATEGORY', {}, row['id'], version(row, 'collection_categories'))
    assert client.get('/api/v1/collection-categories?task_mode=TAG').json()['data']['items'] == []
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT count(*) FROM audit_logs').scalar_one() == 4
    audit = client.get('/api/v1/audit-logs/1').json()['data']
    assert audit['changes_json']['after']['id'] == result['target_id']


@pytest.mark.parametrize(
    'payload',
    [
        {'task_mode': 'tag', 'name': 'x'},
        {'task_mode': 'TAG', 'name': ' '},
        {'task_mode': 'TAG', 'name': 'x' * 101},
        {'task_mode': 'TAG', 'name': 'x', 'is_enabled': 1},
        {'task_mode': 'TAG', 'name': True},
    ],
)
def test_category_validation(base_data, payload):
    client, _ = base_data
    response = prepare(client, 'CREATE_CATEGORY', payload)
    assert response.status_code == 422 and response.json()['errors']


def test_category_pagination_search_and_strict_queries(base_data):
    client, _ = base_data
    for mode, name in [('TAG', '100%'), ('ROAD', '101'), ('TAG', 'A_B')]:
        write(client, 'CREATE_CATEGORY', {'task_mode': mode, 'name': name})
    page = client.get('/api/v1/collection-categories?page_size=1').json()['data']
    assert page['total'] == '3' and page['items'][0]['task_mode'] == 'ROAD'
    assert client.get('/api/v1/collection-categories?q=%25').json()['data']['total'] == '1'
    assert (
        client.get('/api/v1/collection-categories?page=9999999999999999999999999').json()['data']['items']
        == []
    )
    for query in ('task_mode=X', 'page=0', 'page_size=101', 'q=' + 'x' * 101, 'unknown=1', 'page=1&page=2'):
        assert client.get('/api/v1/collection-categories?' + query).status_code == 422


def test_category_same_key_binds_input_and_stale_version(base_data):
    client, _ = base_data
    key = str(uuid4())
    request = {
        'request_key': key,
        'action_code': 'CREATE_CATEGORY',
        'target_type': 'CATEGORY',
        'target_id': None,
        'payload': {'task_mode': 'TAG', 'name': 'A'},
        'expected_versions_json': {'business_revision': '1'},
    }
    first = client.post('/api/v1/operations', json=request, headers=ORIGIN).json()['data']
    assert execute(client, first).status_code == 200
    assert (
        client.post('/api/v1/operations', json=request, headers=ORIGIN).json()['data']['status']
        == 'SUCCEEDED'
    )
    assert (
        client.post(
            '/api/v1/operations',
            json=request | {'payload': {'task_mode': 'TAG', 'name': 'B'}},
            headers=ORIGIN,
        ).json()['code']
        == 'IDEMPOTENCY_KEY_REUSED'
    )
    row = client.get('/api/v1/collection-categories').json()['data']['items'][0]
    old = prepare(
        client, 'UPDATE_CATEGORY', {'name': 'B'}, row['id'], version(row, 'collection_categories')
    ).json()['data']
    write(client, 'CREATE_CATEGORY', {'task_mode': 'ROAD', 'name': 'C'})
    assert execute(client, old).json()['code'] == 'VERSION_CONFLICT'
