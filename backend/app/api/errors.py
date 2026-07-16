"""Consistent API error shape and request-id plumbing (Step 17).

Every non-2xx JSON response carries the same envelope::

    {"code": <str>, "message": <str>, "request_id": <str>, "detail": ...}

``code`` is a stable machine-readable identifier (the taxonomy below),
``message`` is safe human-readable text, and ``request_id`` correlates the
response with the server logs (it is also echoed in the ``X-Request-ID``
header on every response, success or failure). ``detail`` is kept for
backward compatibility with the pre-Step-17 FastAPI shape: the message
string, or the field-error list for validation failures.

Internal errors never leak stack traces, exception text, or file paths —
those go to the log under the request id; the client sees only the generic
message.

Taxonomy:

- ``validation_error`` (422) — malformed request payload or parameters.
- ``governance_rejected`` (400) — prompt rejected by governance policy.
- ``generation_timeout`` (500) — the model run exceeded its time budget.
- ``generation_failed`` (500) — the model run failed for another reason.
- ``busy`` (503) — the generation queue is over its configured backlog.
- ``unavailable`` (503) — a dependency (database, model) is unavailable.
- ``not_found`` (404), ``conflict`` (409), ``method_not_allowed`` (405),
  ``bad_request`` (400) — generic HTTP mappings.
- ``internal_error`` (500) — anything unexpected; details are in the logs.
"""

import logging
import re
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Default codes for plain HTTPExceptions that predate the taxonomy.
_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    503: "unavailable",
}

_INTERNAL_ERROR_MESSAGE = (
    "An internal error occurred. The failure has been logged under this "
    "request id."
)

# Inbound X-Request-ID values are honored for tracing but must stay tame.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ApiError(HTTPException):
    """An HTTPException that names its taxonomy code explicitly."""

    def __init__(
        self,
        status_code: int,
        *,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message


def request_id_of(request: Request) -> str:
    """The id assigned by the middleware (or a fresh one, defensively)."""
    rid = getattr(request.state, "request_id", None)
    return rid if rid else str(uuid.uuid4())


def error_body(
    code: str, message: str, request_id: str, *, detail: Any | None = None
) -> dict[str, Any]:
    """The documented error envelope; ``detail`` defaults to ``message``."""
    return {
        "code": code,
        "message": message,
        "request_id": request_id,
        "detail": message if detail is None else detail,
    }


def install_error_handling(app: FastAPI) -> None:
    """Attach the request-id middleware and the exception handlers."""

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next) -> Response:
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request.state.request_id = (
            supplied if _SAFE_REQUEST_ID.match(supplied) else str(uuid.uuid4())
        )
        response = await call_next(request)
        response.headers.setdefault(REQUEST_ID_HEADER, request.state.request_id)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = (
            exc.code
            if isinstance(exc, ApiError)
            else _STATUS_CODES.get(exc.status_code, "http_error")
        )
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message, request_id_of(request)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Never echo the (possibly huge or sensitive) offending input or
        # internal context back to the client — keep loc/msg/type only.
        errors = jsonable_encoder(
            [
                {
                    key: value
                    for key, value in error.items()
                    if key not in ("input", "ctx", "url")
                }
                for error in exc.errors()
            ]
        )
        message = "; ".join(
            str(entry.get("msg", "invalid value")) for entry in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                message or "Request validation failed.",
                request_id_of(request),
                detail=errors,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        rid = request_id_of(request)
        # Full traceback to the log; only the generic notice to the client.
        logger.error(
            "Unhandled error serving %s %s (request_id=%s)",
            request.method,
            request.url.path,
            rid,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", _INTERNAL_ERROR_MESSAGE, rid),
        )
