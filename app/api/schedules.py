from datetime import date

from fastapi import APIRouter, Query, Request

from app.api.dependencies import ok, session_for
from app.core.exceptions import BusinessError
from app.schemas import AssignmentAdd, AssignmentPatch, ConfirmInput, PreviewCreate, VersionInput
from app.services.scheduling_service import SchedulingService

router = APIRouter(prefix='/api/schedules', tags=['排班工作流'])


@router.post('/preview')
def preview(payload: PreviewCreate, request: Request):
    with session_for(request, write=True) as db:
        return ok(SchedulingService(db).generate(payload))


@router.get('/previews')
def list_previews(request: Request, plan_id: int | None = None):
    with session_for(request) as db:
        return ok(SchedulingService(db).list_previews(plan_id))


@router.get('/previews/{identifier}')
def get_preview(identifier: str, request: Request):
    with session_for(request) as db:
        return ok(SchedulingService(db).preview(identifier))


@router.patch('/previews/{identifier}/assignments/{assignment_id}')
def patch_assignment(identifier: str, assignment_id: str, payload: AssignmentPatch, request: Request):
    with session_for(request, write=True) as db:
        return ok(
            SchedulingService(db).edit(identifier, payload.expected_version, 'UPDATE', assignment_id, payload)
        )


@router.post('/previews/{identifier}/assignments')
def add_assignment(identifier: str, payload: AssignmentAdd, request: Request):
    with session_for(request, write=True) as db:
        return ok(SchedulingService(db).edit(identifier, payload.expected_version, 'ADD', payload=payload))


@router.delete('/previews/{identifier}/assignments/{assignment_id}')
def delete_assignment(
    identifier: str, assignment_id: str, request: Request, expected_version: int = Query(..., ge=1)
):
    with session_for(request, write=True) as db:
        return ok(SchedulingService(db).edit(identifier, expected_version, 'DELETE', assignment_id))


@router.post('/previews/{identifier}/discard')
def discard_preview(identifier: str, payload: VersionInput, request: Request):
    with session_for(request, write=True) as db:
        return ok(SchedulingService(db).discard(identifier, payload.expected_version))


@router.post('/confirm')
def confirm(payload: ConfirmInput, request: Request):
    try:
        with session_for(request, write=True) as db:
            result, identifiers = SchedulingService(db).confirm(payload)
    except BusinessError as exc:
        exc.details = {
            'operation_status': 'FAILED',
            'newly_confirmed_dates': [],
            'rolled_back': True,
            'context': exc.details,
        }
        raise
    if identifiers:
        result['notification_status'] = request.app.state.notifications.dispatch(identifiers)
    return ok(result)


@router.get('')
def schedules(
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    plan_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if start_date and end_date and end_date < start_date:
        raise BusinessError('INVALID_DATE_RANGE', '结束日期不能早于开始日期', 422)
    with session_for(request) as db:
        return ok(SchedulingService(db).schedules(start_date, end_date, plan_id, limit, offset))


@router.get('/statistics')
def statistics(
    request: Request, start_date: date | None = None, end_date: date | None = None, plan_id: int | None = None
):
    if start_date and end_date and end_date < start_date:
        raise BusinessError('INVALID_DATE_RANGE', '结束日期不能早于开始日期', 422)
    with session_for(request) as db:
        return ok(SchedulingService(db).statistics(start_date, end_date, plan_id))
