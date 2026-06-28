"""Config + options flow for Person State.

The config step picks the subject (a person) and the away mapping. All the
interesting work happens in the options flow: a menu to add/edit/remove the
ordered list of composite states. Each state has structured fields for the
fixed knobs (name, grace, persist) and a YAML field for its condition, which
is where the nested AND/OR + numeric logic lives.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import condition, selector

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
    DOMAIN,
    PERSON_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_PERSON_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=PERSON_DOMAIN)
)
_ANY_ENTITY_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig())
_TEXT = selector.TextSelector()
_YAML = selector.TextSelector(
    selector.TextSelectorConfig(multiline=True)
)
_BOOL = selector.BooleanSelector()
_SECONDS = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=86400, step=10, unit_of_measurement="s", mode="box"
    )
)

# Keys used only inside the state form (flattened for the UI).
_F_ENABLE_GRACE = "enable_grace"
_F_ENABLE_PERSIST = "enable_persist"


class PersonStateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick the subject; states are added afterwards in options."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            subject = user_input[CONF_SUBJECT]
            await self.async_set_unique_id(subject)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=subject,
                data={CONF_SUBJECT: subject},
                options={
                    CONF_AWAY_FROM: user_input[CONF_AWAY_FROM],
                    CONF_AWAY_STATE: user_input[CONF_AWAY_STATE],
                    CONF_STATES: [],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_SUBJECT): _PERSON_SELECTOR,
                vol.Required(CONF_AWAY_FROM, default=DEFAULT_AWAY_FROM): _TEXT,
                vol.Required(CONF_AWAY_STATE, default=DEFAULT_AWAY_STATE): _TEXT,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(entry) -> OptionsFlow:
        return PersonStateOptionsFlow()


class PersonStateOptionsFlow(OptionsFlow):
    """Menu-driven editing of the subject settings and the state list."""

    def __init__(self) -> None:
        self._states: list[dict[str, Any]] = []
        self._away_from: str = DEFAULT_AWAY_FROM
        self._away_state: str = DEFAULT_AWAY_STATE
        self._editing: int | None = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        opts = self.config_entry.options
        self._states = [dict(s) for s in opts.get(CONF_STATES, [])]
        self._away_from = opts.get(CONF_AWAY_FROM, DEFAULT_AWAY_FROM)
        self._away_state = opts.get(CONF_AWAY_STATE, DEFAULT_AWAY_STATE)
        self._loaded = True

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(
            data={
                CONF_AWAY_FROM: self._away_from,
                CONF_AWAY_STATE: self._away_state,
                CONF_STATES: self._states,
            }
        )

    # --- menu ---------------------------------------------------------------
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        options = ["add_state", "settings", "save"]
        if self._states:
            options[1:1] = ["edit_state", "remove_state"]
        return self.async_show_menu(step_id="init", menu_options=options)

    # --- add / edit ---------------------------------------------------------
    async def async_step_add_state(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._editing = None
        return await self._state_form(user_input)

    async def async_step_edit_state(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        if user_input is not None:
            self._editing = int(user_input["index"])
            return await self._state_form(None)
        names = [
            {"value": str(i), "label": s[CONF_NAME]}
            for i, s in enumerate(self._states)
        ]
        schema = vol.Schema(
            {
                vol.Required("index"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=names)
                )
            }
        )
        return self.async_show_form(step_id="edit_state", data_schema=schema)

    async def _state_form(
        self, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                parsed_condition = yaml.safe_load(user_input[CONF_CONDITION])
            except yaml.YAMLError:
                parsed_condition = None
                errors[CONF_CONDITION] = "invalid_yaml"

            if not errors:
                try:
                    parsed_condition = await condition.async_validate_condition_config(
                        self.hass, parsed_condition
                    )
                except Exception:  # noqa: BLE001 - any validation failure -> form error
                    errors[CONF_CONDITION] = "invalid_condition"

            if not errors:
                entry: dict[str, Any] = {
                    CONF_NAME: user_input[CONF_NAME].strip(),
                    CONF_CONDITION: parsed_condition,
                }
                if user_input.get(_F_ENABLE_GRACE):
                    entry[CONF_GRACE] = {
                        CONF_GRACE_DOOR: user_input[CONF_GRACE_DOOR],
                        CONF_GRACE_OPEN_STATE: user_input[CONF_GRACE_OPEN_STATE],
                        CONF_GRACE_SECONDS: user_input[CONF_GRACE_SECONDS],
                    }
                if user_input.get(_F_ENABLE_PERSIST):
                    entry[CONF_PERSIST] = {
                        CONF_PERSIST_WINDOW: user_input[CONF_PERSIST_WINDOW],
                        CONF_PERSIST_WINDOW_OFF: user_input[CONF_PERSIST_WINDOW_OFF],
                        CONF_PERSIST_DOOR: user_input[CONF_PERSIST_DOOR],
                        CONF_PERSIST_CLOSED_STATE: user_input[CONF_PERSIST_CLOSED_STATE],
                    }

                if self._editing is None:
                    self._states.append(entry)
                else:
                    self._states[self._editing] = entry
                return await self.async_step_init()

        return self.async_show_form(
            step_id="add_state" if self._editing is None else "edit_state",
            data_schema=self._state_schema(),
            errors=errors,
        )

    def _state_schema(self) -> vol.Schema:
        current: dict[str, Any] = {}
        if self._editing is not None:
            current = self._states[self._editing]
        grace = current.get(CONF_GRACE, {})
        persist = current.get(CONF_PERSIST, {})

        cond_yaml = ""
        if current.get(CONF_CONDITION):
            cond_yaml = yaml.safe_dump(current[CONF_CONDITION], sort_keys=False)

        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): _TEXT,
                vol.Required(CONF_CONDITION, default=cond_yaml): _YAML,
                vol.Optional(
                    _F_ENABLE_GRACE, default=bool(grace)
                ): _BOOL,
                vol.Optional(
                    CONF_GRACE_DOOR,
                    default=grace.get(CONF_GRACE_DOOR, vol.UNDEFINED),
                ): _ANY_ENTITY_SELECTOR,
                vol.Optional(
                    CONF_GRACE_OPEN_STATE,
                    default=grace.get(CONF_GRACE_OPEN_STATE, DEFAULT_OPEN_STATE),
                ): _TEXT,
                vol.Optional(
                    CONF_GRACE_SECONDS,
                    default=grace.get(CONF_GRACE_SECONDS, DEFAULT_GRACE_SECONDS),
                ): _SECONDS,
                vol.Optional(
                    _F_ENABLE_PERSIST, default=bool(persist)
                ): _BOOL,
                vol.Optional(
                    CONF_PERSIST_WINDOW,
                    default=persist.get(CONF_PERSIST_WINDOW, vol.UNDEFINED),
                ): _ANY_ENTITY_SELECTOR,
                vol.Optional(
                    CONF_PERSIST_WINDOW_OFF,
                    default=persist.get(
                        CONF_PERSIST_WINDOW_OFF, DEFAULT_WINDOW_OFF_STATE
                    ),
                ): _TEXT,
                vol.Optional(
                    CONF_PERSIST_DOOR,
                    default=persist.get(CONF_PERSIST_DOOR, vol.UNDEFINED),
                ): _ANY_ENTITY_SELECTOR,
                vol.Optional(
                    CONF_PERSIST_CLOSED_STATE,
                    default=persist.get(
                        CONF_PERSIST_CLOSED_STATE, DEFAULT_CLOSED_STATE
                    ),
                ): _TEXT,
            }
        )

    # --- remove -------------------------------------------------------------
    async def async_step_remove_state(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        if user_input is not None:
            drop = {int(i) for i in user_input.get("indexes", [])}
            self._states = [
                s for i, s in enumerate(self._states) if i not in drop
            ]
            return await self.async_step_init()
        names = [
            {"value": str(i), "label": s[CONF_NAME]}
            for i, s in enumerate(self._states)
        ]
        schema = vol.Schema(
            {
                vol.Required("indexes", default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=names, multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="remove_state", data_schema=schema)

    # --- settings -----------------------------------------------------------
    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        if user_input is not None:
            self._away_from = user_input[CONF_AWAY_FROM]
            self._away_state = user_input[CONF_AWAY_STATE]
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(CONF_AWAY_FROM, default=self._away_from): _TEXT,
                vol.Required(CONF_AWAY_STATE, default=self._away_state): _TEXT,
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    # --- save ---------------------------------------------------------------
    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        return self._save()
