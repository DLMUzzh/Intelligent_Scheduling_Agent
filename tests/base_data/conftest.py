from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.runtime import RuntimeSettings
from app.core.time import business_date
from app.database.foundation import build_engine
from app.main import create_app

ORIGIN = {'Origin': 'http://127.0.0.1:8000'}


@pytest.fixture
def base_data(tmp_path):
    config = RuntimeSettings(
        database_url=f'sqlite:///{(tmp_path / "data.db").as_posix()}', log_directory=tmp_path / 'logs'
    )
    engine = build_engine(config)
    app = create_app(engine, config=config)
    with TestClient(
        app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000), raise_server_exceptions=False
    ) as client:
        yield client, engine
    engine.dispose()


@pytest.fixture
def tomorrow():
    return (business_date() + timedelta(days=1)).isoformat()


def prepare(client, action, payload, target_id=None, versions=None, key=None):
    expected = {'business_revision': client.get('/api/v1/context').json()['data_revision']} | (versions or {})
    request = {
        'request_key': key or str(uuid4()),
        'action_code': action,
        'target_type': action.split('_', 1)[1],
        'target_id': target_id,
        'payload': payload,
        'expected_versions_json': expected,
    }
    return client.post('/api/v1/operations', json=request, headers=ORIGIN)


def execute(client, operation):
    return client.post(
        f'/api/v1/operations/{operation["id"]}/executions',
        json={'request_hash': operation['request_hash'], 'confirmed': True},
        headers=ORIGIN,
    )


def write(client, action, payload, target_id=None, versions=None):
    response = prepare(client, action, payload, target_id, versions)
    assert response.status_code == 201, response.text
    result = execute(client, response.json()['data'])
    assert result.status_code == 200, result.text
    return result.json()['data']


def create_driver(client, **fields):
    operation = write(client, 'CREATE_DRIVER', {'name': '张师傅'} | fields)
    return client.get(f'/api/v1/drivers/{operation["target_id"]}').json()['data']


def vehicle_payload(**fields):
    return {
        'plate_number': '辽B12345',
        'morning_max_tag_count': '10',
        'morning_max_road_meters': '12500',
        'middle_max_tag_count': '20',
        'middle_max_road_meters': '0',
        'evening_max_tag_count': '0',
        'evening_max_road_meters': '30001',
    } | fields


def create_vehicle(client, **fields):
    operation = write(client, 'CREATE_VEHICLE', vehicle_payload(**fields))
    return client.get(f'/api/v1/vehicles/{operation["target_id"]}').json()['data']


def version(row, table):
    return {table: [{'id': row['id'], 'version': row['version']}]}
