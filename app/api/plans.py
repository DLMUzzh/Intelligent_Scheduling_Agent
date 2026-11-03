from fastapi import APIRouter, Query, Request

from app.api.dependencies import ok, session_for
from app.schemas import PlanCreate
from app.services.plan_service import CollectionPlanService

router = APIRouter(prefix='/api/plans', tags=['采集计划'])


@router.post('', status_code=201)
def create_plan(payload: PlanCreate, request: Request):
    with session_for(request, write=True) as db:
        return ok(CollectionPlanService(db).create(payload))


@router.get('')
def list_plans(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with session_for(request) as db:
        return ok(CollectionPlanService(db).list(limit, offset))


@router.get('/{plan_id}')
def get_plan(plan_id: int, request: Request):
    with session_for(request) as db:
        return ok(CollectionPlanService(db).detail(plan_id))


@router.get('/{plan_id}/daily-tasks')
def get_tasks(plan_id: int, request: Request):
    with session_for(request) as db:
        return ok(CollectionPlanService(db).daily_tasks(plan_id))
