"""FastAPI dependencies: services, DB session, current user, admin."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from workflow_demo.db import User
from workflow_demo.security import ADMIN_COOKIE, SESSION_COOKIE
from workflow_demo.services.container import AppServices


def get_services(request: Request) -> AppServices:
    return request.app.state.services


Services = Annotated[AppServices, Depends(get_services)]


def get_db(svc: Services) -> Iterator[Session]:
    with svc.db.session() as session:
        yield session


DB = Annotated[Session, Depends(get_db)]


def current_user(svc: Services, db: DB, wd_session: Annotated[str | None, Cookie()] = None) -> User:
    payload = svc.signer.loads(wd_session, SESSION_COOKIE, svc.settings.session_days * 86400)
    user = db.get(User, payload["uid"]) if isinstance(payload, dict) and "uid" in payload else None
    # Also match the username, so a cookie can't outlive its user if an id is ever reused.
    if user is None or user.username != payload.get("username"):
        raise HTTPException(401, "Sign in first")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(svc: Services, wd_admin: Annotated[str | None, Cookie()] = None) -> None:
    payload = svc.signer.loads(wd_admin, ADMIN_COOKIE, svc.settings.admin_session_hours * 3600)
    if payload != {"admin": True}:
        raise HTTPException(401, "Admin sign-in required")


Admin = Depends(require_admin)
