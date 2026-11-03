from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.dependencies import ok, session_for
from app.models import Driver, Notification
from app.repositories.scheduling_repository import require
from app.services.notification_service import notification_view

router = APIRouter(prefix='/api/notifications', tags=['通知'])


@router.get('')
def notifications(
    request: Request,
    status: Literal['PENDING', 'SENT', 'FAILED'] | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with session_for(request) as db:
        query = select(Notification).order_by(Notification.id.desc()).limit(limit).offset(offset)
        if status:
            query = query.where(Notification.status == status)
        drivers = {d.id: d.name for d in db.scalars(select(Driver))}
        return ok([notification_view(n, drivers[n.driver_id]) for n in db.scalars(query)])


@router.get('/{identifier}')
def notification(identifier: int, request: Request):
    with session_for(request) as db:
        row = require(db, Notification, identifier)
        return ok(notification_view(row, require(db, Driver, row.driver_id).name))


@router.post('/{identifier}/retry')
def retry_notification(identifier: int, request: Request):
    return ok(request.app.state.notifications.send(identifier, retry=True))
