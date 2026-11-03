from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    action: str,
    target_type: str,
    target_id: str | int,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before_data=before,
            after_data=after,
        )
    )
