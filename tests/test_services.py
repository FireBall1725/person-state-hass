"""Manual override service: set, clear, and timed auto-revert."""

from __future__ import annotations

from datetime import timedelta

import pytest
from custom_components.statecraft.const import (
    ATTR_DURATION,
    ATTR_STATE,
    CONF_DEFAULT_STATE,
    CONF_NAME,
    CONF_SCOPE_NAME,
    CONF_SCOPE_TYPE,
    CONF_STATES,
    CONF_SUBJECT,
    DOMAIN,
    SCOPE_CUSTOM,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_SET_OVERRIDE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

SUBJECT = "statecraft.house"


@pytest.fixture
async def custom_scope(hass):
    """A custom scope whose only rule is off, so it sits at 'idle'."""
    # The referenced entity must exist and be off: a missing entity would trip
    # the engine's "keep state while a source is unavailable" latch and pin party.
    hass.states.async_set("input_boolean.party", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SUBJECT: SUBJECT,
            CONF_SCOPE_TYPE: SCOPE_CUSTOM,
            CONF_SCOPE_NAME: "House",
        },
        options={
            CONF_DEFAULT_STATE: "idle",
            CONF_STATES: [
                {
                    CONF_NAME: "party",
                    "condition": {
                        "condition": "state",
                        "entity_id": "input_boolean.party",
                        "state": "on",
                    },
                }
            ],
        },
        unique_id=SUBJECT,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_set_and_clear_override(hass, custom_scope):
    assert hass.states.get(SUBJECT).state == "idle"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_OVERRIDE,
        {ATTR_ENTITY_ID: SUBJECT, ATTR_STATE: "party"},
        blocking=True,
    )
    assert hass.states.get(SUBJECT).state == "party"

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_OVERRIDE, {ATTR_ENTITY_ID: SUBJECT}, blocking=True
    )
    assert hass.states.get(SUBJECT).state == "idle"


async def test_override_reverts_after_duration(hass, custom_scope):
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_OVERRIDE,
        {ATTR_ENTITY_ID: SUBJECT, ATTR_STATE: "party", ATTR_DURATION: {"seconds": 30}},
        blocking=True,
    )
    assert hass.states.get(SUBJECT).state == "party"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert hass.states.get(SUBJECT).state == "idle"


async def test_override_unknown_scope_raises(hass, custom_scope):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_OVERRIDE,
            {ATTR_ENTITY_ID: "statecraft.nope", ATTR_STATE: "party"},
            blocking=True,
        )
