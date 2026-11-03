import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

from app.api import notifications, plans, resources, schedules
from app.api.dependencies import ok, session_for, verify_api_key
from app.core.config import ROOT, settings
from app.core.exceptions import BusinessError
from app.database.seed import seed_demo, seed_shifts
from app.database.session import Base, engine, transaction
from app.models import AuditLog
from app.services.notification_service import NotificationService

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)


def create_app(database_engine=None, demo: bool | None = None) -> FastAPI:
    selected_engine = database_engine or engine
    factory = sessionmaker(bind=selected_engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        Base.metadata.create_all(selected_engine)
        with transaction(factory, write=True) as db:
            seed_shifts(db)
            if settings.seed_demo if demo is None else demo:
                seed_demo(db)
        application.state.notifications.recover_pending()
        yield

    application = FastAPI(
        title=settings.app_name,
        version='3.0.0',
        lifespan=lifespan,
        description='司机智能排班业务 API。Agent 由用户后续实现。所有业务响应使用 success/data 或 success/error 封装。',
    )
    application.state.session_factory = factory
    application.state.notifications = NotificationService(factory)
    secured = APIRouter(dependencies=[Depends(verify_api_key)])
    for router in (plans.router, resources.router, schedules.router, notifications.router):
        secured.include_router(router)

    @secured.get('/api/capabilities', tags=['系统'])
    def capabilities():
        return ok(
            {
                'version': '3.0.0',
                'agent': {
                    'implemented': False,
                    'directory': 'app/agent',
                    'message': 'Agent 实现目录已预留，待后续开发',
                },
                'algorithms': ['GREEDY_V1'],
                'notification_channel': 'CONSOLE',
                'authentication': 'API_KEY' if settings.api_key else 'LOCAL_DEVELOPMENT',
            }
        )

    @secured.get('/api/audit-logs', tags=['审计'])
    def audit_logs(request: Request):
        with session_for(request) as db:
            return ok(
                [
                    {
                        'id': r.id,
                        'action': r.action,
                        'target_type': r.target_type,
                        'target_id': r.target_id,
                        'operator_id': r.operator_id,
                        'before_data': r.before_data,
                        'after_data': r.after_data,
                        'created_at': r.created_at.isoformat() + 'Z',
                    }
                    for r in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100))
                ]
            )

    application.include_router(secured)
    application.mount('/static', StaticFiles(directory=ROOT / 'app' / 'static'), name='static')
    templates = Jinja2Templates(directory=ROOT / 'app' / 'templates')

    @application.get('/', include_in_schema=False)
    def home(request: Request):
        return templates.TemplateResponse(
            request=request, name='index.html', context={'app_name': settings.app_name}
        )

    @application.get('/health', tags=['系统'])
    def health():
        with transaction(factory) as db:
            db.execute(select(1))
        return ok({'status': 'ok', 'version': '3.0.0'})

    @application.middleware('http')
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.url.path == '/':
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @application.exception_handler(BusinessError)
    async def business_error(_request, exc: BusinessError):
        return JSONResponse(
            status_code=exc.status,
            content={
                'success': False,
                'error': {'code': exc.code, 'message': exc.message, 'details': exc.details},
            },
        )

    async def validation_error(_request, exc):
        errors = [{'field': '.'.join(str(p) for p in e['loc']), 'message': e['msg']} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                'success': False,
                'error': {'code': 'VALIDATION_ERROR', 'message': '输入校验失败', 'details': errors},
            },
        )

    application.add_exception_handler(RequestValidationError, validation_error)
    application.add_exception_handler(ValidationError, validation_error)

    @application.exception_handler(IntegrityError)
    async def integrity_error(_request, _exc):
        return JSONResponse(
            status_code=409,
            content={
                'success': False,
                'error': {'code': 'DATA_CONFLICT', 'message': '数据唯一性或关联约束冲突，请刷新后重试'},
            },
        )

    @application.exception_handler(OperationalError)
    async def database_error(_request, exc):
        logger.exception('数据库操作失败', exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={
                'success': False,
                'error': {'code': 'DATABASE_UNAVAILABLE', 'message': '数据库暂时繁忙，请稍后重试'},
            },
        )

    @application.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                'success': False,
                'error': {'code': f'HTTP_{exc.status_code}', 'message': str(exc.detail)},
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_error(_request, exc):
        logger.exception('未处理的服务异常', exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': {
                    'code': 'INTERNAL_ERROR',
                    'message': '服务内部异常，本次未提交操作已回滚，请查看服务端日志',
                },
            },
        )

    return application


app = create_app()
