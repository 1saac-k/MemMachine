"""FastAPI gateway application factory and entry point (DESIGN.md §2, §8)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ExceptionHandler

from memmachine_account.server import (
    routes_auth,
    routes_orgs,
    routes_proxy,
    routes_tokens,
)
from memmachine_account.server.config import AppConfig, load_config
from memmachine_account.server.errors import AccountError
from memmachine_account.server.storage import (
    create_engine,
    create_session_factory,
    init_models,
)


def create_app(config: AppConfig) -> FastAPI:
    """Build the FastAPI app: DB lifecycle, exception handling, and routers."""
    engine = create_engine(config.storage.sqlite_path)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await init_models(engine)
        yield
        await engine.dispose()

    app = FastAPI(
        title="MemMachine Account",
        description="Member management gateway for on-premise MemMachine deployments",
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.session_factory = session_factory
    app.state.engine = engine

    app.add_exception_handler(AccountError, cast(ExceptionHandler, _account_error_handler))
    app.include_router(routes_auth.router, prefix="/account/v1")
    app.include_router(routes_tokens.router, prefix="/account/v1")
    app.include_router(routes_orgs.router, prefix="/account/v1")
    app.include_router(routes_proxy.router)

    return app


async def _account_error_handler(_: Request, exc: AccountError) -> JSONResponse:
    """Render an AccountError as MemMachine's RestError envelope (DESIGN.md §8.1)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.to_detail()})


def main() -> None:
    """CLI entry point for `memmachine-account-server`."""
    config = load_config()
    app = create_app(config)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        log_level=config.logging.level,
    )
