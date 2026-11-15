from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from leventum.api.deps import CLIENT_HEADER, current_user
from leventum.api.routers import protected, public
from leventum.config import Settings, get_settings
from leventum.db.engine import make_engine, make_session_factory
from leventum.models import Role
from leventum.security.permissions import ROLES

BACKEND_DIR = Path(__file__).resolve().parent.parent
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def run_migrations(settings: Settings) -> None:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.db_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def seed_roles(session_factory) -> None:
    with session_factory() as db:
        have = {r.code for r in db.scalars(select(Role))}
        for code, name in ROLES.items():
            if code not in have:
                db.add(Role(code=code, name=name))
        db.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    run_migrations(settings)
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    seed_roles(factory)

    app = FastAPI(title="Leventum Property Management", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Schreibende API-Aufrufe brauchen einen Custom-Header: Browser senden ihn bei Cross-Site-Formularen
        # nicht, und ohne CORS-Freigabe kann ihn fremder JS-Code nicht setzen.
        if request.url.path.startswith("/api/") and request.method in UNSAFE and request.headers.get(CLIENT_HEADER) != "1":
            return JSONResponse({"detail": {"code": "csrf", "detail": "Ungültige Anfrage."}}, status_code=403)
        return await call_next(request)

    app.include_router(public, prefix="/api/v1")
    app.include_router(protected, prefix="/api/v1", dependencies=[Depends(current_user)])

    dist = settings.frontend_dist or (BACKEND_DIR.parent / "frontend" / "dist")
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (dist / path).resolve()
            if path and dist.resolve() in f.parents and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app
