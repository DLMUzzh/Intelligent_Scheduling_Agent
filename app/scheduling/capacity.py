def capacity_for(vehicle, shift: str, mode: str) -> int:
    return vehicle.capacities.get(shift, {}).get(mode, 0)


def proportional_split(total: int, capacities: list[int]) -> list[int]:
    """Integer largest-remainder allocation; never exceeds an individual capacity."""
    if not capacities or sum(capacities) == 0:
        return [0] * len(capacities)
    total = min(total, sum(capacities))
    denominator = sum(capacities)
    amounts = [total * capacity // denominator for capacity in capacities]
    order = sorted(range(len(capacities)), key=lambda i: (-(total * capacities[i] % denominator), i))
    for index in order[: total - sum(amounts)]:
        amounts[index] += 1
    return amounts
