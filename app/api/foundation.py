import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import TypeAdapter
from sqlalchemy import func, or_, select

from app.core.responses import ApiError, envelope
from app.core.time import business_date
from app.database.foundation import transaction
from app.models.foundation import AuditLog
from app.schemas.operations import ACTION_TARGETS, ExecuteInput, Id, ObjectVersion, PrepareInput
from app.services.version_service import revision

router = APIRouter(prefix='/api/v1')


def query_fields(request: Request, allowed: set[str]) -> None:
    unknown = set(request.query_params) - allowed
    if unknown:
        raise ApiError(
            'VALIDATION_ERROR',
            '查询参数不受支持',
            [
                {
                    'code': 'VALIDATION_ERROR',
                    'message': '不允许该查询参数',
                    'field': field,
                }
                for field in sorted(unknown)
            ],
        )


def identifier(value: str) -> int:
    result = TypeAdapter(Id).validate_python(value)
    try:
        return int(ObjectVersion.bounded_integer(result))
    except ValueError:
        raise ApiError('VALIDATION_ERROR', '对象编号超出 SQLite 整数范围') from None


def reply(request: Request, result):
    request.state.operation_id = result.data.get('id')
    return envelope(
        request,
        code=result.code,
        message='操作已准备，等待执行' if result.code == 'OPERATION_PREPARED' else '请求处理成功',
        data=result.data,
        revision=result.revision,
        status=result.status,
    )


@router.get('/context')
def context(request: Request):
    query_fields(request, set())
    with transaction(request.app.state.session_factory) as db:
        return envelope(
            request,
            data={
                'actor_code': 'LOCAL_CAPTAIN',
                'actor_name': '车队长',
                'business_date': business_date().isoformat(),
                'timezone': 'Asia/Shanghai',
                'notification_status': 'NOT_CONNECTED',
            },
            revision=revision(db),
        )


@router.post('/operations')
def prepare(request: Request, payload: PrepareInput):
    query_fields(request, set())
    return reply(request, request.app.state.confirmation_service.prepare(payload))


@router.get('/operations')
def find(request: Request):
    query_fields(request, {'request_key'})
    value = request.query_params.get('request_key')
    if value is None:
        raise ApiError('VALIDATION_ERROR', '缺少 request_key')
    try:
        PrepareInput.uuid4_key(value)
    except ValueError:
        raise ApiError('VALIDATION_ERROR', 'request_key 必须为规范小写 UUID v4') from None
    return reply(request, request.app.state.confirmation_service.find(value))


@router.get('/operations/{operation_id}')
def get_operation(request: Request, operation_id: str):
    query_fields(request, set())
    return reply(request, request.app.state.confirmation_service.get(identifier(operation_id)))


@router.post('/operations/{operation_id}/executions')
def execute(request: Request, operation_id: str, payload: ExecuteInput):
    query_fields(request, set())
    return reply(request, request.app.state.confirmation_service.execute(identifier(operation_id), payload))


def audit_view(row: AuditLog, detail: bool = False) -> dict:
    data = {
        column.name: getattr(row, column.name)
        for column in AuditLog.__table__.columns
        if column.name != 'changes_json'
    }
    for name in (
        'id',
        'plan_day_id',
        'formal_version',
        'snapshot_schema_version',
        'business_operation_id',
        'target_id',
    ):
        data[name] = str(data[name]) if data[name] is not None else None
    if detail:
        data['changes_json'] = json.loads(row.changes_json)
    return data


@router.get('/audit-logs/{audit_log_id}')
def audit_detail(request: Request, audit_log_id: str):
    query_fields(request, set())
    with transaction(request.app.state.session_factory) as db:
        row = db.get(AuditLog, identifier(audit_log_id))
        if row is None:
            raise ApiError('NOT_FOUND', '操作记录不存在')
        return envelope(request, data=audit_view(row, detail=True), revision=revision(db))


@router.get('/audit-logs')
def audit_list(request: Request):
    query_fields(
        request,
        {
            'page',
            'page_size',
            'q',
            'entry_source',
            'outcome',
            'action_code',
            'target_type',
            'target_id',
            'business_operation_id',
            'start_date',
            'end_date',
        },
    )
    params = request.query_params
    page, page_size = params.get('page', '1'), params.get('page_size', '20')
    if not page.isascii() or not page.isdecimal() or not page_size.isascii() or not page_size.isdecimal():
        raise ApiError('VALIDATION_ERROR', '分页参数须为整数')
    try:
        page_number, size_number = int(page), int(page_size)
    except ValueError:
        raise ApiError('VALIDATION_ERROR', '分页参数不合法') from None
    if page_number < 1 or not 1 <= size_number <= 100:
        raise ApiError('VALIDATION_ERROR', '分页参数超出范围')
    conditions = []
    for field, values in {
        'entry_source': {'PAGE', 'AGENT'},
        'outcome': {'SUCCEEDED', 'FAILED'},
        'action_code': set(ACTION_TARGETS),
        'target_type': set(ACTION_TARGETS.values()),
    }.items():
        value = params.get(field)
        if value is not None:
            if value not in values:
                raise ApiError('VALIDATION_ERROR', '筛选枚举不合法')
            conditions.append(getattr(AuditLog, field) == value)
    if 'target_id' in params and 'target_type' not in params:
        raise ApiError('VALIDATION_ERROR', 'target_id 须同时提供 target_type')
    for field in ('target_id', 'business_operation_id'):
        if field in params:
            conditions.append(getattr(AuditLog, field) == identifier(params[field]))
    if 'q' in params:
        value = params['q'].strip()
        if len(value) > 100:
            raise ApiError('VALIDATION_ERROR', '搜索词不能超过 100 字符')
        conditions.append(
            or_(
                AuditLog.target_label_snapshot.contains(value, autoescape=True),
                AuditLog.action_code.contains(value, autoescape=True),
                AuditLog.reason.contains(value, autoescape=True),
            )
        )
    if ('start_date' in params) != ('end_date' in params):
        raise ApiError('VALIDATION_ERROR', '日期范围须成对提供')
    if 'start_date' in params:
        try:
            start, end = date.fromisoformat(params['start_date']), date.fromisoformat(params['end_date'])
            if (
                start.isoformat() != params['start_date']
                or end.isoformat() != params['end_date']
                or start > end
            ):
                raise ValueError
            zone = ZoneInfo('Asia/Shanghai')
            first = (
                datetime.min.replace(tzinfo=UTC)
                if start == date.min
                else datetime.combine(start, time.min, zone).astimezone(UTC)
            )
            last = datetime.combine(end, time.max, zone).astimezone(UTC) + timedelta(microseconds=1)
        except (ValueError, OverflowError):
            raise ApiError('VALIDATION_ERROR', '日期范围不合法') from None
        conditions.extend(
            [
                AuditLog.created_at >= first.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                AuditLog.created_at < last.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            ]
        )
    with transaction(request.app.state.session_factory) as db:
        total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
        offset = (page_number - 1) * size_number
        rows = []
        if offset < total:
            rows = db.scalars(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset(offset)
                .limit(size_number)
            ).all()
        return envelope(
            request,
            data={
                'items': [audit_view(row) for row in rows],
                'page': page_number,
                'page_size': size_number,
                'total': str(total),
            },
            revision=revision(db),
        )
