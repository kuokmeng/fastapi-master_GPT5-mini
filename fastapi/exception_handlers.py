from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, WebSocketRequestValidationError
from fastapi.utils import is_body_allowed_for_status_code, build_from_pydantic_error
from fastapi.websockets import WebSocket
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import WS_1008_POLICY_VIOLATION


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    headers = getattr(exc, "headers", None)
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=headers
    )


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


async def websocket_request_validation_exception_handler(
    websocket: WebSocket, exc: WebSocketRequestValidationError
) -> None:
    await websocket.close(
        code=WS_1008_POLICY_VIOLATION, reason=jsonable_encoder(exc.errors())
    )


def configure_problem_details(
    app,
    *,
    legacy_mode: bool = True,
    override_http_exceptions: bool = False,
    type_base: str = "https://example.com/problems",
    debug: bool = False,
):
    """Configure RFC7807 Problem Details handlers on a FastAPI `app`.

    Minimal, opt-in utility to register validation and (optionally) HTTP
    exception handlers that emit RFC7807 Problem Details while preserving
    legacy payload shapes when `legacy_mode` is True.
    """

    def _build_validation_problem(exc: RequestValidationError) -> dict:
        raw_errors = exc.errors()
        normalized = []
        for err in raw_errors:
            loc = err.get("loc", [])
            pointer = build_from_pydantic_error(loc)
            normalized.append(
                {
                    "loc": loc,
                    "msg": err.get("msg"),
                    "type": err.get("type"),
                    "ctx": err.get("ctx"),
                    "pointer": pointer,
                }
            )

        if legacy_mode:
            problem = {
                "type": f"{type_base}/validation",
                "title": "Request validation error",
                "status": 422,
                "detail": jsonable_encoder(raw_errors),
                "errors": jsonable_encoder(normalized),
            }
        else:
            problem = {
                "type": f"{type_base}/validation",
                "title": "Request validation error",
                "status": 422,
                "detail": "Request validation failed; see `errors` for details.",
                "errors": jsonable_encoder(normalized),
            }

        if debug:
            problem["debug_hint"] = str(exc)

        return problem

    async def _request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problem = _build_validation_problem(exc)
        return JSONResponse(
            status_code=422, content=problem, media_type="application/problem+json"
        )

    app.add_exception_handler(RequestValidationError, _request_validation_handler)

    if override_http_exceptions:

        async def _http_exc_handler(request: Request, exc: HTTPException) -> Response:
            headers = getattr(exc, "headers", None)
            if not is_body_allowed_for_status_code(exc.status_code):
                return Response(status_code=exc.status_code, headers=headers)

            if isinstance(exc.detail, dict) and "type" in exc.detail:
                return JSONResponse(
                    content=exc.detail,
                    status_code=exc.status_code,
                    headers=headers,
                    media_type="application/problem+json",
                )

            if legacy_mode and isinstance(exc.detail, list):
                content = {
                    "type": f"{type_base}/http-error",
                    "title": exc.status_code,
                    "status": exc.status_code,
                    "detail": jsonable_encoder(exc.detail),
                }
            else:
                content = {
                    "type": f"{type_base}/http-error",
                    "title": str(exc.detail) if exc.detail else "HTTP Error",
                    "status": exc.status_code,
                    "detail": str(exc.detail) if exc.detail else None,
                }

            return JSONResponse(
                content=content,
                status_code=exc.status_code,
                headers=headers,
                media_type="application/problem+json",
            )

        app.add_exception_handler(HTTPException, _http_exc_handler)
