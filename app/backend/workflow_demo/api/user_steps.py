"""Return path from a platform popup (Make Bridge redirect) and the fake popup used in fake mode."""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from workflow_demo.api.deps import DB, Services
from workflow_demo.services import deployments as svc_deployments
from workflow_demo.services.deployments import USER_STEP_MAX_AGE_SECONDS, USER_STEP_PURPOSE, DeploymentError

router = APIRouter(tags=["user-steps"])


def _page(title: str, body: str, ok: bool) -> HTMLResponse:
    message = json.dumps({"type": "wd:user-step", "ok": ok})
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui;margin:3rem;max-width:32rem">
<h1 style="font-size:1.4rem">{html.escape(title)}</h1><p>{html.escape(body)}</p>
<script>
if (window.opener) {{
  window.opener.postMessage({message}, window.location.origin);
  setTimeout(() => window.close(), 1500);
}}
</script>
</body></html>""",
        status_code=200 if ok else 400,
    )


@router.get("/make/callback", response_class=HTMLResponse)
def make_callback(request: Request, svc: Services, db: DB, state: str = "") -> HTMLResponse:
    payload = svc.signer.loads(state, USER_STEP_PURPOSE, USER_STEP_MAX_AGE_SECONDS)
    if not isinstance(payload, dict) or "deployment_id" not in payload:
        return _page("Link expired", "Start the deploy again from the demo.", ok=False)
    params = {k: v for k, v in request.query_params.items() if k != "state"}
    try:
        svc_deployments.finish_user_step(svc, db, payload, params)
    except DeploymentError as exc:
        return _page("Couldn't finish the deploy", exc.message, ok=False)
    return _page("All set", "Your workflow is deployed. You can close this window.", ok=True)


@router.get("/fake/make-popup", response_class=HTMLResponse)
def fake_make_popup(svc: Services, state: str = "") -> HTMLResponse:
    if not svc.settings.fake_platforms:
        raise HTTPException(404)
    target = f"/make/callback?state={html.escape(state)}"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>Make (fake)</title></head>
<body style="font-family:system-ui;margin:3rem;max-width:32rem">
<h1 style="font-size:1.4rem">Make popup (fake mode)</h1>
<p>In the real demo you connect GitHub and Slack and pick a repository and channel here.</p>
<p><a href="{target}" style="padding:.6rem 1rem;background:#6d28d9;color:#fff;border-radius:.4rem;
text-decoration:none">Connect accounts and finish</a></p></body></html>"""
    )
