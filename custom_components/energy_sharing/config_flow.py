"""Config flow for Energy Sharing."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.typing import ConfigType

from . import EnergySharingConfigEntry
from .const import (
    CONF_ALLOW_PERCENTAGE_ABOVE_100,
    CONF_FIXED_PERCENTAGE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PERCENTAGE_ENTITY,
    CONF_PERCENTAGE_MODE,
    CONF_PROCESSING_DELAY,
    CONF_RESET_TOLERANCE,
    CONF_RETRY_INTERVAL,
    CONF_SHARED_ENERGY_ENTITY,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_FIXED_PERCENTAGE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_NAME,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RESET_TOLERANCE,
    DEFAULT_RETRY_INTERVAL,
    DOMAIN,
    MAX_INTERVAL_MINUTES,
    MAX_MAX_WAIT,
    MAX_PROCESSING_DELAY,
    MAX_RESET_TOLERANCE,
    MAX_RETRY_INTERVAL,
    MIN_INTERVAL_MINUTES,
    MIN_MAX_WAIT,
    MIN_PROCESSING_DELAY,
    MIN_RESET_TOLERANCE,
    MIN_RETRY_INTERVAL,
    PERCENTAGE_MODE_ENTITY,
    PERCENTAGE_MODE_FIXED,
)
from .helpers import validate_percentage_entity, validate_utility_meter_entity

_LOGGER = logging.getLogger(__name__)


def _default_options() -> dict[str, Any]:
    """Return default option values."""
    return {
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
        CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
        CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
        CONF_RESET_TOLERANCE: DEFAULT_RESET_TOLERANCE,
        CONF_FIXED_PERCENTAGE: DEFAULT_FIXED_PERCENTAGE,
        CONF_ALLOW_PERCENTAGE_ABOVE_100: False,
    }


def _user_schema(hass: HomeAssistant, defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the user setup schema."""
    defaults = defaults or {}
    percentage_mode = defaults.get(CONF_PERCENTAGE_MODE, PERCENTAGE_MODE_ENTITY)

    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
        ): selector.TextSelector(),
        vol.Required(
            CONF_GRID_IMPORT_ENTITY,
            default=defaults.get(CONF_GRID_IMPORT_ENTITY),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor"])
        ),
        vol.Required(
            CONF_SHARED_ENERGY_ENTITY,
            default=defaults.get(CONF_SHARED_ENERGY_ENTITY),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor"])
        ),
        vol.Required(
            CONF_PERCENTAGE_MODE,
            default=percentage_mode,
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=PERCENTAGE_MODE_ENTITY,
                        label="percentage_mode_entity",
                    ),
                    selector.SelectOptionDict(
                        value=PERCENTAGE_MODE_FIXED,
                        label="percentage_mode_fixed",
                    ),
                ],
                translation_key="percentage_mode",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }

    if percentage_mode == PERCENTAGE_MODE_ENTITY:
        schema[
            vol.Required(
                CONF_PERCENTAGE_ENTITY,
                default=defaults.get(CONF_PERCENTAGE_ENTITY),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["input_number", "sensor", "number"])
        )
    else:
        schema[
            vol.Required(
                CONF_FIXED_PERCENTAGE,
                default=defaults.get(CONF_FIXED_PERCENTAGE, DEFAULT_FIXED_PERCENTAGE),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=0.01, max=1000))

    return vol.Schema(schema)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the options schema."""
    percentage_mode = defaults.get(CONF_PERCENTAGE_MODE, PERCENTAGE_MODE_ENTITY)
    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
        ): selector.TextSelector(),
        vol.Required(
            CONF_INTERVAL_MINUTES,
            default=defaults.get(CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_INTERVAL_MINUTES, max=MAX_INTERVAL_MINUTES)),
        vol.Required(
            CONF_PROCESSING_DELAY,
            default=defaults.get(CONF_PROCESSING_DELAY, DEFAULT_PROCESSING_DELAY),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_PROCESSING_DELAY, max=MAX_PROCESSING_DELAY),
        ),
        vol.Required(
            CONF_MAX_WAIT,
            default=defaults.get(CONF_MAX_WAIT, DEFAULT_MAX_WAIT),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_MAX_WAIT, max=MAX_MAX_WAIT)),
        vol.Required(
            CONF_RETRY_INTERVAL,
            default=defaults.get(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_RETRY_INTERVAL, max=MAX_RETRY_INTERVAL),
        ),
        vol.Required(
            CONF_RESET_TOLERANCE,
            default=defaults.get(CONF_RESET_TOLERANCE, DEFAULT_RESET_TOLERANCE),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_RESET_TOLERANCE, max=MAX_RESET_TOLERANCE),
        ),
        vol.Required(
            CONF_ALLOW_PERCENTAGE_ABOVE_100,
            default=defaults.get(CONF_ALLOW_PERCENTAGE_ABOVE_100, False),
        ): selector.BooleanSelector(),
    }

    if percentage_mode == PERCENTAGE_MODE_FIXED:
        schema[
            vol.Required(
                CONF_FIXED_PERCENTAGE,
                default=defaults.get(CONF_FIXED_PERCENTAGE, DEFAULT_FIXED_PERCENTAGE),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=0.01, max=1000))

    return vol.Schema(schema)


class EnergySharingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Sharing."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._user_input = user_input
            errors = await self._async_validate_user_input(user_input)
            if not errors:
                await self.async_set_unique_id(
                    self._build_unique_id(
                        user_input[CONF_GRID_IMPORT_ENTITY],
                        user_input[CONF_SHARED_ENERGY_ENTITY],
                    )
                )
                self._abort_if_unique_id_configured()

                options = _default_options()
                if user_input[CONF_PERCENTAGE_MODE] == PERCENTAGE_MODE_FIXED:
                    options[CONF_FIXED_PERCENTAGE] = user_input[CONF_FIXED_PERCENTAGE]

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=self._build_entry_data(user_input),
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self.hass, self._user_input or None),
            errors=errors,
        )

    @staticmethod
    def _build_unique_id(grid_import_entity: str, shared_energy_entity: str) -> str:
        """Build a stable unique ID for duplicate protection."""
        return f"{grid_import_entity}|{shared_energy_entity}"

    @staticmethod
    def _build_entry_data(user_input: dict[str, Any]) -> dict[str, Any]:
        """Build immutable config entry data."""
        data: dict[str, Any] = {
            CONF_GRID_IMPORT_ENTITY: user_input[CONF_GRID_IMPORT_ENTITY],
            CONF_SHARED_ENERGY_ENTITY: user_input[CONF_SHARED_ENERGY_ENTITY],
            CONF_PERCENTAGE_MODE: user_input[CONF_PERCENTAGE_MODE],
        }
        if user_input[CONF_PERCENTAGE_MODE] == PERCENTAGE_MODE_ENTITY:
            data[CONF_PERCENTAGE_ENTITY] = user_input[CONF_PERCENTAGE_ENTITY]
        return data

    async def _async_validate_user_input(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate user input."""
        errors: dict[str, str] = {}

        if user_input[CONF_GRID_IMPORT_ENTITY] == user_input[CONF_SHARED_ENERGY_ENTITY]:
            errors["base"] = "duplicate_entities"
            return errors

        for key, entity_id in (
            ("grid_import", user_input[CONF_GRID_IMPORT_ENTITY]),
            ("shared_energy", user_input[CONF_SHARED_ENERGY_ENTITY]),
        ):
            try:
                await validate_utility_meter_entity(self.hass, entity_id)
            except ValueError:
                errors[key] = "invalid_utility_meter"

        if user_input[CONF_PERCENTAGE_MODE] == PERCENTAGE_MODE_ENTITY:
            try:
                await validate_percentage_entity(
                    self.hass, user_input[CONF_PERCENTAGE_ENTITY]
                )
            except ValueError:
                errors["percentage"] = "invalid_percentage_entity"

        return errors

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: EnergySharingConfigEntry,
    ) -> EnergySharingOptionsFlowHandler:
        """Get the options flow for this handler."""
        return EnergySharingOptionsFlowHandler()


class EnergySharingOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Energy Sharing."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        defaults = {
            CONF_NAME: self.config_entry.title,
            CONF_PERCENTAGE_MODE: self.config_entry.data[CONF_PERCENTAGE_MODE],
            **self.config_entry.options,
        }

        if user_input is not None:
            if self.config_entry.data[CONF_PERCENTAGE_MODE] == PERCENTAGE_MODE_FIXED:
                fixed_pct = user_input.get(CONF_FIXED_PERCENTAGE)
                if fixed_pct is None or fixed_pct <= 0:
                    errors[CONF_FIXED_PERCENTAGE] = "invalid_percentage"

            if not errors:
                new_title = user_input.pop(CONF_NAME)
                await self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=new_title,
                    options=user_input,
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults),
            errors=errors,
            description_placeholders={
                "grid_import_entity": self.config_entry.data[CONF_GRID_IMPORT_ENTITY],
                "shared_energy_entity": self.config_entry.data[CONF_SHARED_ENERGY_ENTITY],
                "percentage_mode": self.config_entry.data[CONF_PERCENTAGE_MODE],
                "percentage_entity": self.config_entry.data.get(CONF_PERCENTAGE_ENTITY, ""),
            },
        )

    @staticmethod
    def _async_update_options(
        hass: HomeAssistant,
        config_entry: EnergySharingConfigEntry,
        options: ConfigType,
    ) -> None:
        """Update stored options."""
        hass.config_entries.async_update_entry(config_entry, options=options)
