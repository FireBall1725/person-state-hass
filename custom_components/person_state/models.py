"""Data model for Person State, parsed from the config entry.

These are plain dataclasses with no Home Assistant runtime dependency so the
shape is easy to reason about and test. Condition configs are stored as the
native HA condition dicts (already validated by the config flow on save).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .const import (
    CONF_AWAY_FROM,
    CONF_AWAY_STATE,
    CONF_CONDITION,
    CONF_GRACE,
    CONF_GRACE_DOOR,
    CONF_GRACE_OPEN_STATE,
    CONF_GRACE_SECONDS,
    CONF_NAME,
    CONF_PERSIST,
    CONF_PERSIST_CLOSED_STATE,
    CONF_PERSIST_DOOR,
    CONF_PERSIST_WINDOW,
    CONF_PERSIST_WINDOW_OFF,
    CONF_STATES,
    CONF_SUBJECT,
    DEFAULT_AWAY_FROM,
    DEFAULT_AWAY_STATE,
    DEFAULT_CLOSED_STATE,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_OPEN_STATE,
    DEFAULT_WINDOW_OFF_STATE,
)


@dataclass(frozen=True)
class GraceModifier:
    """A door-open trip still counts as this state for `seconds`."""

    door_entity_id: str
    open_state: str
    seconds: float


@dataclass(frozen=True)
class PersistModifier:
    """Stay in this state while a window helper is off and the door is closed."""

    window_entity_id: str
    window_off_state: str
    door_entity_id: str
    closed_state: str


@dataclass(frozen=True)
class StateDef:
    """One user-defined composite state."""

    name: str
    condition: dict[str, Any]
    grace: GraceModifier | None
    persist: PersistModifier | None


@dataclass(frozen=True)
class SubjectConfig:
    """Everything one config entry manages."""

    subject_entity_id: str
    states: tuple[StateDef, ...]  # priority order: first true wins
    away_from: str
    away_state: str


def _parse_grace(raw: dict[str, Any] | None) -> GraceModifier | None:
    if not raw:
        return None
    return GraceModifier(
        door_entity_id=raw[CONF_GRACE_DOOR],
        open_state=raw.get(CONF_GRACE_OPEN_STATE, DEFAULT_OPEN_STATE),
        seconds=float(raw.get(CONF_GRACE_SECONDS, DEFAULT_GRACE_SECONDS)),
    )


def _parse_persist(raw: dict[str, Any] | None) -> PersistModifier | None:
    if not raw:
        return None
    return PersistModifier(
        window_entity_id=raw[CONF_PERSIST_WINDOW],
        window_off_state=raw.get(CONF_PERSIST_WINDOW_OFF, DEFAULT_WINDOW_OFF_STATE),
        door_entity_id=raw[CONF_PERSIST_DOOR],
        closed_state=raw.get(CONF_PERSIST_CLOSED_STATE, DEFAULT_CLOSED_STATE),
    )


def parse_subject(data: dict[str, Any], options: dict[str, Any]) -> SubjectConfig:
    """Build a SubjectConfig from entry.data + entry.options."""
    merged = {**data, **options}
    states = tuple(
        StateDef(
            name=raw[CONF_NAME],
            condition=raw[CONF_CONDITION],
            grace=_parse_grace(raw.get(CONF_GRACE)),
            persist=_parse_persist(raw.get(CONF_PERSIST)),
        )
        for raw in merged.get(CONF_STATES, [])
    )
    return SubjectConfig(
        subject_entity_id=merged[CONF_SUBJECT],
        states=states,
        away_from=merged.get(CONF_AWAY_FROM, DEFAULT_AWAY_FROM),
        away_state=merged.get(CONF_AWAY_STATE, DEFAULT_AWAY_STATE),
    )


def collect_for_horizons(config: Any) -> list[float]:
    """Walk a condition config and collect every `for:` duration in seconds.

    Lets the engine schedule a precise re-evaluation when a `for:` window is due
    to elapse, instead of relying only on the periodic safety net.
    """
    horizons: list[float] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "for":
                    secs = _to_seconds(value)
                    if secs is not None:
                        horizons.append(secs)
                else:
                    _walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item)

    _walk(config)
    return horizons


def _to_seconds(value: Any) -> float | None:
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        td = timedelta(
            hours=float(value.get("hours", 0)),
            minutes=float(value.get("minutes", 0)),
            seconds=float(value.get("seconds", 0)),
        )
        return td.total_seconds()
    if isinstance(value, str):
        parts = value.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        while len(nums) < 3:
            nums.insert(0, 0.0)
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None
