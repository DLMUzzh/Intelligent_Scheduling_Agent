from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ROOT


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', env_prefix='FLEET_', extra='ignore')

    app_name: str = 'Fleetwise · 司机智能排班'
    database_url: str = f'sqlite:///{(ROOT / "data/active/scheduling.db").as_posix()}'
    host: Literal['127.0.0.1'] = '127.0.0.1'
    port: int = Field(default=8000, ge=1, le=65535)
    frontend_port: int = Field(default=5173, ge=1, le=65535)
    busy_timeout_ms: int = Field(default=5000, ge=1, le=60000)
    log_directory: Path = ROOT / 'logs'

    @property
    def allowed_hosts(self) -> set[str]:
        return {
            f'{host}:{port}'
            for host in ('127.0.0.1', 'localhost')
            for port in (self.port, self.frontend_port)
        }

    @property
    def allowed_origins(self) -> set[str]:
        return {f'http://{host}' for host in self.allowed_hosts}


runtime_settings = RuntimeSettings()
