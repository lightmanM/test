"""Admin: sign-in, overview, setup check, sweeper, stopping a tester's deployment."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from workflow_demo.api.deps import DB, Admin, Services
from workflow_demo.api.schemas import AdminLoginRequest
from workflow_demo.db import User
from workflow_demo.security import ADMIN_COOKIE, passcode_matches
from workflow_demo.services import deployments as svc_deployments
from workflow_demo.services.deployments import DeploymentError
from workflow_demo.services.setup_check import run_checks
from workflow_demo.services.sweeper import sweep

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", status_code=204)
def admin_login(body: AdminLoginRequest, response: Response, svc: Services) -> None:
    if not passcode_matches(body.passcode, svc.settings.admin_passcode.get_secret_value()):
        raise HTTPException(401, "Wrong admin passcode")
    response.set_cookie(
        ADMIN_COOKIE,
        svc.signer.dumps({"admin": True}, ADMIN_COOKIE),
        max_age=svc.settings.admin_session_hours * 3600,
        httponly=True,
        secure=svc.settings.cookie_secure,
        samesite="lax",
    )


@router.post("/logout", status_code=204)
def admin_logout(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE)


@router.get("/overview", dependencies=[Admin])
def overview(svc: Services, db: DB) -> dict:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return {
        "max_users": svc.settings.max_users,
        "fake_platforms": svc.settings.fake_platforms,
        "users": [
            {
                "username": u.username,
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
                "connections": sorted(c.connector for c in u.connections if c.status == "active"),
                "deployments": [
                    {
                        "workflow_id": d.workflow_id,
                        "status": d.status,
                        "expires_at": d.expires_at,
                        "error": d.error,
                    }
                    for d in u.deployments
                ],
            }
            for u in users
        ],
    }


@router.get("/setup", dependencies=[Admin])
def setup_check(svc: Services) -> dict:
    return run_checks(svc)


@router.post("/sweep", dependencies=[Admin])
def run_sweep(svc: Services) -> dict:
    return asdict(sweep(svc))


@router.post("/users/{username}/deployments/{workflow_id}/stop", status_code=202, dependencies=[Admin])
def stop_deployment(username: str, workflow_id: str, svc: Services, db: DB) -> dict:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(404, "Unknown user")
    try:
        dep = svc_deployments.request_delete(svc, db, user, workflow_id, reason="Stopped by the admin")
    except DeploymentError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return {"status": dep.status}
