"""The Person State integration.

Layers user-defined composite states and boolean attributes onto the core
person entity, instead of creating a parallel sensor. We never own the person
entity; we wrap its state computation (see augment.py).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .augment import (
    attach_listeners,
    get_person_entity,
    install_augmenter,
    remove_augmenter,
)
from .const import DOMAIN
from .data import PersonStateData
from .evaluator import StateEngine
from .models import parse_subject

_LOGGER = logging.getLogger(__name__)


async def _get_data(hass: HomeAssistant) -> PersonStateData:
    if DOMAIN not in hass.data:
        data = PersonStateData(hass)
        await data.async_load()
        hass.data[DOMAIN] = data
    return hass.data[DOMAIN]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one managed subject from a config entry."""
    data = await _get_data(hass)
    subject = parse_subject(dict(entry.data), dict(entry.options))

    engine = StateEngine(hass, subject)
    await engine.async_build()
    data.engines[subject.subject_entity_id] = engine

    install_augmenter(hass)

    # person is a core component loaded before us (after_dependencies), so its
    # entity already exists. Seed the restored composite state, then attach.
    entity = get_person_entity(hass, subject.subject_entity_id)
    if entity is None:
        _LOGGER.warning(
            "subject %s not loaded yet; will attach when it is added",
            subject.subject_entity_id,
        )
    else:
        restored = data.last_state.get(subject.subject_entity_id)
        if restored is not None:
            entity._attr_state = restored  # so first eval sees what we were
        attach_listeners(hass, entity, engine)

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one subject and restore plain presence."""
    data = await _get_data(hass)
    subject = parse_subject(dict(entry.data), dict(entry.options))
    subject_id = subject.subject_entity_id

    runtime = data.runtime.pop(subject_id, None)
    if runtime is not None:
        runtime.detach()
    data.engines.pop(subject_id, None)

    entity = get_person_entity(hass, subject_id)
    if entity is not None:
        entity._update_state()  # falls back to core presence (no engine now)

    if not data.engines:
        remove_augmenter(hass)

    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on options change."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
