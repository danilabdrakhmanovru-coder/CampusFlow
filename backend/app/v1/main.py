from contextlib import asynccontextmanager
from os import environ

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .analytics import router as analytics_router
from .auth import router as auth_router, secret
from .privacy import policy_version
from .privacy_routes import router as privacy_router
from .bookings import router as booking_router
from .db import session_factory
from .schedule import router as schedule_router
from .schedule_secret import schedule_secret
from .site import router as site_router
from .workspace import router as workspace_router
from .room_activity import router as activity_router
from .dispatch import router as dispatch_router
from .group_insights import router as group_router
from .profile import router as profile_router
from .proposals import router as proposal_router


@asynccontextmanager
async def lifespan(app):
    secret()
    schedule_secret()
    policy_version()
    if environ.get("CAMPUSFLOW_LOCAL_HTTP") != "1":
        keys = ("CAMPUSFLOW_JWT_SECRET", "CAMPUSFLOW_SCHEDULE_SECRET")
        if "CAMPUSFLOW_DB_PASSWORD" in environ:
            keys += ("CAMPUSFLOW_DB_PASSWORD",)
        for key in keys:
            value = environ.get(key, "")
            if len(value.encode()) < 32 or value.startswith("local-demo-only"):
                raise RuntimeError(f"Set a private, random {key} for HTTPS")
    app.state.sessions = session_factory()
    try:
        yield
    finally:
        app.state.sessions.kw["bind"].dispose()


app = FastAPI(title="CampusFlow", version="1.0", lifespan=lifespan)
from .web_push import router as push_router
app.include_router(push_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api/v1")
app.include_router(group_router, prefix="/api/v1")
app.include_router(dispatch_router, prefix="/api/v1")
app.include_router(privacy_router, prefix="/api/v1")
app.include_router(booking_router, prefix="/api/v1")
app.include_router(schedule_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(site_router, prefix="/api/v1")
app.include_router(activity_router, prefix="/api/v1")
app.include_router(proposal_router, prefix="/api/v1")


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", "request_error")
        message = detail.get("message", "Не удалось выполнить запрос")
        alternatives = detail.get("alternatives", [])
    else:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
                422: "validation", 429: "rate_limit"}.get(exc.status_code, "request_error")
        message, alternatives = str(detail), []
    return JSONResponse({"code": code, "message": message, "alternatives": alternatives, "detail": detail},
                        status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not reflect input values, including submitted passwords.
    return JSONResponse({"code": "validation", "message": "Проверьте поля запроса",
                         "alternatives": [], "detail": "Проверьте поля запроса"}, status_code=422)

