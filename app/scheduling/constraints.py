from collections import Counter

from app.core.exceptions import BusinessError
from app.scheduling.capacity import capacity_for
from app.scheduling.interfaces import SchedulingInput


class ConstraintValidator:
    def validate(self, data: SchedulingInput, assignments: list[dict]) -> None:
        drivers = {item.id: item for item in data.drivers}
        vehicles = {item.id: item for item in data.vehicles}
        used_drivers: set[int] = set()
        used_slots: set[tuple[int, str]] = set()
        vehicle_modes: dict[int, str] = {}
        for item in data.existing_assignments:
            used_drivers.add(item['driver_id'])
            used_slots.add((item['vehicle_id'], item['shift']))
            vehicle_modes[item['vehicle_id']] = item['task_mode']
        totals = {'TAG': Counter(), 'ROAD': Counter()}
        for item in assignments:
            driver_id, vehicle_id, shift, mode = (
                item[key] for key in ('driver_id', 'vehicle_id', 'shift', 'task_mode')
            )
            prefix = f'{data.target_date} / 司机 D{driver_id:03} / 车辆 V{vehicle_id:03}：'
            if driver_id not in drivers or vehicle_id not in vehicles:
                raise BusinessError('RESOURCE_UNAVAILABLE', prefix + '资源不存在、已停用或当天不可用')
            if shift not in data.enabled_shifts or shift not in drivers[driver_id].available_shifts:
                raise BusinessError('SHIFT_NOT_QUALIFIED', prefix + '班次已停用或司机无对应班次资格')
            if driver_id in used_drivers:
                raise BusinessError('DRIVER_CONFLICT', prefix + '司机当天已有排班，每日最多一个班次')
            if (vehicle_id, shift) in used_slots:
                raise BusinessError('VEHICLE_CONFLICT', prefix + '车辆该班次已被占用')
            if vehicle_id in vehicle_modes and vehicle_modes[vehicle_id] != mode:
                raise BusinessError('VEHICLE_MODE_CONFLICT', prefix + '同一车辆同一天只能执行一种采集模式')
            tags, roads = item.get('tags', {}), item.get('roads', {})
            if (
                mode not in ('TAG', 'ROAD')
                or (mode == 'TAG' and (not tags or roads))
                or (mode == 'ROAD' and (not roads or tags))
            ):
                raise BusinessError('TASK_MODE_INVALID', prefix + '任务内容与模式不匹配')
            values = tags if mode == 'TAG' else roads
            if any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in values.values()
            ):
                raise BusinessError('ALLOCATION_INVALID', prefix + '任务分配量必须为正整数（道路内部使用米）')
            if sum(values.values()) > capacity_for(vehicles[vehicle_id], shift, mode):
                raise BusinessError('CAPACITY_EXCEEDED', prefix + '超过车辆班次容量')
            totals[mode].update(values)
            used_drivers.add(driver_id)
            used_slots.add((vehicle_id, shift))
            vehicle_modes[vehicle_id] = mode
        for mode, targets in [('TAG', data.tag_requirements), ('ROAD', data.road_requirements)]:
            for key, value in totals[mode].items():
                if key not in targets or value > targets[key]:
                    raise BusinessError(
                        'TARGET_EXCEEDED', f'{data.target_date}：{key} 不属于当天需求或累计分配超过目标'
                    )
