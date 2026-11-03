import random
from collections import Counter

import pytest

from app.core.exceptions import BusinessError
from app.scheduling.constraints import ConstraintValidator
from app.scheduling.interfaces import DriverResource, SchedulingInput, VehicleResource
from app.scheduling.strategies.greedy import GreedySchedulingStrategy
from app.schemas import km_to_meters, meters_to_km


def driver(identifier, level='HIGH', shifts=('MORNING', 'AFTERNOON', 'NIGHT')):
    return DriverResource(identifier, f'D{identifier}', level, shifts)


def vehicle(identifier, tag=100, road=100000):
    return VehicleResource(
        identifier,
        f'V{identifier}',
        f'PLATE-{identifier}',
        {shift: {'TAG': tag, 'ROAD': road} for shift in ('MORNING', 'AFTERNOON', 'NIGHT')},
    )


def input_data(drivers=None, vehicles=None, tag=100, road=0):
    return SchedulingInput(
        '2026-11-05',
        {'A': tag} if tag else {},
        {'CITY': road} if road else {},
        drivers or [driver(1), driver(2, 'MEDIUM'), driver(3, 'LOW')],
        vehicles or [vehicle(1)],
    )


def test_efficiency_priority():
    data = input_data(drivers=[driver(3, 'LOW'), driver(2, 'MEDIUM'), driver(1)])
    data.driver_workloads = {1: 50, 2: 0, 3: 0}
    result = GreedySchedulingStrategy().generate(data)
    assert [r['driver_id'] for r in result] == [1]


def test_same_grade_balancing():
    data = input_data(drivers=[driver(1), driver(2)])
    data.driver_workloads = {1: 3, 2: 1}
    assert GreedySchedulingStrategy().generate(data)[0]['driver_id'] == 2


@pytest.mark.parametrize('capacities,expected', [([100, 100], [50, 50]), ([100, 50], [67, 33])])
def test_vehicle_utilization_balance(capacities, expected):
    data = input_data(
        drivers=[driver(1), driver(2)], vehicles=[vehicle(1, capacities[0]), vehicle(2, capacities[1])]
    )
    result = GreedySchedulingStrategy().generate(data)
    ConstraintValidator().validate(data, result)
    assert [sum(r['tags'].values()) for r in result] == expected


def test_coverage_precedes_balancing_when_drivers_scarce():
    data = input_data(drivers=[driver(1)], vehicles=[vehicle(1, 20), vehicle(2, 100)])
    result = GreedySchedulingStrategy().generate(data)
    assert result[0]['vehicle_id'] == 2
    assert result[0]['tags'] == {'A': 100}


def test_daily_mode_and_driver_constraints():
    data = input_data(
        drivers=[driver(i) for i in range(1, 8)], vehicles=[vehicle(1), vehicle(2)], tag=350, road=150000
    )
    result = GreedySchedulingStrategy().generate(data)
    ConstraintValidator().validate(data, result)
    assert len({r['driver_id'] for r in result}) == len(result)
    for vehicle_id in (1, 2):
        assert len({r['task_mode'] for r in result if r['vehicle_id'] == vehicle_id}) <= 1


def test_existing_occupancy_respected():
    data = input_data(vehicles=[vehicle(1), vehicle(2)], road=100000)
    data.existing_assignments = [{'vehicle_id': 1, 'driver_id': 1, 'shift': 'MORNING', 'task_mode': 'TAG'}]
    result = GreedySchedulingStrategy().generate(data)
    ConstraintValidator().validate(data, result)
    assert all(r['driver_id'] != 1 for r in result)
    assert all(r['vehicle_id'] != 1 or r['task_mode'] == 'TAG' for r in result)


@pytest.mark.parametrize(
    'change,code',
    [
        ({'driver_id': 1}, 'DRIVER_CONFLICT'),
        ({'task_mode': 'ROAD', 'tags': {}, 'roads': {'CITY': 1}}, 'VEHICLE_MODE_CONFLICT'),
        ({'tags': {'A': 101}}, 'CAPACITY_EXCEEDED'),
    ],
)
def test_validator_rejects_hard_conflicts(change, code):
    data = input_data(drivers=[driver(1), driver(2)], tag=100, road=100000)
    data.existing_assignments = [{'vehicle_id': 1, 'driver_id': 1, 'shift': 'MORNING', 'task_mode': 'TAG'}]
    row = {
        'vehicle_id': 1,
        'driver_id': 2,
        'shift': 'AFTERNOON',
        'task_mode': 'TAG',
        'tags': {'A': 50},
        'roads': {},
    } | change
    with pytest.raises(BusinessError) as error:
        ConstraintValidator().validate(data, [row])
    assert error.value.code == code


def test_qualification_and_disabled_shift():
    data = input_data(drivers=[driver(1, shifts=('NIGHT',))])
    data.enabled_shifts = ('MORNING',)
    assert GreedySchedulingStrategy().generate(data) == []


def test_multiday_driver_balance():
    workloads = Counter()
    for _ in range(7):
        data = input_data(drivers=[driver(1), driver(2), driver(3)])
        data.driver_workloads = dict(workloads)
        rows = GreedySchedulingStrategy().generate(data)
        workloads.update(r['driver_id'] for r in rows)
    assert max(workloads.values()) - min(workloads.values()) <= 1


@pytest.mark.parametrize(
    'km,meters', [('0.001', 1), ('80.125', 80125), ('100', 100000), ('0', 0), ('0.010', 10)]
)
def test_exact_road_units(km, meters):
    assert km_to_meters(km) == meters
    assert km_to_meters(meters_to_km(meters)) == meters


@pytest.mark.parametrize('invalid', ['0.0001', '-1', 'NaN', 'Infinity', 'abc', '1000001', 1.2, True])
def test_invalid_road_units(invalid):
    with pytest.raises(ValueError):
        km_to_meters(invalid)


def test_randomized_resources_always_satisfy_constraints():
    rng = random.Random(306)
    for _ in range(100):
        drivers = [
            driver(
                i,
                rng.choice(['HIGH', 'MEDIUM', 'LOW']),
                tuple(rng.sample(['MORNING', 'AFTERNOON', 'NIGHT'], rng.randint(1, 3))),
            )
            for i in range(1, rng.randint(2, 14))
        ]
        vehicles = [
            vehicle(i, rng.randint(0, 150), rng.randint(0, 150000)) for i in range(1, rng.randint(2, 8))
        ]
        data = input_data(
            drivers=drivers, vehicles=vehicles, tag=rng.randint(1, 1000), road=rng.randint(1, 1000000)
        )
        ConstraintValidator().validate(data, GreedySchedulingStrategy().generate(data))


def test_target_overallocation_rejected_even_below_vehicle_capacity():
    data = input_data(tag=50)
    row = {
        'vehicle_id': 1,
        'driver_id': 1,
        'shift': 'MORNING',
        'task_mode': 'TAG',
        'tags': {'A': 60},
        'roads': {},
    }
    with pytest.raises(BusinessError) as error:
        ConstraintValidator().validate(data, [row])
    assert error.value.code == 'TARGET_EXCEEDED'
