from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.base_data.conftest import (
    create_driver,
    create_vehicle,
    execute,
    prepare,
    vehicle_payload,
    version,
    write,
)


def test_driver_defaults_duplicate_names_grades_and_all_qualifications(base_data):
    client, _ = base_data
    driver = create_driver(client)
    assert driver['efficiency_level'] == 'MEDIUM'
    assert [driver[key] for key in ('is_enabled', 'can_morning', 'can_middle', 'can_evening')] == [1, 1, 1, 1]
    second = create_driver(client, efficiency_level='LOW', can_morning=0, can_middle=0, can_evening=0)
    assert driver['id'] != second['id'] and second['is_available'] == 1
    write(
        client,
        'UPDATE_DRIVER',
        {'efficiency_level': 'HIGH', 'phone': '123', 'can_middle': 0},
        driver['id'],
        version(driver, 'drivers'),
    )
    updated = client.get(f'/api/v1/drivers/{driver["id"]}').json()['data']
    assert updated['version'] == '2' and updated['can_morning'] == 1 and updated['can_middle'] == 0
    assert updated['efficiency_level'] == 'HIGH' and updated['phone'] == '123'
    write(
        client, 'UPDATE_DRIVER', {'phone': None, 'is_enabled': 0}, driver['id'], version(updated, 'drivers')
    )
    disabled = client.get(f'/api/v1/drivers/{driver["id"]}').json()['data']
    assert disabled['phone'] is None and disabled['is_available'] == 0
    assert (
        client.get('/api/v1/drivers?efficiency_level=HIGH&is_enabled=0&is_available=0').json()['data'][
            'total'
        ]
        == '1'
    )
    write(client, 'DELETE_DRIVER', {}, driver['id'], version(disabled, 'drivers'))
    assert client.get(f'/api/v1/drivers/{driver["id"]}').status_code == 404


@pytest.mark.parametrize(
    'patch',
    [
        {},
        {'name': None},
        {'is_enabled': True},
        {'can_middle': '0'},
        {'can_evening': 2},
        {'efficiency_level': 'FAST'},
        {'phone': 'x' * 41},
        {'name': 'x' * 101},
        {'name': ' '},
        {'id': '1'},
    ],
)
def test_driver_rejects_invalid_patches(base_data, patch):
    client, _ = base_data
    driver = create_driver(client)
    response = prepare(client, 'UPDATE_DRIVER', patch, driver['id'], version(driver, 'drivers'))
    assert response.status_code == 422, response.text


def test_vehicle_six_capacities_plate_normalization_and_update(base_data):
    client, engine = base_data
    vehicle = create_vehicle(client, plate_number=' 辽b 12345 ', name='测试车')
    assert vehicle['plate_number'] == '辽b 12345'
    assert vehicle['morning_max_road_meters'] == '12500'
    assert vehicle['middle_max_road_meters'] == '0'
    assert vehicle['evening_max_road_meters'] == '30001'
    assert 'plate_key' not in vehicle
    duplicate = prepare(client, 'CREATE_VEHICLE', vehicle_payload(plate_number='辽B\t12345'))
    assert duplicate.status_code == 409 and duplicate.json()['code'] == 'DUPLICATE_PLATE'
    write(
        client,
        'UPDATE_VEHICLE',
        {'morning_max_tag_count': '9223372036854775807', 'name': None, 'notes': '备注'},
        vehicle['id'],
        version(vehicle, 'vehicles'),
    )
    row = client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']
    assert row['morning_max_tag_count'] == '9223372036854775807' and row['name'] is None
    assert row['middle_max_tag_count'] == '20' and row['version'] == '2'
    assert client.get('/api/v1/vehicles?q=12345').json()['data']['total'] == '1'
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT plate_key FROM vehicles').scalar_one() == '辽B12345'
    write(client, 'UPDATE_VEHICLE', {'is_enabled': 0}, row['id'], version(row, 'vehicles'))
    row = client.get(f'/api/v1/vehicles/{row["id"]}').json()['data']
    assert row['is_available'] == 0
    write(client, 'DELETE_VEHICLE', {}, row['id'], version(row, 'vehicles'))
    assert client.get('/api/v1/vehicles').json()['data']['total'] == '0'


@pytest.mark.parametrize('value', ['-1', '1.1', '01', '+1', '1e3', '9223372036854775808', 1, 1.0, True, None])
def test_vehicle_capacity_is_bounded_exact_integer_text(base_data, value):
    client, _ = base_data
    response = prepare(client, 'CREATE_VEHICLE', vehicle_payload(morning_max_tag_count=value))
    assert response.status_code == 422 and response.json()['errors']


def test_vehicle_requires_all_capacities_and_supports_zero(base_data):
    client, _ = base_data
    payload = vehicle_payload()
    del payload['evening_max_tag_count']
    assert prepare(client, 'CREATE_VEHICLE', payload).status_code == 422
    fields = {key: '0' for key in vehicle_payload() if key != 'plate_number'}
    zero = create_vehicle(client, **fields)
    assert zero['is_available'] == 1
    assert prepare(client, 'CREATE_VEHICLE', vehicle_payload(plate_number='x' * 31)).status_code == 422


def test_two_prepared_duplicate_plates_cannot_both_execute(base_data):
    client, _ = base_data
    first = prepare(client, 'CREATE_VEHICLE', vehicle_payload()).json()['data']
    second = prepare(client, 'CREATE_VEHICLE', vehicle_payload()).json()['data']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda operation: execute(client, operation), [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get('/api/v1/vehicles').json()['data']['total'] == '1'


@pytest.mark.parametrize(
    'path',
    [
        '/drivers/01',
        '/vehicles/9223372036854775808',
        '/drivers/0',
        '/drivers?is_enabled=true',
        '/drivers?work_date=2026-02-30',
        '/vehicles?work_date=20261104',
        '/drivers?efficiency_level=high',
        '/vehicles?efficiency_level=HIGH',
        '/drivers/1?unknown=1',
        '/vehicles?page_size=101',
    ],
)
def test_resource_query_contract(base_data, path):
    client, _ = base_data
    assert client.get('/api/v1' + path).status_code == 422


def test_actual_business_adapters_replay_after_restarting_service(base_data):
    from sqlalchemy.orm import sessionmaker

    from app.schemas.operations import ExecuteInput
    from app.services.base_data_service import base_data_adapters
    from app.services.confirmation_service import ConfirmationService

    client, engine = base_data
    prepared = prepare(client, 'CREATE_VEHICLE', vehicle_payload()).json()['data']
    first = execute(client, prepared).json()['data']
    restarted = ConfirmationService(sessionmaker(bind=engine, expire_on_commit=False), base_data_adapters())
    replay = restarted.execute(
        int(prepared['id']), ExecuteInput(request_hash=prepared['request_hash'], confirmed=True)
    )
    assert replay.data == first
    assert client.get('/api/v1/vehicles').json()['data']['total'] == '1'
