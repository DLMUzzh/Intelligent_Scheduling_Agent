import json
from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time import business_date
from app.models.foundation import CollectionPlan, DailyDemand, PlanDay, TaskAllocation, TaskPackage
from tests.base_data.conftest import create_driver, create_vehicle, execute, prepare, version, write
from tests.base_data.scenarios import add_formal_history, formal_snapshot, seed_days


def setup_resources(client):
    driver, vehicle = create_driver(client), create_vehicle(client)
    op = write(client, 'CREATE_CATEGORY', {'task_mode': 'TAG', 'name': '原类别'})
    category = client.get('/api/v1/collection-categories').json()['data']['items'][0]
    assert category['id'] == op['target_id']
    return driver, vehicle, category


def test_category_rename_refreshes_future_demand_and_draft_only(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    today = business_date().isoformat()
    plan_id, days = seed_days(
        engine, [today, tomorrow], int(category['id']), int(driver['id']), int(vehicle['id'])
    )
    op = write(
        client,
        'UPDATE_CATEGORY',
        {'name': '新类别'},
        category['id'],
        version(category, 'collection_categories'),
    )
    assert op['summary_json']['affected_dates'] == [tomorrow]
    assert len(op['summary_json']['related_changes']) == 1
    with Session(engine) as db:
        demands = list(db.scalars(select(DailyDemand).order_by(DailyDemand.plan_day_id)))
        allocations = list(db.scalars(select(TaskAllocation).order_by(TaskAllocation.id)))
        assert [value.category_name_snapshot for value in demands] == ['原类别', '新类别']
        assert [value.category_name_snapshot for value in allocations] == ['原类别', '新类别']
        assert json.loads(db.get(PlanDay, days[0]).draft_metadata_json)['needs_revalidation'] == 0
        assert json.loads(db.get(PlanDay, days[1]).draft_metadata_json)['needs_revalidation'] == 1
        assert db.get(PlanDay, days[0]).version == 1 and db.get(PlanDay, days[1]).version == 2
        assert db.get(CollectionPlan, plan_id).version == 2
    audit = client.get('/api/v1/audit-logs').json()['data']['items'][0]
    details = client.get(f'/api/v1/audit-logs/{audit["id"]}').json()['data']['changes_json']
    assert any('daily_demands' in item['field'] for item in details['changes'])


@pytest.mark.parametrize('reference', ['demand', 'allocation', 'basis'])
def test_category_deletion_protects_all_current_reference_sources(base_data, tomorrow, reference):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    with Session(engine) as db:
        if reference != 'demand':
            db.execute(delete(DailyDemand))
        if reference == 'basis':
            db.execute(delete(TaskAllocation))
            db.execute(delete(TaskPackage))
        db.commit()
    response = prepare(
        client, 'DELETE_CATEGORY', {}, category['id'], version(category, 'collection_categories')
    )
    assert response.status_code == 409 and response.json()['code'] == 'RESOURCE_REFERENCED'


@pytest.mark.parametrize('target', ['DRIVER', 'VEHICLE', 'CATEGORY'])
def test_all_formal_history_before_after_protect_deletion(base_data, tomorrow, target):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    _, days = seed_days(
        engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']), kind='FORMAL'
    )
    with Session(engine) as db:
        before = formal_snapshot(db, days[0])
        after = before | {
            'header': before['header'] | {'formal_status': 'CANCELLED', 'formal_version': 2},
            'packages': [],
            'demands': [],
        }
        add_formal_history(db, days[0], before, after)
        # Later events no longer reference these resources. The earlier before side still protects them.
        add_formal_history(db, days[0], after, after, version=3)
        db.execute(delete(TaskAllocation))
        db.execute(delete(TaskPackage))
        db.execute(delete(DailyDemand))
        day = db.get(PlanDay, days[0])
        day.formal_status = 'CANCELLED'
        day.formal_version = 3
        db.commit()
    row, table = {
        'DRIVER': (driver, 'drivers'),
        'VEHICLE': (vehicle, 'vehicles'),
        'CATEGORY': (category, 'collection_categories'),
    }[target]
    response = prepare(client, f'DELETE_{target}', {}, row['id'], version(row, table))
    assert response.status_code == 409 and response.json()['code'] == 'RESOURCE_REFERENCED'


@pytest.mark.parametrize(
    'target,patch,error',
    [
        ('DRIVER', {'is_enabled': 0}, 'RESOURCE_UNAVAILABLE'),
        ('DRIVER', {'can_morning': 0}, 'SHIFT_NOT_QUALIFIED'),
        ('VEHICLE', {'morning_max_tag_count': '4'}, 'CAPACITY_EXCEEDED'),
        ('VEHICLE', {'is_enabled': 0}, 'RESOURCE_UNAVAILABLE'),
    ],
)
def test_future_formal_protection_lists_every_affected_day(base_data, tomorrow, target, patch, error):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    next_day = (business_date() + timedelta(days=2)).isoformat()
    seed_days(
        engine,
        [tomorrow, next_day],
        int(category['id']),
        int(driver['id']),
        int(vehicle['id']),
        kind='FORMAL',
    )
    row, table = (driver, 'drivers') if target == 'DRIVER' else (vehicle, 'vehicles')
    response = prepare(client, f'UPDATE_{target}', patch, row['id'], version(row, table))
    assert response.status_code == 409 and response.json()['code'] == 'FUTURE_SCHEDULE_INVALID'
    assert [item['work_date'] for item in response.json()['errors']] == [tomorrow, next_day]
    assert all(item['code'] == error for item in response.json()['errors'])
    assert client.get(f'/api/v1/{table}/{row["id"]}').json()['data']['version'] == '1'
    # Names and efficiency do not rewrite current formal snapshots or reassign tasks.
    write(client, f'UPDATE_{target}', {'name': '改名'}, row['id'], version(row, table))
    with Session(engine) as db:
        assert all(value.driver_name_snapshot == '原司机' for value in db.scalars(select(TaskPackage)))


def test_future_formal_capacity_check_uses_package_sum_and_road_units(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    seed_days(
        engine,
        [tomorrow],
        int(category['id']),
        int(driver['id']),
        int(vehicle['id']),
        kind='FORMAL',
        mode='ROAD',
    )
    response = prepare(
        client,
        'UPDATE_VEHICLE',
        {'morning_max_road_meters': '4999'},
        vehicle['id'],
        version(vehicle, 'vehicles'),
    )
    assert response.json()['code'] == 'FUTURE_SCHEDULE_INVALID'
    write(
        client,
        'UPDATE_VEHICLE',
        {'morning_max_road_meters': '5000'},
        vehicle['id'],
        version(vehicle, 'vehicles'),
    )


def test_capacity_refresh_freezes_today_and_audits_actual_new_vehicle_id(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    today = business_date().isoformat()
    _, days = seed_days(engine, [today, tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    with Session(engine) as db:
        frozen = db.get(PlanDay, days[0]).vehicle_capacities_json
    new_vehicle = create_vehicle(client, plate_number='新车')
    with Session(engine) as db:
        assert db.get(PlanDay, days[0]).vehicle_capacities_json == frozen
        future = db.get(PlanDay, days[1])
        rows = json.loads(future.vehicle_capacities_json)
        assert len(rows) == 6 and {row['vehicle_id'] for row in rows} == {
            int(vehicle['id']),
            int(new_vehicle['id']),
        }
        assert future.capacity_basis_revision == int(client.get('/api/v1/context').json()['data_revision'])
    audit_id = client.get('/api/v1/audit-logs').json()['data']['items'][0]['id']
    changes = client.get(f'/api/v1/audit-logs/{audit_id}').json()['data']['changes_json']['changes']
    capacity_change = next(item for item in changes if item['field'].endswith('vehicle_capacities_json'))
    assert new_vehicle['id'] in {row['vehicle_id'] for row in capacity_change['after']}
    write(client, 'DELETE_VEHICLE', {}, new_vehicle['id'], version(new_vehicle, 'vehicles'))
    with Session(engine) as db:
        assert len(json.loads(db.get(PlanDay, days[1]).vehicle_capacities_json)) == 3


def test_maintenance_overlap_union_and_formal_impact(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    _, days = seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    payload = {'vehicle_id': vehicle['id'], 'start_date': tomorrow, 'end_date': tomorrow}
    first = write(client, 'CREATE_UNAVAILABILITY', payload, versions=version(vehicle, 'vehicles'))
    vehicle = client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']
    write(client, 'CREATE_UNAVAILABILITY', payload, versions=version(vehicle, 'vehicles'))
    row = client.get(f'/api/v1/resource-unavailability/{first["target_id"]}').json()['data']
    vehicle = client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']
    write(
        client,
        'DELETE_UNAVAILABILITY',
        {},
        row['id'],
        version(row, 'resource_unavailability') | version(vehicle, 'vehicles'),
    )
    with Session(engine) as db:
        assert {
            row['is_available'] for row in json.loads(db.get(PlanDay, days[0]).vehicle_capacities_json)
        } == {0}
        package = db.scalar(select(TaskPackage))
        package.schedule_kind = 'FORMAL'
        day = db.get(PlanDay, days[0])
        day.formal_status = 'ACTIVE'
        day.formal_version = 1
        day.draft_metadata_json = None
        db.commit()
    vehicle = client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']
    response = prepare(client, 'CREATE_UNAVAILABILITY', payload, versions=version(vehicle, 'vehicles'))
    assert response.json()['code'] == 'FUTURE_SCHEDULE_INVALID'


def test_associated_write_failure_rolls_back_everything(base_data, tomorrow, monkeypatch):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    _, days = seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    operation = prepare(
        client, 'UPDATE_VEHICLE', {'morning_max_tag_count': '20'}, vehicle['id'], version(vehicle, 'vehicles')
    ).json()['data']
    import app.services.base_data_service as service

    original = service.apply_related

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated storage write failure')

    monkeypatch.setattr(service, 'apply_related', broken)
    response = execute(client, operation)
    assert response.status_code == 500 and response.json()['data']['status'] == 'FAILED'
    assert client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']['morning_max_tag_count'] == '10'
    with Session(engine) as db:
        day = db.get(PlanDay, days[0])
        assert day.version == 1 and json.loads(day.draft_metadata_json)['needs_revalidation'] == 0
        assert json.loads(day.vehicle_capacities_json)[0]['max_tag_count'] == 10
    audit = client.get('/api/v1/audit-logs').json()['data']['items'][0]
    assert audit['outcome'] == 'FAILED'


def test_unavailability_commit_crossing_midnight_rolls_back(base_data, tomorrow, monkeypatch):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    _, days = seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    operation = prepare(
        client,
        'CREATE_UNAVAILABILITY',
        {
            'driver_id': driver['id'],
            'start_date': tomorrow,
            'end_date': tomorrow,
        },
        versions=version(driver, 'drivers'),
    ).json()['data']
    from datetime import date

    import app.services.base_data_service as service
    import app.services.confirmation_service as common

    original = service.apply_related

    def cross_midnight(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(common, 'business_date', lambda: date.fromisoformat(tomorrow))
        return result

    monkeypatch.setattr(service, 'apply_related', cross_midnight)
    response = execute(client, operation)
    assert response.status_code == 409 and response.json()['code'] == 'DATE_LOCKED'
    assert client.get('/api/v1/resource-unavailability').json()['data']['total'] == '0'
    assert client.get(f'/api/v1/drivers/{driver["id"]}').json()['data']['version'] == '1'
    with Session(engine) as db:
        assert db.get(PlanDay, days[0]).version == 1


def test_category_rename_does_not_rewrite_formal_allocations_or_history(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    _, days = seed_days(
        engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']), kind='FORMAL'
    )
    from app.models.foundation import AuditLog

    with Session(engine) as db:
        snapshot = formal_snapshot(db, days[0])
        audit_id = add_formal_history(db, days[0], snapshot, snapshot)
        db.commit()
        frozen = db.get(AuditLog, audit_id).changes_json
    write(
        client,
        'UPDATE_CATEGORY',
        {'name': '类别新名称'},
        category['id'],
        version(category, 'collection_categories'),
    )
    with Session(engine) as db:
        assert db.scalar(select(DailyDemand)).category_name_snapshot == '类别新名称'
        assert db.scalar(select(TaskAllocation)).category_name_snapshot == '原类别'
        assert db.get(AuditLog, audit_id).changes_json == frozen


def test_only_capacity_in_formal_history_allows_vehicle_deletion(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    extra = create_vehicle(client, plate_number='纯容量历史车辆')
    _, days = seed_days(
        engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']), kind='FORMAL'
    )
    from app.models.foundation import AuditLog

    with Session(engine) as db:
        snapshot = formal_snapshot(db, days[0])
        audit_id = add_formal_history(db, days[0], snapshot, snapshot)
        db.commit()
        frozen = db.get(AuditLog, audit_id).changes_json
    write(client, 'DELETE_VEHICLE', {}, extra['id'], version(extra, 'vehicles'))
    assert client.get(f'/api/v1/vehicles/{extra["id"]}').status_code == 404
    with Session(engine) as db:
        assert db.get(AuditLog, audit_id).changes_json == frozen
        assert len(json.loads(db.get(PlanDay, days[0]).vehicle_capacities_json)) == 3


def test_invalid_capacity_snapshot_prevents_partial_resource_change(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    _, days = seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    with Session(engine) as db:
        day = db.get(PlanDay, days[0])
        rows = json.loads(day.vehicle_capacities_json)
        day.vehicle_capacities_json = json.dumps(rows[:1])
        db.commit()
    response = prepare(
        client, 'UPDATE_VEHICLE', {'name': '不可保存'}, vehicle['id'], version(vehicle, 'vehicles')
    )
    assert response.status_code == 500 and response.json()['code'] == 'DATA_INTEGRITY_ERROR'
    assert client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']['name'] is None


def test_unavailability_only_marks_drafts_in_its_old_and_new_intervals(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    outside = (business_date() + timedelta(days=4)).isoformat()
    _, days = seed_days(
        engine, [tomorrow, outside], int(category['id']), int(driver['id']), int(vehicle['id'])
    )
    operation = write(
        client,
        'CREATE_UNAVAILABILITY',
        {
            'driver_id': driver['id'],
            'start_date': tomorrow,
            'end_date': tomorrow,
        },
        versions=version(driver, 'drivers'),
    )
    assert operation['summary_json']['affected_dates'] == [tomorrow]
    with Session(engine) as db:
        assert json.loads(db.get(PlanDay, days[0]).draft_metadata_json)['needs_revalidation'] == 1
        assert json.loads(db.get(PlanDay, days[1]).draft_metadata_json)['needs_revalidation'] == 0


def test_formal_vehicle_capacity_checks_sum_of_multiple_categories(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    write(
        client, 'UPDATE_VEHICLE', {'morning_max_tag_count': '20'}, vehicle['id'], version(vehicle, 'vehicles')
    )
    vehicle = client.get(f'/api/v1/vehicles/{vehicle["id"]}').json()['data']
    second = write(client, 'CREATE_CATEGORY', {'task_mode': 'TAG', 'name': '另一类别'})
    seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']), kind='FORMAL')
    with Session(engine) as db:
        package = db.scalar(select(TaskPackage))
        package.max_tag_count_snapshot = 20
        db.add(
            DailyDemand(
                plan_day_id=package.plan_day_id,
                collection_category_id=int(second['target_id']),
                category_name_snapshot='另一类别',
                task_mode='TAG',
                target_tag_count=10,
                sort_order=2,
            )
        )
        db.add(
            TaskAllocation(
                task_package_id=package.id,
                collection_category_id=int(second['target_id']),
                category_name_snapshot='另一类别',
                task_mode='TAG',
                assigned_tag_count=6,
            )
        )
        db.commit()
    response = prepare(
        client, 'UPDATE_VEHICLE', {'morning_max_tag_count': '10'}, vehicle['id'], version(vehicle, 'vehicles')
    )
    assert response.json()['code'] == 'FUTURE_SCHEDULE_INVALID'
    assert response.json()['errors'][0]['code'] == 'CAPACITY_EXCEEDED'


def test_resource_read_counts_only_active_formal_packages(base_data, tomorrow):
    client, engine = base_data
    driver, vehicle, category = setup_resources(client)
    other_date = (business_date() + timedelta(days=2)).isoformat()
    seed_days(engine, [tomorrow], int(category['id']), int(driver['id']), int(vehicle['id']))
    seed_days(engine, [other_date], int(category['id']), int(driver['id']), int(vehicle['id']), kind='FORMAL')
    for table, row in [('drivers', driver), ('vehicles', vehicle)]:
        current = client.get(f'/api/v1/{table}/{row["id"]}?work_date={other_date}').json()['data']
        assert current['scheduled_shift_count'] == '1'
        assert current['is_available'] == 1
