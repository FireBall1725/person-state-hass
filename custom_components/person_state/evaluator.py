"""HA-aware state engine: turns a SubjectConfig into a composite state.

Builds one condition checker per user-defined state via HA's native condition
helper, then on each evaluation runs the cascade and layers the optional grace
/ persist modifiers on top.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import condition
import homeassistant.util.dt as dt_util

from .core import grace_active, persist_active, pick_state
from .models import SubjectConfig, collect_for_horizons

_LOGGER = logging.getLogger(__name__)

# Circuit breaker: if the cascade is applied more than this many times within
# the window, assume a feedback loop and stop. This makes it impossible for any
# loop (known or not) to hang the event loop / take HA down.
_BREAKER_MAX = 25
_BREAKER_WINDOW = 2.0  # seconds


def _run_checker(checker: Any, hass: HomeAssistant) -> bool:
    """Evaluate a condition checker, tolerant of None / version differences."""
    if checker is None:
        return False
    try:
        check = getattr(checker, "async_check", None)
        result = check(variables=None) if check is not None else checker(hass, None)
    except Exception as err:  # noqa: BLE001 - a bad condition must not crash person
        _LOGGER.debug("condition check failed: %s", err)
        return False
    return bool(result)


class StateEngine:
    """Evaluates one subject's states."""

    def __init__(self, hass: HomeAssistant, subject: SubjectConfig) -> None:
        self.hass = hass
        self.subject = subject
        self._checkers: dict[str, Any] = {}
        # entities to subscribe to so we re-evaluate on change
        self.entities: set[str] = set()
        # `for:` / grace durations to schedule precise re-evaluations
        self.for_horizons: list[float] = []
        # circuit breaker state (see allow_apply)
        self._apply_times: deque[float] = deque()
        self.tripped: bool = False

    def allow_apply(self) -> bool:
        """Return False if the cascade is running away (feedback loop).

        Once tripped, stays tripped until the entry reloads (a fresh engine is
        built). The caller logs the trip once, with the watched entities, so the
        offending source can be identified without HA going down.
        """
        if self.tripped:
            return False
        now = time.monotonic()
        self._apply_times.append(now)
        while self._apply_times and now - self._apply_times[0] > _BREAKER_WINDOW:
            self._apply_times.popleft()
        if len(self._apply_times) > _BREAKER_MAX:
            self.tripped = True
            return False
        return True

    async def async_build(self) -> None:
        """Compile condition checkers and collect what to watch."""
        self._checkers.clear()
        self.entities.clear()
        self.for_horizons.clear()

        for state_def in self.subject.states:
            try:
                self._checkers[state_def.name] = await condition.async_from_config(
                    self.hass, state_def.condition
                )
            except Exception as err:  # noqa: BLE001 - surface, do not crash setup
                _LOGGER.error(
                    "state %r has an invalid condition, it will never be true: %s",
                    state_def.name,
                    err,
                )
                self._checkers[state_def.name] = None

            try:
                self.entities |= condition.async_extract_entities(state_def.condition)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("could not extract entities for %r: %s", state_def.name, err)

            self.for_horizons.extend(collect_for_horizons(state_def.condition))

            if state_def.grace is not None:
                self.entities.add(state_def.grace.door_entity_id)
                self.for_horizons.append(state_def.grace.seconds)
            if state_def.persist is not None:
                self.entities.add(state_def.persist.window_entity_id)
                self.entities.add(state_def.persist.door_entity_id)

    @callback
    def evaluate(
        self, presence: str | None, previous_state: str | None
    ) -> tuple[str, dict[str, bool]]:
        """Return (composite_state, {state_name: active})."""
        ordered = [
            (sd.name, self._state_on(sd, previous_state)) for sd in self.subject.states
        ]
        state = pick_state(
            ordered, presence, self.subject.away_from, self.subject.away_state
        )
        return state, dict(ordered)

    @callback
    def _state_on(self, state_def, previous_state: str | None) -> bool:
        if _run_checker(self._checkers.get(state_def.name), self.hass):
            return True

        if state_def.grace is not None:
            door_state, door_age = self._door(state_def.grace.door_entity_id)
            if grace_active(
                previous_state,
                state_def.name,
                door_state,
                door_age,
                state_def.grace.open_state,
                state_def.grace.seconds,
            ):
                return True

        if state_def.persist is not None:
            if persist_active(
                previous_state,
                state_def.name,
                self._state(state_def.persist.window_entity_id),
                state_def.persist.window_off_state,
                self._state(state_def.persist.door_entity_id),
                state_def.persist.closed_state,
            ):
                return True

        return False

    def _door(self, entity_id: str) -> tuple[str | None, float | None]:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None, None
        age = (dt_util.utcnow() - state.last_changed).total_seconds()
        return state.state, age

    def _state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return None if state is None else state.state
