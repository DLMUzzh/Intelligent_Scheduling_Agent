from datetime import timedelta

import pytest

from app.core.time import business_date
from tests.base_data.conftest import create_driver, create_vehicle, prepare, version, write


@pytest.mark.parametrize('kind', ['driver', 'vehicle'])
def test_unavailability_create_overlap_edit_cancel_and_resource_versions(base_data, tomorrow, kind):
    client, _ = base_data
    resource = create_driver(client) if kind == 'driver' else create_vehicle(client)
    table = 'drivers' if kind == 'driver' else 'vehicles'
    next_day = (business_date() + timedelta(days=2)).isoformat()
    payload = {
        f'{kind}_id': resource['id'],
        'start_date': tomorrow,
        'end_date': next_day,
        'reason': '休假' if kind == 'driver' else '保养',
    }
    first = write(client, 'CREATE_UNAVAILABILITY', payload, versions=version(resource, table))
    assert first['result_json']['resource_ids'] == [resource['id']]
    current = client.get(f'/api/v1/{table}/{resource["id"]}?work_date={tomorrow}').json()['data']
    assert (
        current['is_available'] == 0
        and current['version'] == '2'
        and current['unavailability_ids'] == [first['target_id']]
    )
    second = write(client, 'CREATE_UNAVAILABILITY', payload, versions=version(current, table))
    records = client.get(f'/api/v1/resource-unavailability?{kind}_id={resource["id"]}').json()['data']
    assert records['total'] == '2'
    row = client.get(f'/api/v1/resource-unavailability/{first["target_id"]}').json()['data']
    current = client.get(f'/api/v1/{table}/{resource["id"]}').json()['data']
    write(
        client,
        'UPDATE_UNAVAILABILITY',
        {'start_date': tomorrow, 'end_date': tomorrow, 'reason': None},
        row['id'],
        version(row, 'resource_unavailability') | version(current, table),
    )
    row = client.get(f'/api/v1/resource-unavailability/{row["id"]}').json()['data']
    assert row['version'] == '2' and row['reason'] is None
    current = client.get(f'/api/v1/{table}/{resource["id"]}').json()['data']
    write(
        client,
        'DELETE_UNAVAILABILITY',
        {},
        row['id'],
        version(row, 'resource_unavailability') | version(current, table),
    )
    current = client.get(f'/api/v1/{table}/{resource["id"]}?work_date={tomorrow}').json()['data']
    assert current['is_available'] == 0 and current['unavailability_ids'] == [second['target_id']]
    row = client.get(f'/api/v1/resource-unavailability/{second["target_id"]}').json()['data']
    write(
        client,
        'DELETE_UNAVAILABILITY',
        {},
        row['id'],
        version(row, 'resource_unavailability') | version(current, table),
    )
    assert (
        client.get(f'/api/v1/{table}/{resource["id"]}?work_date={tomorrow}').json()['data']['is_available']
        == 1
    )


def test_unavailability_requires_resource_version_and_locks_today(base_data, tomorrow):
    client, _ = base_data
    driver = create_driver(client)
    payload = {'driver_id': driver['id'], 'start_date': tomorrow, 'end_date': tomorrow}
    assert prepare(client, 'CREATE_UNAVAILABILITY', payload).status_code == 422
    today = business_date().isoformat()
    response = prepare(
        client, 'CREATE_UNAVAILABILITY', payload | {'start_date': today}, versions=version(driver, 'drivers')
    )
    assert response.status_code == 409 and response.json()['code'] == 'DATE_LOCKED'
    missing = prepare(client, 'CREATE_UNAVAILABILITY', payload | {'driver_id': '999999'})
    assert missing.status_code == 404 and missing.json()['code'] == 'REFERENCED_OBJECT_NOT_FOUND'


def test_locked_original_range_cannot_be_shifted_or_cancelled(base_data, tomorrow):
    client, engine = base_data
    driver = create_driver(client)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            'INSERT INTO resource_unavailability(driver_id,start_date,end_date) VALUES (?,?,?)',
            (int(driver['id']), business_date().isoformat(), tomorrow),
        )
    row = client.get('/api/v1/resource-unavailability/1').json()['data']
    versions = version(row, 'resource_unavailability') | version(driver, 'drivers')
    for action, payload in [
        ('UPDATE_UNAVAILABILITY', {'start_date': tomorrow, 'end_date': tomorrow}),
        ('UPDATE_UNAVAILABILITY', {'reason': '改原因'}),
        ('DELETE_UNAVAILABILITY', {}),
    ]:
        result = prepare(client, action, payload, row['id'], versions)
        assert result.status_code == 409 and result.json()['code'] == 'DATE_LOCKED'
    assert client.get('/api/v1/resource-unavailability/1').json()['data'] == row


@pytest.mark.parametrize(
    'patch',
    [
        {},
        {'start_date': '2030-01-01'},
        {'end_date': '2030-01-01'},
        {'driver_id': '2'},
        {'start_date': None, 'end_date': None},
        {'start_date': '2030-02-30', 'end_date': '2030-03-01'},
        {'start_date': '2030-01-02', 'end_date': '2030-01-01'},
        {'reason': 'x' * 2001},
    ],
)
def test_unavailability_patch_validation(base_data, tomorrow, patch):
    client, _ = base_data
    driver = create_driver(client)
    op = write(
        client,
        'CREATE_UNAVAILABILITY',
        {'driver_id': driver['id'], 'start_date': tomorrow, 'end_date': tomorrow},
        versions=version(driver, 'drivers'),
    )
    row = client.get(f'/api/v1/resource-unavailability/{op["target_id"]}').json()['data']
    current = client.get(f'/api/v1/drivers/{driver["id"]}').json()['data']
    result = prepare(
        client,
        'UPDATE_UNAVAILABILITY',
        patch,
        row['id'],
        version(row, 'resource_unavailability') | version(current, 'drivers'),
    )
    assert result.status_code == 422, result.text


def test_unavailability_filters_and_delete_unused_resource_cleanup(base_data, tomorrow):
    client, _ = base_data
    driver = create_driver(client)
    op = write(
        client,
        'CREATE_UNAVAILABILITY',
        {'driver_id': driver['id'], 'start_date': tomorrow, 'end_date': tomorrow},
        versions=version(driver, 'drivers'),
    )
    result = client.get(f'/api/v1/resource-unavailability?start_date={tomorrow}&end_date={tomorrow}').json()[
        'data'
    ]
    assert result['total'] == '1'
    for query in (
        'driver_id=1&vehicle_id=1',
        'start_date=2030-01-01',
        'start_date=2030-01-02&end_date=2030-01-01',
        'unknown=1',
    ):
        assert client.get('/api/v1/resource-unavailability?' + query).status_code == 422
    driver = client.get(f'/api/v1/drivers/{driver["id"]}').json()['data']
    deleted = write(client, 'DELETE_DRIVER', {}, driver['id'], version(driver, 'drivers'))
    assert deleted['summary_json']['changes'][-1]['field'] == 'resource_unavailability'
    assert client.get(f'/api/v1/resource-unavailability/{op["target_id"]}').status_code == 404
