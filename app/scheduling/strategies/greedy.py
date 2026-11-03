from uuid import uuid4

from app.scheduling.capacity import capacity_for, proportional_split
from app.scheduling.interfaces import SchedulingInput

EFFICIENCY_ORDER = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}


class GreedySchedulingStrategy:
    """Coverage first, then proportional utilization; no database or Agent dependency."""

    name = 'GREEDY_V1'

    def generate(self, data: SchedulingInput) -> list[dict]:
        demand = {'TAG': sum(data.tag_requirements.values()), 'ROAD': sum(data.road_requirements.values())}
        selected: list[dict] = []
        selected_capacity = {'TAG': 0, 'ROAD': 0}
        used_drivers = {item['driver_id'] for item in data.existing_assignments}
        used_slots = {(item['vehicle_id'], item['shift']) for item in data.existing_assignments}
        modes = {item['vehicle_id']: item['task_mode'] for item in data.existing_assignments}
        newly_used_vehicles: set[int] = set()

        def driver_key(driver):
            return (
                EFFICIENCY_ORDER[driver.efficiency_level],
                data.driver_workloads.get(driver.id, 0),
                len(driver.available_shifts),
                driver.id,
            )

        def candidates(only_deficit: bool) -> list[tuple]:
            result = []
            for mode in ('TAG', 'ROAD'):
                deficit = max(0, demand[mode] - selected_capacity[mode])
                mode_slots = sum(item['task_mode'] == mode for item in selected)
                if (
                    demand[mode] == 0
                    or (only_deficit and deficit == 0)
                    or (not only_deficit and mode_slots >= demand[mode])
                ):
                    continue
                for vehicle in data.vehicles:
                    if modes.get(vehicle.id, mode) != mode or (
                        not only_deficit and vehicle.id in newly_used_vehicles
                    ):
                        continue
                    for shift_index, shift in enumerate(data.enabled_shifts):
                        capacity = capacity_for(vehicle, shift, mode)
                        if capacity <= 0 or (vehicle.id, shift) in used_slots:
                            continue
                        eligible = [
                            d
                            for d in data.drivers
                            if d.id not in used_drivers and shift in d.available_shifts
                        ]
                        if not eligible:
                            continue
                        driver = min(eligible, key=driver_key)
                        # Compare coverage fractions, never add TAG counts to ROAD meters.
                        gain = min(capacity, deficit) / demand[mode] if deficit else 0
                        # Preserve vehicles uniquely useful to the other task mode when possible.
                        other = 'ROAD' if mode == 'TAG' else 'TAG'
                        opportunity = max(
                            (capacity_for(vehicle, s, other) for s in data.enabled_shifts), default=0
                        )
                        other_capacity = sum(
                            max((capacity_for(v, s, other) for s in data.enabled_shifts), default=0)
                            for v in data.vehicles
                            if modes.get(v.id, other) == other
                        )
                        scarce_cost = (
                            opportunity / max(1, other_capacity)
                            if demand[other] > selected_capacity[other]
                            else 0
                        )
                        score = (
                            -gain,
                            scarce_cost,
                            *driver_key(driver)[:2],
                            vehicle.id in newly_used_vehicles,
                            shift_index,
                            vehicle.id,
                            driver.id,
                        )
                        result.append((score, mode, vehicle, shift, capacity, driver))
            return result

        while True:
            options = candidates(only_deficit=True)
            if not options:
                options = candidates(only_deficit=False)
            if not options:
                break
            _, mode, vehicle, shift, capacity, driver = min(options, key=lambda item: item[0])
            selected.append(
                {
                    'assignment_id': f'A-{uuid4().hex[:12]}',
                    'vehicle_id': vehicle.id,
                    'driver_id': driver.id,
                    'shift': shift,
                    'task_mode': mode,
                    'capacity': capacity,
                    'tags': {},
                    'roads': {},
                }
            )
            selected_capacity[mode] += capacity
            used_slots.add((vehicle.id, shift))
            used_drivers.add(driver.id)
            modes[vehicle.id] = mode
            newly_used_vehicles.add(vehicle.id)

        for mode, targets, field in [
            ('TAG', data.tag_requirements, 'tags'),
            ('ROAD', data.road_requirements, 'roads'),
        ]:
            slots = [item for item in selected if item['task_mode'] == mode]
            amounts = proportional_split(demand[mode], [item['capacity'] for item in slots])
            remaining = dict(targets)
            for slot, amount in zip(slots, amounts, strict=True):
                for key, available_amount in remaining.items():
                    value = min(amount, available_amount)
                    if value:
                        slot[field][key] = value
                        remaining[key] -= value
                        amount -= value
                    if amount == 0:
                        break
        for item in selected:
            item.pop('capacity')
        return [item for item in selected if item['tags'] or item['roads']]
