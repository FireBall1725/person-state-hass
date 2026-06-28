"""Pure decision logic for Person State.

No Home Assistant imports on purpose: the cascade and the two hysteresis
modifiers are plain functions over primitive values, so they are trivial to
unit test. Everything HA-aware (building condition checkers, reading entity
states) lives in evaluator.py.
"""

from __future__ import annotations


def grace_active(
    previous_state: str | None,
    name: str,
    door_state: str | None,
    door_age: float | None,
    open_state: str,
    seconds: float,
) -> bool:
    """A quick door-open trip still counts as `name` for `seconds`.

    Only applies if we were already in this state and the door has been open
    no longer than the grace window.
    """
    if previous_state != name:
        return False
    if door_state != open_state:
        return False
    if door_age is None:
        return False
    return door_age <= seconds


def persist_active(
    previous_state: str | None,
    name: str,
    window_state: str | None,
    window_off_state: str,
    door_state: str | None,
    closed_state: str,
) -> bool:
    """Stay in `name` after the window helper turns off, while the door stays
    closed. Ports the original out-of-window "stay asleep" behavior.
    """
    if previous_state != name:
        return False
    if window_state != window_off_state:
        return False
    return door_state == closed_state


def pick_state(
    active_in_order: list[tuple[str, bool]],
    presence: str | None,
    away_from: str,
    away_state: str,
) -> str:
    """First state whose flag is true wins; else fall back to presence.

    `presence` is core's person state (home, not_home, or a zone name). The
    away_from value becomes away_state; anything else (home, Work, School)
    passes straight through.
    """
    for name, on in active_in_order:
        if on:
            return name
    if presence == away_from:
        return away_state
    return presence or away_state
