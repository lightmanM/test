"""Deployment status values and allowed transitions."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    DEPLOYING = "deploying"
    AWAITING_USER = "awaiting_user"  # user must finish a step on the platform (Make popup)
    ACTIVE = "active"
    FAILED = "failed"
    REDEPLOYING = "redeploying"
    STOPPING = "stopping"
    STOPPED = "stopped"


BUSY = frozenset({Status.DEPLOYING, Status.REDEPLOYING, Status.STOPPING})

TRANSITIONS: dict[Status | None, frozenset[Status]] = {
    None: frozenset({Status.DEPLOYING}),
    Status.STOPPED: frozenset({Status.DEPLOYING}),
    Status.DEPLOYING: frozenset({Status.ACTIVE, Status.AWAITING_USER, Status.FAILED}),
    Status.REDEPLOYING: frozenset({Status.ACTIVE, Status.AWAITING_USER, Status.FAILED}),
    # DEPLOYING: the user finished the popup and a job completes the deploy on the platform.
    Status.AWAITING_USER: frozenset(
        {Status.DEPLOYING, Status.ACTIVE, Status.FAILED, Status.REDEPLOYING, Status.STOPPING}
    ),
    Status.ACTIVE: frozenset({Status.REDEPLOYING, Status.STOPPING}),
    Status.FAILED: frozenset({Status.REDEPLOYING, Status.STOPPING}),
    Status.STOPPING: frozenset({Status.STOPPED, Status.FAILED}),
}


class InvalidTransition(Exception):
    pass


def check_transition(current: str | None, new: Status) -> None:
    current_status = Status(current) if current is not None else None
    if new not in TRANSITIONS[current_status]:
        raise InvalidTransition(f"cannot go from {current_status} to {new}")
