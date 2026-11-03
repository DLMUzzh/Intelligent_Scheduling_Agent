from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')

    app_name: str = 'Driver Scheduling Agent'
    database_url: str = f'sqlite:///{(ROOT / "data" / "scheduling.db").as_posix()}'
    seed_demo: bool = True
    preview_ttl_hours: int = 24
    api_key: str = ''
    host: str = '127.0.0.1'
    port: int = 8000


settings = Settings()
