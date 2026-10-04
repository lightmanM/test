import pytest

from workflow_demo.services.states import InvalidTransition, Status, check_transition


def test_allowed_paths():
    check_transition(None, Status.DEPLOYING)
    check_transition(Status.DEPLOYING, Status.AWAITING_USER)
    check_transition(Status.AWAITING_USER, Status.ACTIVE)
    check_transition(Status.ACTIVE, Status.REDEPLOYING)
    check_transition(Status.FAILED, Status.STOPPING)
    check_transition(Status.STOPPING, Status.STOPPED)
    check_transition(Status.STOPPED, Status.DEPLOYING)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (None, Status.ACTIVE),
        (Status.ACTIVE, Status.DEPLOYING),
        (Status.STOPPED, Status.ACTIVE),
        (Status.DEPLOYING, Status.STOPPING),
    ],
)
def test_rejected_paths(current, new):
    with pytest.raises(InvalidTransition):
        check_transition(current, new)
