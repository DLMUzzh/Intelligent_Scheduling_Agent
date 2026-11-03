from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.database.session import transaction
from app.models import (
    ConfirmationOperation,
    DailySchedule,
    Notification,
    ScheduleAssignment,
    SchedulePreview,
    utcnow,
)
from tests.conftest import confirm, create_plan, generate


def test_daily_expansion_and_overrides(client):
    response = client.post(
        '/api/plans',
        json={
            'title': '逐日任务',
            'start_date': '2026-11-05',
            'end_date': '2026-11-07',
            'tag_requirements': [{'tag_type': 'A', 'daily_count': 100}],
            'daily_overrides': [
                {'date': '2026-11-06', 'road_requirements': [{'road_type': 'CITY', 'daily_km': '0.001'}]}
            ],
        },
    )
    assert response.status_code == 201, response.text
    rows = client.get(f'/api/plans/{response.json()["data"]["plan_id"]}/daily-tasks').json()['data']
    assert len(rows) == 3
    assert rows[1]['tag_requirements'] == []
    assert rows[1]['road_requirements'][0]['km'] == '0.001'
    assert rows[2]['tag_requirements'][0]['count'] == 100


@pytest.mark.parametrize(
    'change',
    [
        {'end_date': '2026-11-01'},
        {'road_requirements': [{'road_type': 'CITY', 'daily_km': 0.2}]},
        {'tag_requirements': [{'tag_type': 'A', 'daily_count': 1.5}]},
        {'tag_requirements': [], 'road_requirements': []},
        {
            'daily_overrides': [
                {'date': '2026-12-01', 'tag_requirements': [{'tag_type': 'A', 'daily_count': 1}]}
            ]
        },
    ],
)
def test_invalid_plan_inputs(client, change):
    data = {
        'title': '测试',
        'start_date': '2026-11-05',
        'end_date': '2026-11-06',
        'tag_requirements': [{'tag_type': 'A', 'daily_count': 10}],
    } | change
    assert client.post('/api/plans', json=data).status_code == 422


def test_preview_does_not_reserve_resources_and_is_reused(fleet):
    plan = create_plan(fleet)
    first = generate(fleet, plan)
    second = generate(fleet, plan)
    assert first['preview_id'] == second['preview_id']
    assert fleet.get('/api/schedules').json()['data'] == []
    assert fleet.get('/api/notifications').json()['data'] == []
    assert len(fleet.get('/api/drivers/available?date=2026-11-05').json()['data']) == 4


def test_successful_edit_delete_add_and_version_conflict(fleet):
    preview = generate(fleet, create_plan(fleet))
    identifier = preview['preview_id']
    row = preview['daily_results'][0]['assignments'][0]
    url = f'/api/schedules/previews/{identifier}/assignments/{row["assignment_id"]}'
    edit = fleet.patch(url, json={'expected_version': 1, 'changes': {'driver_id': 4}})
    assert edit.status_code == 200, edit.text
    assert edit.json()['data']['preview_version'] == 2
    assert fleet.patch(url, json={'expected_version': 1, 'changes': {'driver_id': 3}}).status_code == 409
    deleted = fleet.delete(url, params={'expected_version': 2})
    assert deleted.status_code == 200
    day = deleted.json()['data']['daily_results'][0]
    assert sum(t['count'] for t in day['unallocated']['tags']) == sum(
        t['count'] for t in row['tag_allocations']
    )
    added = fleet.post(
        f'/api/schedules/previews/{identifier}/assignments',
        json={
            'expected_version': 3,
            'date': day['date'],
            'driver_id': 4,
            'vehicle_id': row['vehicle_id'],
            'shift': row['shift'],
            'task_mode': row['task_mode'],
            'tag_allocations': row['tag_allocations'],
            'road_allocations': row['road_allocations'],
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()['data']['preview_version'] == 4
    assert fleet.get('/api/notifications').json()['data'] == []


def test_invalid_edit_preserves_preview(fleet):
    preview = generate(fleet, create_plan(fleet))
    rows = preview['daily_results'][0]['assignments']
    response = fleet.patch(
        f'/api/schedules/previews/{preview["preview_id"]}/assignments/{rows[0]["assignment_id"]}',
        json={'expected_version': 1, 'changes': {'driver_id': rows[1]['driver_id']}},
    )
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DRIVER_CONFLICT'
    current = fleet.get(f'/api/schedules/previews/{preview["preview_id"]}').json()['data']
    assert current['preview_version'] == 1
    assert current['daily_results'] == preview['daily_results']


def test_partial_assignment_confirmed_and_not_carried(fleet):
    plan = create_plan(fleet, tags=1000, road='1000')
    preview = generate(fleet, plan)
    assert preview['status'] == 'PARTIAL'
    response = confirm(fleet, preview)
    assert response.status_code == 200, response.text
    assert response.json()['data']['notification_status'] == 'SENT'
    formal = fleet.get('/api/schedules').json()['data']
    assert all(day['auto_carry_forward'] is False for day in formal)
    next_plan = create_plan(fleet, start='2026-11-07', end='2026-11-07', tags=1)
    next_preview = generate(fleet, next_plan)
    assert next_preview['daily_results'][0]['metrics']['tag_target'] == 1


def test_confirm_idempotency_and_key_conflict(fleet):
    preview = generate(fleet, create_plan(fleet))
    first = confirm(fleet, preview)
    assert first.status_code == 200, first.text
    notifications = fleet.get('/api/notifications').json()['data']
    assert len(notifications) == 4
    repeated = confirm(fleet, preview)
    assert repeated.json()['data']['operation_status'] == 'ALREADY_CONFIRMED'
    assert repeated.json()['data']['notification_triggered'] is False
    assert len(fleet.get('/api/notifications').json()['data']) == len(notifications)
    assert (
        confirm(fleet, preview, key='another-key').json()['data']['operation_status'] == 'ALREADY_CONFIRMED'
    )
    other = generate(fleet, create_plan(fleet, start='2026-11-09', end='2026-11-09'))
    assert confirm(fleet, other).json()['error']['code'] == 'IDEMPOTENCY_KEY_REUSED'
    regenerated = fleet.post(
        '/api/schedules/preview',
        json={
            'plan_id': preview['plan_id'],
            'start_date': preview['start_date'],
            'end_date': preview['end_date'],
        },
    ).json()['data']
    assert regenerated['operation_status'] == 'ALREADY_CONFIRMED'
    assert regenerated['previews'] == []


def test_atomic_batch_conflict_preserves_previous_day(fleet):
    preview = generate(fleet, create_plan(fleet, end='2026-11-07'))
    assert confirm(fleet, preview, ['2026-11-05'], 'day-one').status_code == 200
    stale = generate(fleet, create_plan(fleet, start='2026-11-07', end='2026-11-07'))
    assert confirm(fleet, stale, key='other-plan').status_code == 200
    preview = fleet.get(f'/api/schedules/previews/{preview["preview_id"]}').json()['data']
    response = confirm(fleet, preview, key='batch')
    assert response.status_code == 409
    assert response.json()['error']['details']['rolled_back'] is True
    with transaction(fleet.app.state.session_factory) as db:
        rows = db.scalars(select(DailySchedule).where(DailySchedule.plan_id == preview['plan_id'])).all()
        assert [r.schedule_date.isoformat() for r in rows] == ['2026-11-05']
        assert db.get(ConfirmationOperation, 'batch') is None


def test_actual_storage_failure_rolls_back_all_inserts(fleet, monkeypatch):
    preview = generate(fleet, create_plan(fleet))
    from sqlalchemy import event

    def fail_on_second_day(mapper, connection, target):
        if target.work_date.isoformat() == '2026-11-06':
            raise RuntimeError('simulated storage failure')

    event.listen(ScheduleAssignment, 'before_insert', fail_on_second_day)
    try:
        with pytest.raises(RuntimeError):
            confirm(fleet, preview, key='storage-fail')
    finally:
        event.remove(ScheduleAssignment, 'before_insert', fail_on_second_day)
    with transaction(fleet.app.state.session_factory) as db:
        for model in (DailySchedule, ScheduleAssignment, Notification):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_notifications_failure_retry_and_sent_idempotence(fleet):
    class FailingSender:
        def send(self, content, idempotency_key):
            raise RuntimeError('测试通知通道失败')

    preview = generate(fleet, create_plan(fleet, end='2026-11-05'))
    fleet.app.state.notifications.sender = FailingSender()
    response = confirm(fleet, preview)
    assert response.json()['data']['notification_status'] == 'FAILED'
    assert len(fleet.get('/api/schedules').json()['data']) == 1
    row = fleet.get('/api/notifications').json()['data'][0]
    assert row['status'] == 'FAILED'
    assert '测试通知通道失败' in row['error_message']
    from app.notifications.console_sender import ConsoleSender

    fleet.app.state.notifications.sender = ConsoleSender()
    retried = fleet.post(f'/api/notifications/{row["id"]}/retry').json()['data']
    assert retried['status'] == 'SENT' and retried['retry_count'] == 1
    twice = fleet.post(f'/api/notifications/{row["id"]}/retry').json()['data']
    assert twice['retry_count'] == 1


def test_unavailability_qualification_capacity_changes_rechecked(fleet):
    preview = generate(fleet, create_plan(fleet))
    row = preview['daily_results'][0]['assignments'][0]
    assert (
        fleet.post(
            f'/api/drivers/{row["driver_id"]}/unavailability',
            json={'start_date': '2026-11-05', 'end_date': '2026-11-05', 'reason': '请假'},
        ).status_code
        == 201
    )
    available = fleet.get('/api/drivers/available?date=2026-11-05').json()['data']
    assert row['driver_id'] not in {d['id'] for d in available}
    response = confirm(fleet, preview)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'RESOURCE_UNAVAILABLE'
    assert fleet.get('/api/schedules').json()['data'] == []


def test_discard_expiry_and_regenerate(fleet):
    plan = create_plan(fleet)
    preview = generate(fleet, plan)
    discarded = fleet.post(
        f'/api/schedules/previews/{preview["preview_id"]}/discard', json={'expected_version': 1}
    )
    assert discarded.status_code == 200
    newer = generate(fleet, plan)
    assert newer['preview_id'] != preview['preview_id']
    with transaction(fleet.app.state.session_factory, write=True) as db:
        row = db.get(SchedulePreview, newer['preview_id'])
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert confirm(fleet, newer).status_code == 409
    latest = generate(fleet, plan)
    assert latest['preview_id'] != newer['preview_id']


def test_concurrent_confirmation_prevents_double_booking(fleet):
    p1 = generate(fleet, create_plan(fleet, end='2026-11-05'))
    p2 = generate(fleet, create_plan(fleet, end='2026-11-05'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda pair: confirm(fleet, pair[0], key=pair[1]), [(p1, 'parallel-1'), (p2, 'parallel-2')]
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(fleet.get('/api/schedules').json()['data']) == 1


def test_auth_and_agent_boundaries(client, monkeypatch):
    monkeypatch.setattr(settings, 'api_key', 'integration-secret')
    assert client.get('/api/drivers').status_code == 401
    assert client.get('/api/drivers', headers={'X-API-Key': 'integration-secret'}).status_code == 200
    assert client.get('/health').status_code == 200
    caps = client.get('/api/capabilities', headers={'X-API-Key': 'integration-secret'}).json()['data']
    assert caps['agent']['implemented'] is False
    assert (
        client.post(
            '/api/agent/chat', headers={'X-API-Key': 'integration-secret'}, json={'message': '测试'}
        ).status_code
        == 404
    )


def test_dashboard_assets_statistics_and_audit(fleet):
    response = fleet.get('/')
    assert response.status_code == 200 and 'Fleetwise' in response.text
    assert 'frame-ancestors' in response.headers['Content-Security-Policy']
    assert fleet.get('/static/app.js').status_code == 200
    preview = generate(fleet, create_plan(fleet, end='2026-11-05'))
    confirm(fleet, preview)
    stats = fleet.get('/api/schedules/statistics').json()['data']
    assert stats['tag_target'] == stats['tag_assigned'] == 100
    assert stats['road_coverage_rate'] is None
    assert stats['assignment_count'] == 2
    assert any(row['action'] == 'CONFIRM_SCHEDULE' for row in fleet.get('/api/audit-logs').json()['data'])


def test_algorithm_quality_metrics(fleet):
    preview = generate(fleet, create_plan(fleet))
    assert preview['quality']['algorithm_runtime_ms'] >= 0
    assert preview['quality']['hard_constraint_violations_detected'] == 0
    assert preview['quality']['driver_efficiency_distribution'] == {'HIGH': 4, 'MEDIUM': 0, 'LOW': 0}
    assert preview['quality']['driver_shift_dispersion_by_efficiency']['HIGH']['population_stddev'] == 0
    assert (
        preview['daily_results'][0]['quality']['vehicle_utilization_dispersion_by_mode']['TAG'][
            'population_stddev'
        ]
        == 0
    )


def test_no_assignment_cannot_confirm_and_overlapping_range_reused(client):
    plan = create_plan(client)
    preview = generate(client, plan)
    assert preview['status'] == 'NO_ASSIGNMENT'
    response = confirm(client, preview)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'NO_ASSIGNMENT'
    narrower = client.post(
        '/api/schedules/preview',
        json={'plan_id': plan['plan_id'], 'start_date': '2026-11-06', 'end_date': '2026-11-06'},
    )
    assert narrower.json()['data']['previews'][0]['preview_id'] == preview['preview_id']
