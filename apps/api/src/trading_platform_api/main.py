from fastapi import FastAPI

from trading_platform_api.config import AppSettings, load_app_settings
from trading_platform_api.health import create_router as create_health_router

APP_TITLE = "Trading Platform API"
APP_VERSION = "0.1.0"


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)
    app.state.settings = settings if settings is not None else load_app_settings()
    app.include_router(create_health_router())
    return app


app = create_app()
