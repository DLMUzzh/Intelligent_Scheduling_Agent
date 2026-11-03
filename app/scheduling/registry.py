from app.core.exceptions import BusinessError
from app.scheduling.interfaces import SchedulingStrategy
from app.scheduling.strategies.greedy import GreedySchedulingStrategy

STRATEGIES: dict[str, SchedulingStrategy] = {'GREEDY_V1': GreedySchedulingStrategy()}


def get_strategy(name: str) -> SchedulingStrategy:
    if name not in STRATEGIES:
        raise BusinessError('ALGORITHM_NOT_FOUND', '未注册该排班算法', 422)
    return STRATEGIES[name]
