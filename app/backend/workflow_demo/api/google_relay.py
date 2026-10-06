"""The Google relay for deployed n8n workflows (``Authorization: Bearer <deployment key>``)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from workflow_demo.api.deps import Services
from workflow_demo.relay_keys import RELAY_PATH
from workflow_demo.services import google_relay

router = APIRouter(prefix=RELAY_PATH, tags=["google relay"], include_in_schema=False)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
async def relay(path: str, request: Request, svc: Services) -> Response:
    length = request.headers.get("content-length") or "0"
    if not length.isdigit() or int(length) > google_relay.MAX_BODY:
        return _error(413, "Request body too large")
    body = await request.body()

    def forward() -> google_relay.RelayResponse:
        with svc.db.session() as db:
            return google_relay.relay(
                svc,
                db,
                authorization=request.headers.get("authorization"),
                method=request.method,
                path=path,
                query=list(request.query_params.multi_items()),
                body=body,
            )

    try:
        result = await run_in_threadpool(forward)
    except google_relay.RelayError as exc:
        return _error(exc.status_code, exc.message)
    return Response(result.content, status_code=result.status_code, media_type=result.media_type)


def _error(status_code: int, message: str) -> JSONResponse:
    # Google's error shape, so n8n shows the message in the failed node's details.
    return JSONResponse({"error": {"code": status_code, "message": message}}, status_code=status_code)
