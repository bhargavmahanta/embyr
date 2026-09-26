from app.api.errors import AppError


def transition(status: str, action: str) -> str:
    target = {
        ("ACTIVE", "RETURN"): "ACTIVE",
        ("ACTIVE", "PAUSE"): "PAUSED",
        ("PAUSED", "RETURN"): "PAUSED",
        ("PAUSED", "RESUME"): "ACTIVE",
    }.get((status, action))
    if target is None:
        raise AppError(
            code="INVALID_EXPLORATION_TRANSITION",
            status=409,
            title="Invalid transition",
            detail="This action is unavailable in the current state.",
        )
    return target
