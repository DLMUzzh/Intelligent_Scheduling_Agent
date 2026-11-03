from collections import Counter
from statistics import pstdev

from app.scheduling.interfaces import SchedulingInput


def dispersion(values: list[int | float]) -> dict:
    return {
        'population_stddev': round(pstdev(values), 4) if values else 0,
        'minimum': min(values) if values else 0,
        'maximum': max(values) if values else 0,
        'sample_count': len(values),
    }


def evaluate(data: SchedulingInput, assignments: list[dict]) -> dict:
    tags, roads = Counter(), Counter()
    for item in assignments:
        tags.update(item['tags'])
        roads.update(item['roads'])
    remaining_tags = {
        key: value - tags[key] for key, value in data.tag_requirements.items() if value > tags[key]
    }
    remaining_roads = {
        key: value - roads[key] for key, value in data.road_requirements.items() if value > roads[key]
    }
    tag_target, road_target = sum(data.tag_requirements.values()), sum(data.road_requirements.values())
    status = (
        'NO_ASSIGNMENT' if not assignments else ('PARTIAL' if remaining_tags or remaining_roads else 'FULL')
    )
    return {
        'coverage_status': status,
        'tag_target': tag_target,
        'tag_assigned': sum(tags.values()),
        'road_target_meters': road_target,
        'road_assigned_meters': sum(roads.values()),
        'tag_coverage_rate': round(sum(tags.values()) / tag_target * 100, 2) if tag_target else None,
        'road_coverage_rate': round(sum(roads.values()) / road_target * 100, 2) if road_target else None,
        'remaining_tags': remaining_tags,
        'remaining_roads': remaining_roads,
        'reasons': ['可用司机、班次资格、车辆每日模式或班次容量不足；未分配任务仅提醒，不自动结转。']
        if remaining_tags or remaining_roads
        else [],
    }
