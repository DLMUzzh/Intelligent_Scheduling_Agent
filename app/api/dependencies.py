import secrets

from fastapi import Header, Request

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.database.session import transaction


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and not secrets.compare_digest(x_api_key or '', settings.api_key):
        raise BusinessError('UNAUTHORIZED', '请先配置正确的 API 访问密钥', 401)


def session_for(request: Request, write: bool = False):
    return transaction(request.app.state.session_factory, write=write)


def ok(data):
    return {'success': True, 'data': data}
