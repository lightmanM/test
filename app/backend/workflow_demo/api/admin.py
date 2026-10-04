"""Admin sign-in and overview (more actions in P6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from workflow_demo.api.deps import DB, Admin, Services
from workflow_demo.api.schemas import AdminLoginRequest
from workflow_demo.db import User
from workflow_demo.security import ADMIN_COOKIE, passcode_matches

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
