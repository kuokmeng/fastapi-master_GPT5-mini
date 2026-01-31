from __future__ import annotations

from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from fastapi.logger import logger
from fastapi.responses import JSONResponse


class ErrorMiddleware:
    """Minimal middleware that converts uncaught exceptions into RFC7807
    Problem Details for HTTP requests while preserving existing framework
    behavior for known exception types.

    Design notes / safety:
    - Only catches `Exception` (not `BaseException`) so system-exit and
      signal events are not swallowed.
    - Re-raises Starlette `HTTPException` and FastAPI `RequestValidationError`
      so existing exception handlers remain in control.
    - For non-HTTP scopes (e.g., websockets), exceptions are re-raised so
      the appropriate websocket handling applies.
    - Responses for unexpected errors do not expose internals; in debug
      mode you may choose to enrich them, but production should avoid
      leaking stack traces or sensitive data.
    - This middleware is intentionally lightweight to avoid adding
      measurable overhead to the request pipeline in the success-path.
    """

    def __init__(self, app: ASGIApp, *, debug: bool = False) -> None:
        self.app = app
        self.debug = debug

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only apply JSON error mapping for HTTP requests. For other scope
        # types (websocket, lifespan), re-raise and let the framework handle.
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:  # pragma: no cover - exercised in tests
            # Avoid swallowing framework exceptions that have their own
            # handling. Re-raise them so registered exception handlers run.
            try:
                from starlette.exceptions import HTTPException as StarletteHTTPException
            except Exception:  # pragma: no cover - defensive
                StarletteHTTPException = None

            try:
                from fastapi.exceptions import RequestValidationError
            except Exception:  # pragma: no cover - defensive
                RequestValidationError = None

            if StarletteHTTPException and isinstance(exc, StarletteHTTPException):
                raise

            if RequestValidationError and isinstance(exc, RequestValidationError):
                raise

            # Log the unexpected exception once. Keep the message concise.
            logger.exception("Unhandled exception in request")

            # Build a minimal RFC7807 problem details response. Do not include
            # exception text or stack traces in the response body.
            problem = {
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Internal Server Error",
            }

            # In debug mode, it's acceptable to include a short hint, but even
            # then avoid full tracebacks in production.
            if self.debug:
                problem["detail"] = str(exc)

            response = JSONResponse(
                content=problem, status_code=500, media_type="application/problem+json"
            )

            await response(scope, receive, send)
