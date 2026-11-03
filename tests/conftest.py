import pytest
from fastapi.testclient import TestClient

from app.database.session import build_engine
from app.legacy_main import create_app


@pytest.fixture
def client(tmp_path):
    engine = build_engine(f'sqlite:///{(tmp_path / "test.db").as_posix()}')
    app = create_app(engine, demo=False)
    with TestClient(app) as client:
        yield client
    engine.dispose()


@pytest.fixture
def fleet(client):
    for name, level in [('张三', 'HIGH'), ('李四', 'HIGH'), ('王五', 'MEDIUM'), ('赵六', 'LOW')]:
        response = client.post('/api/drivers', json={'name': name, 'efficiency_level': level})
        assert response.status_code == 201, response.text
    for index in range(2):
        response = client.post(
            '/api/vehicles',
            json={
                'plate_number': f'V{index}',
                'vehicle_name': f'车辆{index}',
                'capacities': [
                    {'shift': shift, 'max_tag_count': 100, 'max_road_km': '80.125'}
                    for shift in ('MORNING', 'AFTERNOON', 'NIGHT')
                ],
            },
        )
        assert response.status_code == 201, response.text
    return client


def create_plan(client, start='2026-11-05', end='2026-11-06', tags=100, road=None):
    payload = {
        'title': '测试采集计划',
        'start_date': start,
        'end_date': end,
        'tag_requirements': [{'tag_type': 'A', 'daily_count': tags}] if tags else [],
        'road_requirements': [{'road_type': 'CITY', 'daily_km': road}] if road else [],
    }
    response = client.post('/api/plans', json=payload)
    assert response.status_code == 201, response.text
    return response.json()['data']


def generate(client, plan):
    response = client.post(
        '/api/schedules/preview',
        json={'plan_id': plan['plan_id'], 'start_date': plan['start_date'], 'end_date': plan['end_date']},
    )
    assert response.status_code == 200, response.text
    return response.json()['data']['previews'][0]


def confirm(client, preview, dates=None, key='confirm-test'):
    return client.post(
        '/api/schedules/confirm',
        json={
            'preview_id': preview['preview_id'],
            'expected_version': preview['preview_version'],
            'confirm_dates': dates or [d['date'] for d in preview['daily_results']],
            'idempotency_key': key,
        },
    )
