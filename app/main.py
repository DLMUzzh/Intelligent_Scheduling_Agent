import json
import logging
import math
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

from app.api.foundation import router
from app.core.config import ROOT
from app.core.exceptions import BusinessError
from app.core.responses import ApiError, error_response, logger
from app.core.runtime import RuntimeSettings, runtime_settings
from app.database.foundation import CommitUncertain, build_engine
from app.database.migrate import initialize_database
from app.services.confirmation_service import ConfirmationService


def configure_logging(config: RuntimeSettings) -> logging.Handler | None:
    config.log_directory.mkdir(parents=True, exist_ok=True)
    destination = (config.log_directory / 'application.log').resolve()
    if any(getattr(handler, 'baseFilename', None) == str(destination) for handler in logger.handlers):
        return None
    handler = RotatingFileHandler(destination, maxBytes=5_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler


def reject_duplicate_keys(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def reject_constant(_value: str):
    raise ValueError('non-finite JSON number')


def parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError('non-finite JSON number')
    return parsed


def create_app(database_engine=None, *, config: RuntimeSettings | None = None, adapters=None) -> FastAPI:
    selected_config = config or runtime_settings
    engine = database_engine or build_engine(selected_config)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        handler = configure_logging(selected_config)
        try:
            initialize_database(engine)
            yield
        finally:
            if handler is not None:
                logger.removeHandler(handler)
                handler.close()
            if database_engine is None:
                engine.dispose()

    application = FastAPI(title=selected_config.app_name, version='1.0.0', lifespan=lifespan)
    application.state.session_factory = factory
    application.state.confirmation_service = ConfirmationService(factory, adapters)
    application.state.runtime_config = selected_config
    application.include_router(router)

    @application.middleware('http')
    async def access_boundary(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            hosts, origins = request.headers.getlist('host'), request.headers.getlist('origin')
            if len(hosts) != 1 or hosts[0] not in selected_config.allowed_hosts:
                raise ApiError('ACCESS_DENIED', '本机访问来源不允许')
            if request.client and request.client.host not in ('127.0.0.1', '::1'):
                raise ApiError('ACCESS_DENIED', '仅允许本机访问')
            if origins and (len(origins) != 1 or origins[0] not in selected_config.allowed_origins):
                raise ApiError('ACCESS_DENIED', '浏览器来源不允许')
            if request.url.path.startswith('/api/'):
                keys = [key for key, _ in request.query_params.multi_items()]
                if len(keys) != len(set(keys)):
                    raise ApiError('VALIDATION_ERROR', '不允许重复查询参数')
                if request.method == 'GET' and await request.body():
                    raise ApiError('VALIDATION_ERROR', 'GET 请求不接受请求体')
                if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                    if not origins:
                        raise ApiError('ACCESS_DENIED', '写请求必须携带允许的 Origin')
                    if (
                        request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                        != 'application/json'
                    ):
                        raise ApiError('UNSUPPORTED_MEDIA_TYPE', '写请求须使用 application/json')
                    try:
                        json.loads(
                            (await request.body()).decode('utf-8'),
                            object_pairs_hook=reject_duplicate_keys,
                            parse_constant=reject_constant,
                            parse_float=parse_finite_float,
                        )
                    except (ValueError, UnicodeDecodeError, RecursionError):
                        raise ApiError('MALFORMED_JSON', 'JSON 语法或键值结构不合法') from None
            response = await call_next(request)
        except Exception as exc:
            response = await error_response(request, exc)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        logger.info(
            'request_id=%s method=%s status=%s operation_id=%s',
            request.state.request_id,
            request.method,
            response.status_code,
            getattr(request.state, 'operation_id', None),
        )
        return response

    for exception_type in (
        BusinessError,
        ApiError,
        RequestValidationError,
        ValidationError,
        IntegrityError,
        OperationalError,
        CommitUncertain,
        HTTPException,
        Exception,
    ):
        application.add_exception_handler(exception_type, error_response)

    dist = ROOT / 'frontend/dist'
    if (dist / 'assets').is_dir():
        application.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @application.get('/', include_in_schema=False)
    def home():
        if not (dist / 'index.html').is_file():
            raise ApiError('STORAGE_UNAVAILABLE', '前端尚未构建，请运行 start.ps1 完成构建')
        return FileResponse(dist / 'index.html')

    return application


app = create_app()
