"""API for the shared Slack bot (``Authorization: Bearer <BOT_API_TOKEN>``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from workflow_demo.api.deps import DB, Services
from workflow_demo.security import passcode_matches
from workflow_demo.services import bot as svc_bot

SLACK_USER_ID = r"^[UW][A-Z0-9]{2,30}$"


def require_bot(svc: Services, authorization: Annotated[str | None, Header()] = None) -> None:
    token = svc.settings.bot_api_token
    if token is None or not token.get_secret_value():
        raise HTTPException(503, "The bot API isn't configured")
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not passcode_matches(given, token.get_secret_value()):
        raise HTTPException(401, "Invalid bot token")


router = APIRouter(prefix="/api/bot", tags=["bot"], dependencies=[Depends(require_bot)])


class UserKeyOut(BaseModel):
    user_key: str


class CardIn(BaseModel):
    slack_user_id: str = Field(pattern=SLACK_USER_ID)
    # Whatever the Slack message said (no limit there); shortened when stored.
    title: str = Field(min_length=1, max_length=40_000)
    url: str = Field(max_length=500, pattern=r"^https://")


class CardOut(BaseModel):
    recorded: bool


@router.get("/user-map/{slack_user_id}", response_model=UserKeyOut)
def user_map(slack_user_id: str, svc: Services, db: DB) -> UserKeyOut:
    key = svc_bot.user_key(svc, db, slack_user_id)
    if not key:
        raise HTTPException(404, "Not activated")
    return UserKeyOut(user_key=key)


@router.post("/cards", response_model=CardOut, status_code=202)
def card_created(body: CardIn, svc: Services, db: DB) -> CardOut:
    return CardOut(recorded=svc_bot.record_card(svc, db, body.slack_user_id, body.title, body.url))
