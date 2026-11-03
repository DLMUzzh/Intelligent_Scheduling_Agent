import logging
import traceback

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from app.core.exceptions import BusinessError
from app.database.foundation import CommitUncertain, transaction
from app.models.foundation import BusinessState
from app.schemas.operations import ErrorItem

logger = logging.getLogger('fleetwise')

ERROR_STATUS = {
    'MALFORMED_JSON': 400,
    'ACCESS_DENIED': 403,
    'NOT_FOUND': 404,
    'REFERENCED_OBJECT_NOT_FOUND': 404,
    'METHOD_NOT_ALLOWED': 405,
    'UNSUPPORTED_MEDIA_TYPE': 415,
    **dict.fromkeys(
        (
            'IDEMPOTENCY_KEY_REUSED',
            'CONFIRMATION_MISMATCH',
            'CONFIRMATION_REQUIRED',
            'VERSION_CONFLICT',
            'INPUT_CHANGED',
            'DATE_LOCKED',
            'DATE_OVERLAP',
            'PLAN_HAS_HISTORY',
            'PLAN_EDIT_NOT_ALLOWED',
            'FORMAL_CHANGE_REQUIRED',
            'FORMAL_NOT_ACTIVE',
            'DRAFT_NOT_FOUND',
            'EMPTY_SCHEDULE',
            'MANUAL_DRAFT_OVERWRITE_REQUIRED',
            'RESOURCE_REFERENCED',
            'DUPLICATE_CATEGORY',
            'DUPLICATE_PLATE',
            'DRIVER_CONFLICT',
            'VEHICLE_SHIFT_CONFLICT',
            'VEHICLE_MODE_CONFLICT',
            'RESOURCE_UNAVAILABLE',
            'SHIFT_NOT_QUALIFIED',
            'CAPACITY_EXCEEDED',
            'DEMAND_EXCEEDED',
            'FUTURE_SCHEDULE_INVALID',
            'CONFIRM_PLAN_FAILED',
        ),
        409,
    ),
    **dict.fromkeys(
        (
            'VALIDATION_ERROR',
            'INVALID_QUANTITY',
            'INVALID_PLAN_DAYS',
            'CATEGORY_MODE_MISMATCH',
            'UNSUPPORTED_BATCH',
            'CONFIRMATION_SCOPE_INVALID',
        ),
        422,
    ),
    'INTERNAL_ERROR': 500,
    'DATA_INTEGRITY_ERROR': 500,
    'AGENT_UPSTREAM_ERROR': 502,
    'WRITE_BUSY': 503,
    'STORAGE_UNAVAILABLE': 503,
    'AGENT_UNAVAILABLE': 503,
    'AGENT_TIMEOUT': 504,
}


class ApiError(BusinessError):
    def __init__(
        self,
        code: str,
        message: str,
        errors: list[dict] | None = None,
        data: dict | None = None,
        revision: str | None = None,
    ):
        super().__init__(code, message, ERROR_STATUS[code])
        self.errors = [ErrorItem.model_validate(item).model_dump() for item in errors or []]
        self.data = data
        self.revision = revision


def envelope(
    request: Request,
    *,
    code: str = 'OK',
    message: str = '查询成功',
    data: dict | None = None,
    revision: str | None = None,
    status: int = 200,
    errors: list[dict] | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            'success': 200 <= status < 300,
            'code': code,
            'message': message,
            'data': data,
            'errors': errors or [],
            'request_id': request.state.request_id,
            'data_revision': revision,
        },
    )


def safe_revision(request: Request) -> str | None:
    try:
        with transaction(request.app.state.session_factory) as db:
            value = db.scalar(select(BusinessState.revision).where(BusinessState.state_key == 'MAIN'))
            return str(value) if value is not None else None
    except Exception:
        return None


def log_failure(request_id: str, exc: Exception) -> None:
    frames = traceback.extract_tb(exc.__traceback__)
    locations = ' '.join(f'{frame.filename}:{frame.lineno}:{frame.name}' for frame in frames)
    logger.error('request_id=%s exception_type=%s locations=%s', request_id, type(exc).__name__, locations)


def translate_integrity(exc: IntegrityError) -> ApiError:
    detail = str(exc.orig)
    codes = {
        'collection_categories.task_mode, collection_categories.name': 'DUPLICATE_CATEGORY',
        'vehicles.plate_key': 'DUPLICATE_PLATE',
        'plan_days.work_date': 'DATE_OVERLAP',
        'task_packages.schedule_kind, task_packages.work_date, task_packages.driver_id': 'DRIVER_CONFLICT',
        'task_packages.schedule_kind, task_packages.work_date, task_packages.vehicle_id, task_packages.shift_code': 'VEHICLE_SHIFT_CONFLICT',
    }
    constraint = detail.removeprefix('UNIQUE constraint failed: ')
    code = codes.get(constraint, 'DATA_INTEGRITY_ERROR')
    return ApiError(code, '数据约束校验失败，请刷新并核对操作内容')


def translate_storage(exc: OperationalError) -> ApiError:
    code = 'WRITE_BUSY' if getattr(exc.orig, 'sqlite_errorcode', None) in (5, 6) else 'STORAGE_UNAVAILABLE'
    return ApiError(code, '存储暂不可用，请使用原操作编号核实结果')


async def error_response(request: Request, exc: Exception) -> JSONResponse:
    headers = None
    if isinstance(exc, ApiError):
        error = exc
    elif isinstance(exc, BusinessError) and exc.code in ERROR_STATUS:
        error = ApiError(exc.code, exc.message)
    elif isinstance(exc, (RequestValidationError, ValidationError)):
        items = [
            {
                'code': 'VALIDATION_ERROR',
                'message': '字段格式或类型不符合接口要求',
                'field': '.'.join(map(str, item['loc'])),
            }
            for item in exc.errors()
        ]
        error = ApiError('VALIDATION_ERROR', '输入校验失败', items)
    elif isinstance(exc, IntegrityError):
        error = translate_integrity(exc)
    elif isinstance(exc, OperationalError):
        error = translate_storage(exc)
    elif isinstance(exc, CommitUncertain):
        error = ApiError('STORAGE_UNAVAILABLE', '提交结果待核实，请查询原操作状态')
    elif isinstance(exc, HTTPException):
        code = {404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED'}.get(exc.status_code, 'INTERNAL_ERROR')
        error = ApiError(
            code,
            {'NOT_FOUND': '请求的资源不存在', 'METHOD_NOT_ALLOWED': '请求方法不允许'}.get(
                code, '服务处理失败'
            ),
        )
        headers = exc.headers
    else:
        error = ApiError('INTERNAL_ERROR', '服务处理失败，请通过请求标识核查日志与操作状态')
    if error.status >= 500:
        log_failure(request.state.request_id, exc)
    if error.data:
        request.state.operation_id = error.data.get('id')
    return envelope(
        request,
        code=error.code,
        message=error.message,
        data=error.data,
        revision=error.revision or safe_revision(request),
        status=error.status,
        errors=error.errors,
        headers=headers,
    )
