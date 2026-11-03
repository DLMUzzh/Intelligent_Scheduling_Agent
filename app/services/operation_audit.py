import json

from sqlalchemy.orm import Session

from app.models.foundation import AuditLog, BusinessOperation


def record_operation(
    db: Session,
    operation: BusinessOperation,
    *,
    outcome: str,
    before: object,
    after: object,
    errors: list[dict] | None = None,
    reason: str | None = None,
    changes: list[dict] | None = None,
) -> None:
    summary = json.loads(operation.summary_json)
    db.add(
        AuditLog(
            business_operation_id=operation.id,
            actor_code='LOCAL_CAPTAIN',
            actor_name_snapshot='车队长',
            entry_source=operation.entry_source,
            action_code=operation.action_code,
            target_type=operation.target_type,
            target_id=operation.target_id,
            target_label_snapshot=summary['title'],
            outcome=outcome,
            reason=reason,
            changes_json=json.dumps(
                {
                    'schema_version': '1',
                    'before': before,
                    'after': after,
                    'changes': (changes if changes is not None else summary['changes'])
                    if outcome == 'SUCCEEDED'
                    else [],
                    'affected_dates': summary['affected_dates'],
                    'errors': errors or [],
                },
                ensure_ascii=False,
                allow_nan=False,
            ),
        )
    )
