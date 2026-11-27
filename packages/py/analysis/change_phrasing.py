"""Render signed changes for readers and narrator prompts."""


def percent_change_phrase(delta_pct: float, *, digits: int = 1) -> str:
    """Phrase a percent delta so the direction word and the number agree.

    Positive → ``"increased by 1.7%"``. Negative → ``"decreased by 1.7%"``.
    A value that rounds to zero at ``digits`` → ``"unchanged (0.0%)"``.
    """
    magnitude = abs(float(delta_pct))
    rendered = f"{magnitude:.{digits}f}"
    if rendered == f"{0:.{digits}f}":
        return f"unchanged ({rendered}%)"
    if delta_pct > 0:
        return f"increased by {rendered}%"
    return f"decreased by {rendered}%"
