"""Sign-in: username + shared passcode (demo rule R1/R2)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from workflow_demo.api.deps import DB, CurrentUser, Services
from workflow_demo.api.schemas import LoginRequest, Me
from workflow_demo.db import User, utcnow
from workflow_demo.security import SESSION_COOKIE, passcode_matches

router = APIRouter(prefix="/api", tags=["auth"])

USERNAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$")


def normalize_username(raw: str) -> str:
    return raw.strip().lower()


@router.post("/auth/login", response_model=Me)
def login(body: LoginRequest, response: Response, svc: Services, db: DB) -> Me:
    username = normalize_username(body.username)
    if not USERNAME.match(username):
        raise HTTPException(422, "Username: 3-20 characters, letters, digits and dashes")
    if not passcode_matches(body.passcode, svc.settings.demo_passcode.get_secret_value()):
        raise HTTPException(401, "Wrong passcode")
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        if db.scalar(select(func.count(User.id))) >= svc.settings.max_users:
            raise HTTPException(403, "The demo is full; sign in with an existing username")
        user = User(username=username)
        db.add(user)
    user.last_login_at = utcnow()
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        svc.signer.dumps({"uid": user.id}, SESSION_COOKIE),
        max_age=svc.settings.session_days * 86400,
        httponly=True,
        secure=svc.settings.cookie_secure,
        samesite="lax",
    )
    return Me(username=user.username)


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", response_model=Me)
def me(user: CurrentUser) -> Me:
    return Me(username=user.username)
