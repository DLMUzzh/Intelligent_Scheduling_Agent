import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import BusinessError
from app.core.responses import ERROR_STATUS, ApiError, logger, translate_integrity, translate_storage
from app.core.time import business_date, utc_timestamp
from app.database.foundation import CommitUncertain, transaction
from app.models.foundation import BusinessOperation
from app.schemas.operations import (
    ACTION_TARGETS,
    ExecuteInput,
    ExecutionResult,
    ExpectedVersions,
    Id,
    ObjectVersion,
    PrepareInput,
    Summary,
)
from app.services.operation_audit import record_operation
from app.services.version_service import advance_revision, check_versions, revision


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def confirmation_projection(preview: object, actual: object) -> object:
    """Match server-assigned IDs to null preview placeholders while preserving business values."""
    if isinstance(preview, dict) and isinstance(actual, dict):
        result = {}
        for key, value in actual.items():
            if key == 'id' and key in preview and preview[key] is None:
                try:
                    ObjectVersion.bounded_integer(TypeAdapter(Id).validate_python(value))
                except ValueError:
                    raise ApiError('INPUT_CHANGED', '新增对象的实际编号不合法') from None
                result[key] = None
            else:
                result[key] = confirmation_projection(preview.get(key), value)
        return result
    if isinstance(preview, list) and isinstance(actual, list) and len(preview) == len(actual):
        return [
            confirmation_projection(expected, value) for expected, value in zip(preview, actual, strict=True)
        ]
    return actual


@dataclass(frozen=True)
class PreparedAction:
    resolved: dict
    summary: Summary
    expected_versions: ExpectedVersions
    requires_confirmation: bool = True


@dataclass(frozen=True)
class ActionExecution:
    result: ExecutionResult
    after: object


class OperationAdapter(Protocol):
    """Trusted action-specific validation and persistence inside the shared unit of work."""

    def validate_payload(self, payload: dict) -> dict: ...

    def prepare(self, db: Session, request: PrepareInput) -> PreparedAction: ...

    def execute(self, db: Session, resolved: dict) -> ActionExecution: ...


@dataclass(frozen=True)
class OperationReply:
    data: dict
    revision: str
    code: str = 'OK'
    status: int = 200


PUBLIC_FIELDS = (
    'id',
    'request_key',
    'request_hash',
    'action_code',
    'entry_source',
    'target_type',
    'target_id',
    'requires_confirmation',
    'status',
    'confirmed_at',
    'result_code',
    'error_message',
    'finished_at',
    'created_at',
    'updated_at',
)


def operation_view(row: BusinessOperation) -> dict:
    data = {field: getattr(row, field) for field in PUBLIC_FIELDS}
    data['id'] = str(row.id)
    data['target_id'] = str(row.target_id) if row.target_id is not None else None
    for field in ('result_json', 'summary_json', 'expected_versions_json'):
        data[field] = json.loads(getattr(row, field)) if getattr(row, field) is not None else None
    return data


def operation_hash(input_data: dict, prepared: PreparedAction, source: str) -> str:
    value = {
        'input': input_data,
        'resolved': prepared.resolved,
        'summary': prepared.summary.model_dump(),
        'expected_versions': prepared.expected_versions.model_dump(),
        'action_code': input_data['action_code'],
        'target_type': input_data['target_type'],
        'target_id': input_data['target_id'],
        'entry_source': source,
    }
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def check_dates(dates: list[str]) -> None:
    today = business_date()
    errors = []
    for value in dates:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ApiError('DATA_INTEGRITY_ERROR', '操作日期结构不完整')
        if parsed <= today:
            errors.append({'code': 'DATE_LOCKED', 'message': '仅允许修改未来日期', 'work_date': value})
    if errors:
        raise ApiError('DATE_LOCKED', '操作涉及已锁定日期', errors)


class ConfirmationService:
    def __init__(self, factory: sessionmaker, adapters: Mapping[str, OperationAdapter] | None = None):
        self.factory = factory
        self.adapters = dict(adapters or {})

    def get(self, operation_id: int) -> OperationReply:
        with transaction(self.factory) as db:
            row = self._require(db, operation_id)
            return OperationReply(operation_view(row), revision(db))

    def find(self, request_key: str) -> OperationReply:
        with transaction(self.factory) as db:
            row = db.scalar(select(BusinessOperation).where(BusinessOperation.request_key == request_key))
            return OperationReply(
                {
                    'items': [operation_view(row)] if row else [],
                    'page': 1,
                    'page_size': 1,
                    'total': '1' if row else '0',
                },
                revision(db),
            )

    def prepare(self, request: PrepareInput, source: Literal['PAGE', 'AGENT'] = 'PAGE') -> OperationReply:
        self._check_action(request)
        adapter = self.adapters.get(request.action_code)
        if adapter is None:
            raise ApiError(
                'VALIDATION_ERROR',
                '该业务动作尚未接入，请等待对应业务模块实现',
                [
                    {
                        'code': 'VALIDATION_ERROR',
                        'message': '业务动作尚未接入',
                        'field': 'action_code',
                    }
                ],
            )
        payload = adapter.validate_payload(request.payload)
        normalized = request.model_copy(update={'payload': payload})
        input_data = normalized.model_dump()
        try:
            with transaction(self.factory, write=True) as db:
                row = db.scalar(
                    select(BusinessOperation).where(BusinessOperation.request_key == request.request_key)
                )
                if row is not None:
                    return self._prepared_replay(db, row, input_data, source)
                check_versions(db, request.expected_versions_json)
                prepared = self._read_prepared(db, adapter, normalized)
                self._check_prepared(request, prepared)
                check_versions(db, prepared.expected_versions)
                row = BusinessOperation(
                    request_key=request.request_key,
                    request_hash=operation_hash(input_data, prepared, source),
                    action_code=request.action_code,
                    target_type=request.target_type,
                    target_id=int(request.target_id) if request.target_id else None,
                    entry_source=source,
                    actor_code='LOCAL_CAPTAIN',
                    status='PENDING',
                    request_payload_json=canonical({'input': input_data, 'resolved': prepared.resolved}),
                    expected_versions_json=canonical(prepared.expected_versions.model_dump()),
                    summary_json=canonical(prepared.summary.model_dump()),
                    requires_confirmation=int(prepared.requires_confirmation),
                )
                db.add(row)
                db.flush()
                result = OperationReply(operation_view(row), revision(db), 'OPERATION_PREPARED', 201)
            return result
        except CommitUncertain:
            # A visible committed preparation is safe to return by its original key.
            with transaction(self.factory) as db:
                row = db.scalar(
                    select(BusinessOperation).where(BusinessOperation.request_key == request.request_key)
                )
                if row is not None:
                    return self._prepared_replay(db, row, input_data, source)
            raise ApiError('STORAGE_UNAVAILABLE', '准备结果待核实，请使用原幂等键查询') from None

    def execute(self, operation_id: int, request: ExecuteInput) -> OperationReply:
        with transaction(self.factory) as db:
            self._check_confirmation(self._require(db, operation_id), request)
        try:
            with transaction(self.factory, write=True) as db:
                row = self._require(db, operation_id)
                self._check_confirmation(row, request)
                if row.status != 'PENDING':
                    return self._terminal(db, row)
                expected = ExpectedVersions.model_validate(json.loads(row.expected_versions_json))
                check_versions(db, expected)
                adapter = self.adapters.get(row.action_code)
                if adapter is None:
                    raise ApiError('VALIDATION_ERROR', '该业务动作尚未接入')
                stored = json.loads(row.request_payload_json)
                original = PrepareInput.model_validate(stored['input'])
                frozen = PreparedAction(
                    resolved=stored['resolved'],
                    summary=Summary.model_validate(json.loads(row.summary_json)),
                    expected_versions=expected,
                    requires_confirmation=bool(row.requires_confirmation),
                )
                if operation_hash(stored['input'], frozen, row.entry_source) != row.request_hash:
                    raise ApiError('INPUT_CHANGED', '冻结的操作内容已变化，请重新准备操作')
                prepared = self._read_prepared(db, adapter, original)
                self._check_prepared(original, prepared)
                if prepared.requires_confirmation != bool(row.requires_confirmation):
                    raise ApiError('INPUT_CHANGED', '确认要求已变化，请重新准备操作')
                if operation_hash(stored['input'], prepared, row.entry_source) != row.request_hash:
                    raise ApiError('INPUT_CHANGED', '拟执行内容或依据已变化，请重新准备操作')
                summary = prepared.summary
                check_dates(summary.affected_dates)
                execution = adapter.execute(db, stored['resolved'])
                if canonical(confirmation_projection(summary.after, execution.after)) != canonical(
                    summary.after
                ):
                    raise ApiError('INPUT_CHANGED', '执行内容与已确认摘要不一致')
                result = execution.result.model_dump()
                if (
                    result['target_type'] != row.target_type
                    or result['affected_dates'] != summary.affected_dates
                    or result['preserved_dates'] != summary.preserved_dates
                    or (row.target_id is not None and result['target_id'] != str(row.target_id))
                ):
                    raise ApiError('DATA_INTEGRITY_ERROR', '执行结果与操作范围不一致')
                if row.target_id is None and result['target_id'] is not None:
                    row.target_id = int(result['target_id'])
                current_revision = revision(db)
                if result['code'] not in ('ALREADY_CONFIRMED', 'NO_PENDING_DATES'):
                    current_revision = advance_revision(db, expected.business_revision)
                self._finish(row, 'SUCCEEDED', result, confirmed=request.confirmed)
                record_operation(db, row, outcome='SUCCEEDED', before=summary.before, after=execution.after)
                db.flush()
                check_dates(result['affected_dates'])
                reply = OperationReply(
                    operation_view(row),
                    current_revision,
                    'ALREADY_CONFIRMED' if result['code'] == 'ALREADY_CONFIRMED' else 'EXECUTED',
                )
            return reply
        except CommitUncertain:
            return self._recover_commit(operation_id)
        except OperationalError as exc:
            raise translate_storage(exc) from None
        except IntegrityError as exc:
            return self._record_failure(operation_id, translate_integrity(exc), request.confirmed)
        except BusinessError as exc:
            error = (
                exc
                if isinstance(exc, ApiError)
                else ApiError(
                    exc.code if exc.code in ERROR_STATUS else 'INTERNAL_ERROR',
                    exc.message if exc.code in ERROR_STATUS else '操作执行失败，业务事务已回滚',
                )
            )
            return self._record_failure(operation_id, error, request.confirmed)
        except Exception as exc:
            logger.error(
                'operation_id=%s exception_type=%s business_transaction=rolled_back',
                operation_id,
                type(exc).__name__,
            )
            return self._record_failure(
                operation_id, ApiError('INTERNAL_ERROR', '操作执行失败，业务事务已回滚'), request.confirmed
            )

    def _recover_commit(self, operation_id: int) -> OperationReply:
        try:
            with transaction(self.factory) as db:
                row = self._require(db, operation_id)
                if row.status != 'PENDING':
                    return self._terminal(db, row)
        except ApiError:
            raise
        except Exception:
            pass
        raise ApiError('STORAGE_UNAVAILABLE', '提交结果待核实，请查询原操作状态')

    def _record_failure(self, operation_id: int, error: ApiError, confirmed: bool) -> OperationReply:
        try:
            with transaction(self.factory, write=True) as db:
                row = self._require(db, operation_id)
                if row.status != 'PENDING':
                    return self._terminal(db, row)
                summary = json.loads(row.summary_json)
                before = summary['before']
                expected_revision = json.loads(row.expected_versions_json)['business_revision']
                if revision(db) != expected_revision:
                    before = None
                    adapter = self.adapters.get(row.action_code)
                    if adapter is not None:
                        try:
                            original = PrepareInput.model_validate(
                                json.loads(row.request_payload_json)['input']
                            )
                            before = self._read_prepared(db, adapter, original).summary.before
                        except Exception:
                            logger.info('operation_id=%s current_failure_snapshot=unavailable', row.id)
                result = ExecutionResult(
                    code=error.code,
                    target_type=row.target_type,
                    target_id=str(row.target_id) if row.target_id else None,
                    errors=error.errors,
                ).model_dump()
                self._finish(row, 'FAILED', result, confirmed=confirmed, message=error.message)
                record_operation(
                    db,
                    row,
                    outcome='FAILED',
                    before=before,
                    after=before,
                    errors=error.errors,
                    reason=error.message,
                )
                db.flush()
                error.data = operation_view(row)
                error.revision = revision(db)
        except CommitUncertain:
            return self._recover_commit(operation_id)
        except ApiError:
            raise
        except Exception as exc:
            logger.error(
                'operation_id=%s failure_record=unavailable exception_type=%s',
                operation_id,
                type(exc).__name__,
            )
        raise error

    @staticmethod
    def _prepared_replay(
        db: Session, row: BusinessOperation, input_data: dict, source: str
    ) -> OperationReply:
        if json.loads(row.request_payload_json)['input'] != input_data or row.entry_source != source:
            raise ApiError('IDEMPOTENCY_KEY_REUSED', '同一幂等键已绑定其他请求内容')
        return OperationReply(operation_view(row), revision(db), 'OPERATION_REPLAY')

    @staticmethod
    def _require(db: Session, operation_id: int) -> BusinessOperation:
        row = db.get(BusinessOperation, operation_id)
        if row is None:
            raise ApiError('NOT_FOUND', '操作记录不存在')
        return row

    @staticmethod
    def _check_action(request: PrepareInput) -> None:
        if ACTION_TARGETS.get(request.action_code) != request.target_type:
            raise ApiError('VALIDATION_ERROR', '操作类型与目标类型不匹配')
        if request.action_code.startswith('CREATE_') != (request.target_id is None):
            raise ApiError('VALIDATION_ERROR', '创建须空目标，已有对象操作须明确目标编号')
        if request.target_id is None:
            return
        table = {
            'CATEGORY': 'collection_categories',
            'PLAN': 'collection_plans',
            'DRIVER': 'drivers',
            'VEHICLE': 'vehicles',
            'UNAVAILABILITY': 'resource_unavailability',
            'PLAN_DAY': 'plan_days',
            'DRAFT': 'plan_days',
            'FORMAL_DAY': 'plan_days',
        }[request.target_type]
        if request.target_id not in {item.id for item in getattr(request.expected_versions_json, table)}:
            raise ApiError('VALIDATION_ERROR', '缺少直接操作对象的版本依据')

    @staticmethod
    def _read_prepared(db: Session, adapter: OperationAdapter, request: PrepareInput) -> PreparedAction:
        connection = db.connection()
        connection.exec_driver_sql('PRAGMA query_only=ON')
        try:
            prepared = adapter.prepare(db, request)
            if db.new or db.dirty or db.deleted:
                raise ApiError('DATA_INTEGRITY_ERROR', '准备阶段不得修改业务数据')
            return prepared
        finally:
            connection.exec_driver_sql('PRAGMA query_only=OFF')

    @staticmethod
    def _check_prepared(request: PrepareInput, prepared: PreparedAction) -> None:
        summary = prepared.summary
        if (
            not prepared.requires_confirmation and request.action_code not in ('GENERATE_DRAFT', 'SAVE_DRAFT')
        ) or (request.action_code == 'SAVE_DRAFT' and prepared.requires_confirmation):
            raise ApiError('DATA_INTEGRITY_ERROR', '业务动作的确认要求不符合接口契约')
        if (summary.action_code, summary.target_type, summary.target_id) != (
            request.action_code,
            request.target_type,
            request.target_id,
        ):
            raise ApiError('DATA_INTEGRITY_ERROR', '操作摘要与请求对象不一致')
        expected = request.expected_versions_json.model_dump()
        enriched = prepared.expected_versions.model_dump()
        if expected['business_revision'] != enriched['business_revision']:
            raise ApiError('DATA_INTEGRITY_ERROR', '不能替换原始版本依据')
        for name, items in expected.items():
            if isinstance(items, list) and any(item not in enriched[name] for item in items):
                raise ApiError('DATA_INTEGRITY_ERROR', '不能覆盖原始对象版本依据')

    @staticmethod
    def _check_confirmation(row: BusinessOperation, request: ExecuteInput) -> None:
        if row.request_hash != request.request_hash:
            raise ApiError('CONFIRMATION_MISMATCH', '确认摘要不匹配')
        if row.requires_confirmation and not request.confirmed:
            raise ApiError('CONFIRMATION_REQUIRED', '请明确确认当前操作摘要')
        if not row.requires_confirmation and request.confirmed:
            raise ApiError('CONFIRMATION_MISMATCH', '该操作应按无需人工确认的流程执行')

    @staticmethod
    def _finish(
        row: BusinessOperation, status: str, result: dict, *, confirmed: bool, message: str | None = None
    ) -> None:
        timestamp = utc_timestamp()
        row.status, row.result_code = status, result['code']
        row.result_json = canonical(result)
        row.error_message = message
        row.confirmed_at = timestamp if confirmed else None
        row.finished_at = row.updated_at = timestamp

    @staticmethod
    def _terminal(db: Session, row: BusinessOperation) -> OperationReply:
        view, current = operation_view(row), revision(db)
        if row.status == 'FAILED':
            raise ApiError(
                row.result_code, row.error_message, json.loads(row.result_json)['errors'], view, current
            )
        code = 'ALREADY_CONFIRMED' if row.result_code == 'ALREADY_CONFIRMED' else 'EXECUTED'
        return OperationReply(view, current, code)
