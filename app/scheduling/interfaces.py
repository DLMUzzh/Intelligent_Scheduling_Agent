from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class DriverResource:
    id: int
    name: str
    efficiency_level: str
    available_shifts: tuple[str, ...]


@dataclass(frozen=True)
class VehicleResource:
    id: int
    name: str
    plate_number: str
    capacities: dict[str, dict[str, int]]


@dataclass
class SchedulingInput:
    target_date: str
    tag_requirements: dict[str, int]
    road_requirements: dict[str, int]  # integer meters
    drivers: list[DriverResource]
    vehicles: list[VehicleResource]
    existing_assignments: list[dict] = field(default_factory=list)
    driver_workloads: dict[int, int] = field(default_factory=dict)
    enabled_shifts: tuple[str, ...] = ('MORNING', 'AFTERNOON', 'NIGHT')


class SchedulingStrategy(Protocol):
    name: str

    def generate(self, data: SchedulingInput) -> list[dict]: ...
