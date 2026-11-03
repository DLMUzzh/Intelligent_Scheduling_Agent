from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CollectionPlan,
    DailyRoadRequirement,
    DailySchedule,
    DailyTagRequirement,
    DailyTask,
    PlanRoadRequirement,
    PlanTagRequirement,
)
from app.repositories.scheduling_repository import SchedulingRepository, require
from app.schemas import PlanCreate, km_to_meters, meters_to_km
from app.services.audit_service import audit


class CollectionPlanService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: PlanCreate) -> dict:
        plan = CollectionPlan(
            title=payload.title, start_date=payload.start_date, end_date=payload.end_date, notes=payload.notes
        )
        self.db.add(plan)
        self.db.flush()
        for item in payload.tag_requirements:
            self.db.add(
                PlanTagRequirement(
                    plan_id=plan.id, tag_type=item.tag_type, daily_target_count=item.daily_count
                )
            )
        for item in payload.road_requirements:
            self.db.add(
                PlanRoadRequirement(
                    plan_id=plan.id, road_type=item.road_type, daily_target_meters=km_to_meters(item.daily_km)
                )
            )
        overrides = {item.date: item for item in payload.daily_overrides}
        current = plan.start_date
        while current <= plan.end_date:
            task = DailyTask(plan_id=plan.id, work_date=current)
            self.db.add(task)
            self.db.flush()
            requirements = overrides.get(current, payload)
            for item in requirements.tag_requirements:
                self.db.add(
                    DailyTagRequirement(
                        daily_task_id=task.id, tag_type=item.tag_type, target_count=item.daily_count
                    )
                )
            for item in requirements.road_requirements:
                self.db.add(
                    DailyRoadRequirement(
                        daily_task_id=task.id,
                        road_type=item.road_type,
                        target_meters=km_to_meters(item.daily_km),
                    )
                )
            current += timedelta(days=1)
        self.db.flush()
        audit(self.db, 'CREATE_PLAN', 'collection_plan', plan.id, after=payload.model_dump(mode='json'))
        return self.detail(plan.id)

    def list(self, limit: int = 100, offset: int = 0) -> list[dict]:
        return [
            self.detail(p.id)
            for p in self.db.scalars(
                select(CollectionPlan).order_by(CollectionPlan.id.desc()).limit(limit).offset(offset)
            )
        ]

    def detail(self, plan_id: int) -> dict:
        plan = require(self.db, CollectionPlan, plan_id)
        tags = self.db.scalars(select(PlanTagRequirement).where(PlanTagRequirement.plan_id == plan_id)).all()
        roads = self.db.scalars(
            select(PlanRoadRequirement).where(PlanRoadRequirement.plan_id == plan_id)
        ).all()
        confirmed = self.db.scalars(select(DailySchedule).where(DailySchedule.plan_id == plan_id)).all()
        days = (plan.end_date - plan.start_date).days + 1
        status = (
            'CONFIRMED' if len(confirmed) == days else ('PARTIALLY_CONFIRMED' if confirmed else 'CREATED')
        )
        return {
            'plan_id': plan.id,
            'title': plan.title,
            'start_date': plan.start_date.isoformat(),
            'end_date': plan.end_date.isoformat(),
            'total_days': days,
            'status': status,
            'version': plan.version,
            'notes': plan.notes,
            'created_at': plan.created_at.isoformat(),
            'confirmed_days': len(confirmed),
            'daily_tag_target': sum(r.daily_target_count for r in tags),
            'daily_road_km': meters_to_km(sum(r.daily_target_meters for r in roads)),
            'tag_requirements': [{'tag_type': r.tag_type, 'daily_count': r.daily_target_count} for r in tags],
            'road_requirements': [
                {'road_type': r.road_type, 'daily_km': meters_to_km(r.daily_target_meters)} for r in roads
            ],
        }

    def daily_tasks(self, plan_id: int) -> list[dict]:
        require(self.db, CollectionPlan, plan_id)
        repo = SchedulingRepository(self.db)
        result = []
        for task in self.db.scalars(
            select(DailyTask).where(DailyTask.plan_id == plan_id).order_by(DailyTask.work_date)
        ):
            tags, roads, _, _ = repo.requirements(plan_id, task.work_date)
            result.append(
                {
                    'date': task.work_date.isoformat(),
                    'tag_requirements': [{'tag_type': key, 'count': value} for key, value in tags.items()],
                    'road_requirements': [
                        {'road_type': key, 'km': meters_to_km(value)} for key, value in roads.items()
                    ],
                }
            )
        return result
