import logging

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database.session import transaction
from app.models import Driver, Notification, utcnow
from app.notifications.console_sender import ConsoleSender
from app.notifications.interfaces import NotificationSender
from app.repositories.scheduling_repository import require
from app.services.audit_service import audit

logger = logging.getLogger(__name__)


def notification_view(row: Notification, driver_name: str = '') -> dict:
    return {
        'id': row.id,
        'assignment_id': row.assignment_id,
        'driver_id': row.driver_id,
        'driver_name': driver_name,
        'notification_type': row.notification_type,
        'schedule_version': row.schedule_version,
        'content': row.content,
        'status': row.status,
        'idempotency_key': row.idempotency_key,
        'retry_count': row.retry_count,
        'error_message': row.error_message,
        'sent_at': row.sent_at.isoformat() + 'Z' if row.sent_at else None,
        'created_at': row.created_at.isoformat() + 'Z',
    }


class NotificationService:
    def __init__(self, factory: sessionmaker, sender: NotificationSender | None = None):
        self.factory = factory
        self.sender = sender or ConsoleSender()

    def send(self, identifier: int, retry: bool = False) -> dict:
        # Console transport is quick; serialize check/send/update to avoid concurrent duplicate logs.
        # Future remote channels must consume idempotency_key on the provider side as well.
        with transaction(self.factory, write=True) as db:
            row = require(db, Notification, identifier)
            if row.status == 'SENT':
                return notification_view(row, require(db, Driver, row.driver_id).name)
            if retry:
                row.retry_count += 1
            try:
                self.sender.send(row.content, row.idempotency_key)
                row.status, row.sent_at, row.error_message = 'SENT', utcnow(), None
            except Exception as exc:
                logger.exception('通知发送失败: %s', identifier)
                row.status, row.error_message = 'FAILED', str(exc)[:1000]
            audit(
                db,
                'RETRY_NOTIFICATION' if retry else 'SEND_NOTIFICATION',
                'notification',
                row.id,
                after={'status': row.status, 'retry_count': row.retry_count},
            )
            return notification_view(row, require(db, Driver, row.driver_id).name)

    def dispatch(self, identifiers: list[int]) -> str:
        statuses = []
        for identifier in identifiers:
            try:
                statuses.append(self.send(identifier)['status'])
            except Exception:
                # The durable PENDING row survives a database/worker failure and is retried at startup.
                logger.exception('通知派发中断: %s', identifier)
                statuses.append('PENDING')
        return 'FAILED' if 'FAILED' in statuses else ('PENDING' if 'PENDING' in statuses else 'SENT')

    def recover_pending(self) -> None:
        with transaction(self.factory) as db:
            identifiers = list(db.scalars(select(Notification.id).where(Notification.status == 'PENDING')))
        self.dispatch(identifiers)
