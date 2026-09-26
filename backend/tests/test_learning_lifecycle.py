import pytest

from app.api.errors import AppError
from app.learning.lifecycle import transition


def test_return_preserves_paused_state_and_resume_is_explicit():
    assert transition("PAUSED", "RETURN") == "PAUSED"
    assert transition("PAUSED", "RESUME") == "ACTIVE"
    assert transition("ACTIVE", "PAUSE") == "PAUSED"
    assert transition("ACTIVE", "RETURN") == "ACTIVE"


@pytest.mark.parametrize(
    "status,action",
    [
        ("COMPLETED", "RETURN"),
        ("COMPLETED", "RESUME"),
        ("ACTIVE", "RESUME"),
        ("PAUSED", "PAUSE"),
    ],
)
def test_invalid_lifecycle_transition_is_a_conflict(status, action):
    with pytest.raises(AppError) as error:
        transition(status, action)
    assert error.value.status == 409
