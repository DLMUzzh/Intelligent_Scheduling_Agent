from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CollectionPlan, Driver, Shift, Vehicle
from app.schemas import DriverCreate, PlanCreate, VehicleCreate
from app.services.plan_service import CollectionPlanService
from app.services.resource_service import ResourceService


def seed_shifts(db: Session) -> None:
    defaults = [
        ('MORNING', '早班', '06:00', '12:00'),
        ('AFTERNOON', '中班', '12:00', '18:00'),
        ('NIGHT', '晚班', '18:00', '23:59'),
    ]
    for code, name, start, end in defaults:
        if db.scalar(select(Shift).where(Shift.code == code)) is None:
            db.add(Shift(code=code, name=name, start_time=start, end_time=end))
    db.flush()


def seed_demo(db: Session) -> None:
    # Only seed an entirely empty fleet, never replenish deleted/edited user records.
    if any(db.scalar(select(func.count()).select_from(model)) for model in (Driver, Vehicle, CollectionPlan)):
        return
    service = ResourceService(db)
    for index, name in enumerate(
        ['张明', '李航', '陈宇', '王磊', '刘洋', '赵宁', '周晨', '吴昊', '徐帆', '孙悦', '郑远', '林川']
    ):
        service.save_driver(
            DriverCreate(
                name=name,
                phone=f'1380000{index + 1:04}',
                efficiency_level='HIGH' if index < 4 else 'MEDIUM' if index < 9 else 'LOW',
                available_shifts=['MORNING', 'AFTERNOON', 'NIGHT']
                if index != 2
                else ['MORNING', 'AFTERNOON'],
            )
        )
    for index, name in enumerate(['城市采集 01', '城市采集 02', '道路采集 03', '综合采集 04']):
        service.save_vehicle(
            VehicleCreate(
                plate_number=f'沪A·C{index + 1:04}',
                vehicle_name=name,
                capacities=[
                    {
                        'shift': shift,
                        'max_tag_count': [100, 100, 60, 80][index],
                        'max_road_km': str([60, 80, 120, 100][index]),
                    }
                    for shift in ('MORNING', 'AFTERNOON', 'NIGHT')
                ],
            )
        )
    CollectionPlanService(db).create(
        PlanCreate(
            title='11 月道路与场景采集',
            start_date=date(2026, 11, 5),
            end_date=date(2026, 11, 11),
            notes='演示计划：可直接生成预览，调整后确认。',
            tag_requirements=[
                {'tag_type': 'Tag-A', 'daily_count': 100},
                {'tag_type': 'Tag-B', 'daily_count': 50},
            ],
            road_requirements=[
                {'road_type': 'CITY', 'daily_km': '80'},
                {'road_type': 'HIGHWAY', 'daily_km': '120'},
            ],
            daily_overrides=[
                {
                    'date': '2026-11-07',
                    'tag_requirements': [{'tag_type': 'Tag-A', 'daily_count': 160}],
                    'road_requirements': [{'road_type': 'CITY', 'daily_km': '100'}],
                }
            ],
        )
    )
