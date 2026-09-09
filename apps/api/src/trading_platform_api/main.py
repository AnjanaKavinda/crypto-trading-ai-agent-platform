from fastapi import FastAPI

APP_TITLE = "Trading Platform API"
APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    return FastAPI(title=APP_TITLE, version=APP_VERSION)


app = create_app()
