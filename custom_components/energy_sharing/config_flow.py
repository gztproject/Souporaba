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

from . import EnergySharingConfigEntry
from .const import (
    CONF_ALLOCATION_PERCENTAGE_MODE,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_ALLOCATION_TOLERANCE_KWH,
    CONF_ALLOCATION_TOLERANCE_PCT,
    CONF_ALLOW_PERCENTAGE_ABOVE_100,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_FIXED_PERCENTAGE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PERCENTAGE_ENTITY,
    CONF_PERCENTAGE_MODE,
    CONF_PROCESSING_DELAY,
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_RECONCILIATION_FAILURE_MODE,
    CONF_REPORTED_ALLOCATION_SOURCE,
    CONF_RESET_TOLERANCE,
    CONF_RETRY_INTERVAL,
    CONF_SHARED_ENERGY_ENTITY,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_ALLOCATION_TOLERANCE_KWH,
    DEFAULT_ALLOCATION_TOLERANCE_PCT,
    DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_NAME,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RECONCILIATION_FAILURE_MODE,
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
    RECONCILIATION_MODE_SKIP_INTERVAL,
    RECONCILIATION_MODE_WARN,
)
from .helpers import (
    IntervalSourceValidationError,
    validate_interval_source,
    validate_percentage_source,
)

_LOGGER = logging.getLogger(__name__)

_ENERGY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain=["sensor"],
        device_class=["energy"],
    )
)

_PERCENTAGE_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["input_number", "sensor", "number"])
)


def _default_options() -> dict[str, Any]:
    """Return default option values."""
    return {
        CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
        CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
        CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
        CONF_RESET_TOLERANCE: DEFAULT_RESET_TOLERANCE,
        CONF_FIXED_ALLOCATION_PERCENTAGE: DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
        CONF_ALLOCATION_TOLERANCE_KWH: DEFAULT_ALLOCATION_TOLERANCE_KWH,
        CONF_ALLOCATION_TOLERANCE_PCT: DEFAULT_ALLOCATION_TOLERANCE_PCT,
        CONF_RECONCILIATION_FAILURE_MODE: DEFAULT_RECONCILIATION_FAILURE_MODE,
        CONF_ALLOW_PERCENTAGE_ABOVE_100: False,
    }


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the user setup schema."""
    defaults = defaults or {}
    percentage_mode = defaults.get(
        CONF_ALLOCATION_PERCENTAGE_MODE, PERCENTAGE_MODE_ENTITY
    )

    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
        ): selector.TextSelector(),
        vol.Required(
            CONF_PROVIDER_EXPORT_SOURCE,
            default=defaults.get(CONF_PROVIDER_EXPORT_SOURCE),
        ): _ENERGY_SELECTOR,
        vol.Required(
            CONF_RECEIVER_IMPORT_SOURCE,
            default=defaults.get(CONF_RECEIVER_IMPORT_SOURCE),
        ): _ENERGY_SELECTOR,
        vol.Optional(
            CONF_REPORTED_ALLOCATION_SOURCE,
            default=defaults.get(CONF_REPORTED_ALLOCATION_SOURCE),
        ): vol.Any(
            None,
            "",
            _ENERGY_SELECTOR,
        ),
        vol.Required(
            CONF_ALLOCATION_PERCENTAGE_MODE,
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
        vol.Optional(
            CONF_ALLOCATION_PERCENTAGE_SOURCE,
            default=defaults.get(CONF_ALLOCATION_PERCENTAGE_SOURCE),
        ): vol.Any(None, "", _PERCENTAGE_SELECTOR),
        vol.Optional(
            CONF_FIXED_ALLOCATION_PERCENTAGE,
            default=defaults.get(
                CONF_FIXED_ALLOCATION_PERCENTAGE, DEFAULT_FIXED_ALLOCATION_PERCENTAGE
            ),
        ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=1000)),
    }
    return vol.Schema(schema)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the options schema."""
    percentage_mode = defaults.get(
        CONF_ALLOCATION_PERCENTAGE_MODE, PERCENTAGE_MODE_ENTITY
    )
    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
        ): selector.TextSelector(),
        vol.Required(
            CONF_ALLOCATION_PERCENTAGE_MODE,
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
        vol.Optional(
            CONF_ALLOCATION_PERCENTAGE_SOURCE,
            default=defaults.get(CONF_ALLOCATION_PERCENTAGE_SOURCE),
        ): vol.Any(None, "", _PERCENTAGE_SELECTOR),
        vol.Optional(
            CONF_REPORTED_ALLOCATION_SOURCE,
            default=defaults.get(CONF_REPORTED_ALLOCATION_SOURCE),
        ): vol.Any(None, "", _ENERGY_SELECTOR),
        vol.Required(
            CONF_INTERVAL_MINUTES,
            default=defaults.get(CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_INTERVAL_MINUTES, max=MAX_INTERVAL_MINUTES),
        ),
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
            CONF_ALLOCATION_TOLERANCE_KWH,
            default=defaults.get(
                CONF_ALLOCATION_TOLERANCE_KWH, DEFAULT_ALLOCATION_TOLERANCE_KWH
            ),
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
        vol.Required(
            CONF_ALLOCATION_TOLERANCE_PCT,
            default=defaults.get(
                CONF_ALLOCATION_TOLERANCE_PCT, DEFAULT_ALLOCATION_TOLERANCE_PCT
            ),
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1000.0)),
        vol.Required(
            CONF_RECONCILIATION_FAILURE_MODE,
            default=defaults.get(
                CONF_RECONCILIATION_FAILURE_MODE,
                DEFAULT_RECONCILIATION_FAILURE_MODE,
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=RECONCILIATION_MODE_WARN,
                        label="reconciliation_mode_warn",
                    ),
                    selector.SelectOptionDict(
                        value=RECONCILIATION_MODE_SKIP_INTERVAL,
                        label="reconciliation_mode_skip_interval",
                    ),
                ],
                translation_key="reconciliation_failure_mode",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_ALLOW_PERCENTAGE_ABOVE_100,
            default=defaults.get(CONF_ALLOW_PERCENTAGE_ABOVE_100, False),
        ): selector.BooleanSelector(),
    }

    if percentage_mode == PERCENTAGE_MODE_FIXED:
        schema[
            vol.Required(
                CONF_FIXED_ALLOCATION_PERCENTAGE,
                default=defaults.get(
                    CONF_FIXED_ALLOCATION_PERCENTAGE,
                    DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
                ),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=0.01, max=1000))

    return vol.Schema(schema)


def _clean_optional_entity(value: Any) -> str | None:
    """Normalize optional entity selector values."""
    if not value:
        return None
    return str(value)


def _map_validation_error(err: IntervalSourceValidationError) -> str:
    """Map validation codes to config flow error keys."""
    mapping = {
        "source_missing": "source_missing",
        "source_unavailable": "source_unavailable",
        "last_period_missing": "last_period_missing",
        "last_reset_missing": "last_reset_missing",
        "invalid_interval_value": "invalid_interval_value",
        "unsupported_energy_unit": "unsupported_energy_unit",
    }
    return mapping.get(err.code, "source_unavailable")


class EnergySharingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Sharing."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}

    @staticmethod
    async def async_migrate_entry(
        hass: HomeAssistant, config_entry: EnergySharingConfigEntry
    ) -> bool:
        """Migrate old config entries to the current schema."""
        if config_entry.version >= CONFIG_ENTRY_VERSION:
            return True

        data = dict(config_entry.data)
        options = dict(config_entry.options)

        if config_entry.version == 1:
            receiver = data.pop(CONF_GRID_IMPORT_ENTITY, None)
            shared = data.pop(CONF_SHARED_ENERGY_ENTITY, None)
            pct_mode = data.pop(CONF_PERCENTAGE_MODE, PERCENTAGE_MODE_ENTITY)
            pct_entity = data.pop(CONF_PERCENTAGE_ENTITY, None)

            data = {
                CONF_PROVIDER_EXPORT_SOURCE: data.get(CONF_PROVIDER_EXPORT_SOURCE, ""),
                CONF_RECEIVER_IMPORT_SOURCE: receiver or "",
            }
            options = {
                **_default_options(),
                **options,
                CONF_REPORTED_ALLOCATION_SOURCE: shared,
                CONF_ALLOCATION_PERCENTAGE_MODE: pct_mode,
            }
            if pct_entity:
                options[CONF_ALLOCATION_PERCENTAGE_SOURCE] = pct_entity
            if CONF_FIXED_PERCENTAGE in options:
                options[CONF_FIXED_ALLOCATION_PERCENTAGE] = options.pop(
                    CONF_FIXED_PERCENTAGE
                )

        hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            options=options,
            version=CONFIG_ENTRY_VERSION,
        )
        return True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = dict(user_input)
            user_input[CONF_REPORTED_ALLOCATION_SOURCE] = _clean_optional_entity(
                user_input.get(CONF_REPORTED_ALLOCATION_SOURCE)
            )
            user_input[CONF_ALLOCATION_PERCENTAGE_SOURCE] = _clean_optional_entity(
                user_input.get(CONF_ALLOCATION_PERCENTAGE_SOURCE)
            )
            self._user_input = user_input
            errors = await self._async_validate_user_input(user_input)
            if not errors:
                await self.async_set_unique_id(
                    self._build_unique_id(
                        user_input[CONF_PROVIDER_EXPORT_SOURCE],
                        user_input[CONF_RECEIVER_IMPORT_SOURCE],
                    )
                )
                self._abort_if_unique_id_configured()

                options = _default_options()
                options[CONF_ALLOCATION_PERCENTAGE_MODE] = user_input[
                    CONF_ALLOCATION_PERCENTAGE_MODE
                ]
                if user_input[CONF_ALLOCATION_PERCENTAGE_MODE] == PERCENTAGE_MODE_ENTITY:
                    options[CONF_ALLOCATION_PERCENTAGE_SOURCE] = user_input.get(
                        CONF_ALLOCATION_PERCENTAGE_SOURCE
                    )
                else:
                    options[CONF_FIXED_ALLOCATION_PERCENTAGE] = user_input[
                        CONF_FIXED_ALLOCATION_PERCENTAGE
                    ]
                if user_input.get(CONF_REPORTED_ALLOCATION_SOURCE):
                    options[CONF_REPORTED_ALLOCATION_SOURCE] = user_input[
                        CONF_REPORTED_ALLOCATION_SOURCE
                    ]

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=self._build_entry_data(user_input),
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(
                user_input if user_input is not None else self._user_input or None
            ),
            errors=errors,
        )

    @staticmethod
    def _build_unique_id(provider_export: str, receiver_import: str) -> str:
        """Build a stable unique ID for duplicate protection."""
        return f"{provider_export}|{receiver_import}"

    @staticmethod
    def _build_entry_data(user_input: dict[str, Any]) -> dict[str, Any]:
        """Build immutable config entry data."""
        return {
            CONF_PROVIDER_EXPORT_SOURCE: user_input[CONF_PROVIDER_EXPORT_SOURCE],
            CONF_RECEIVER_IMPORT_SOURCE: user_input[CONF_RECEIVER_IMPORT_SOURCE],
        }

    async def _async_validate_user_input(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate user input."""
        errors: dict[str, str] = {}
        entities = {
            CONF_PROVIDER_EXPORT_SOURCE: user_input[CONF_PROVIDER_EXPORT_SOURCE],
            CONF_RECEIVER_IMPORT_SOURCE: user_input[CONF_RECEIVER_IMPORT_SOURCE],
        }
        reported = user_input.get(CONF_REPORTED_ALLOCATION_SOURCE)
        if reported:
            entities[CONF_REPORTED_ALLOCATION_SOURCE] = reported

        unique_entities = set(entities.values())
        if len(unique_entities) != len(entities.values()):
            errors["base"] = "duplicate_sources"
            return errors

        for field, entity_id in (
            ("provider_export", entities[CONF_PROVIDER_EXPORT_SOURCE]),
            ("receiver_import", entities[CONF_RECEIVER_IMPORT_SOURCE]),
        ):
            try:
                await validate_interval_source(self.hass, entity_id)
            except IntervalSourceValidationError as err:
                errors[field] = _map_validation_error(err)

        if reported:
            try:
                await validate_interval_source(self.hass, reported)
            except IntervalSourceValidationError as err:
                errors["reported_allocation"] = _map_validation_error(err)

        mode = user_input[CONF_ALLOCATION_PERCENTAGE_MODE]
        if mode == PERCENTAGE_MODE_ENTITY:
            pct_entity = user_input.get(CONF_ALLOCATION_PERCENTAGE_SOURCE)
            if not pct_entity:
                errors["percentage"] = "percentage_invalid"
            else:
                try:
                    await validate_percentage_source(self.hass, pct_entity)
                except IntervalSourceValidationError:
                    errors["percentage"] = "percentage_invalid"
        elif not user_input.get(CONF_FIXED_ALLOCATION_PERCENTAGE):
            errors["percentage"] = "percentage_invalid"

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
            **self.config_entry.options,
        }

        if user_input is not None:
            user_input = dict(user_input)
            user_input[CONF_REPORTED_ALLOCATION_SOURCE] = _clean_optional_entity(
                user_input.get(CONF_REPORTED_ALLOCATION_SOURCE)
            )
            user_input[CONF_ALLOCATION_PERCENTAGE_SOURCE] = _clean_optional_entity(
                user_input.get(CONF_ALLOCATION_PERCENTAGE_SOURCE)
            )

            mode = user_input[CONF_ALLOCATION_PERCENTAGE_MODE]
            if mode == PERCENTAGE_MODE_FIXED:
                fixed_pct = user_input.get(CONF_FIXED_ALLOCATION_PERCENTAGE)
                if fixed_pct is None or fixed_pct <= 0:
                    errors[CONF_FIXED_ALLOCATION_PERCENTAGE] = "percentage_invalid"
            elif not user_input.get(CONF_ALLOCATION_PERCENTAGE_SOURCE):
                errors["percentage"] = "percentage_invalid"

            reported = user_input.get(CONF_REPORTED_ALLOCATION_SOURCE)
            if reported and reported in {
                self.config_entry.data[CONF_PROVIDER_EXPORT_SOURCE],
                self.config_entry.data[CONF_RECEIVER_IMPORT_SOURCE],
            }:
                errors["reported_allocation"] = "duplicate_sources"

            if not errors:
                new_title = user_input.pop(CONF_NAME)
                options = {**self.config_entry.options, **user_input}
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=new_title,
                )
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults),
            errors=errors,
            description_placeholders={
                "provider_export_source": self.config_entry.data[
                    CONF_PROVIDER_EXPORT_SOURCE
                ],
                "receiver_import_source": self.config_entry.data[
                    CONF_RECEIVER_IMPORT_SOURCE
                ],
            },
        )
