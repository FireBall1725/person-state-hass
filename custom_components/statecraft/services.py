"""Manual-override services for Statecraft.

`statecraft.set_override` pins a scope (a person.* or statecraft.* subject) to a
state, bypassing the cascade, then reverts to automatic after an optional
duration. `statecraft.clear_override` drops it early. The override lives on the
scope's engine (evaluator.py); here we own the revert timer and force an
immediate re-evaluation on both the person and custom paths.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

from .augment import get_person_entity
from .const import (
    ATTR_DURATION,
    ATTR_STATE,
    DOMAIN,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_SET_OVERRIDE,
)
from .evaluator import StateEngine

_LOGGER = logging.getLogger(__name__)

SET_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_STATE): cv.string,
        vol.Optional(ATTR_DURATION): cv.positive_time_period,
    }
)
CLEAR_OVERRIDE_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})


def _engine(hass: HomeAssistant, entity_id: str) -> StateEngine:
    data = hass.data.get(DOMAIN)
    engine = data.engines.get(entity_id) if data is not None else None
    if engine is None:
        raise ServiceValidationError(f"{entity_id} is not a Statecraft scope")
    return engine


@callback
def _recompute_subject(hass: HomeAssistant, subject_id: str) -> None:
    """Force one scope to re-evaluate now, on whichever path drives it."""
    data = hass.data[DOMAIN]
    scope = data.custom_entities.get(subject_id)
    if scope is not None:  # custom scope: our owned entity
        scope._recompute()
        return
    entity = get_person_entity(hass, subject_id)  # person scope: core Person
    if entity is not None:
        entity._update_state()


async def _async_set_override(call: ServiceCall) -> None:
    hass = call.hass
    subject_id = call.data[ATTR_ENTITY_ID]
    engine = _engine(hass, subject_id)
    duration = call.data.get(ATTR_DURATION)
    secs = duration.total_seconds() if duration else None
    engine.set_override(call.data[ATTR_STATE], secs)
    if secs:

        @callback
        def _revert(_now: object) -> None:
            engine.clear_override()
            _recompute_subject(hass, subject_id)

        engine.override_cancel = async_call_later(hass, secs, _revert)
    _recompute_subject(hass, subject_id)


async def _async_clear_override(call: ServiceCall) -> None:
    hass = call.hass
    subject_id = call.data[ATTR_ENTITY_ID]
    engine = _engine(hass, subject_id)
    engine.clear_override()
    _recompute_subject(hass, subject_id)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the override services once for the domain (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_OVERRIDE):
        return
    hass.services.async_register(
        DOMAIN, SERVICE_SET_OVERRIDE, _async_set_override, SET_OVERRIDE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_OVERRIDE, _async_clear_override, CLEAR_OVERRIDE_SCHEMA
    )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the override services when the last scope unloads."""
    for service in (SERVICE_SET_OVERRIDE, SERVICE_CLEAR_OVERRIDE):
        hass.services.async_remove(DOMAIN, service)
