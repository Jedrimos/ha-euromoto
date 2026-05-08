"""Config flow for EURO MOTO / IDM."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_CLASSES,
    CONF_FAVORITE_RIDER,
    CLASS_SUPERBIKE,
    CLASS_SUPERSPORT,
    CLASS_SPORTBIKE,
    ALL_CLASSES,
)

_DEFAULT_CLASSES = [CLASS_SUPERBIKE, CLASS_SUPERSPORT]


class EuroMotoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            selected = [cls for cls in ALL_CLASSES if user_input.get(cls, False)]
            return self.async_create_entry(
                title="EURO MOTO / IDM",
                data={
                    CONF_CLASSES: selected,
                    CONF_FAVORITE_RIDER: user_input.get(CONF_FAVORITE_RIDER) or None,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(CLASS_SUPERBIKE, default=True): bool,
                vol.Optional(CLASS_SUPERSPORT, default=True): bool,
                vol.Optional(CLASS_SPORTBIKE, default=False): bool,
                vol.Optional(CONF_FAVORITE_RIDER): vol.Any(None, vol.Coerce(int)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EuroMotoOptionsFlow(config_entry)


class EuroMotoOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        current_classes: list[str] = self._entry.options.get(
            CONF_CLASSES, self._entry.data.get(CONF_CLASSES, _DEFAULT_CLASSES)
        )
        current_rider: int | None = self._entry.options.get(
            CONF_FAVORITE_RIDER, self._entry.data.get(CONF_FAVORITE_RIDER)
        )

        if user_input is not None:
            selected = [cls for cls in ALL_CLASSES if user_input.get(cls, False)]
            return self.async_create_entry(
                title="",
                data={
                    CONF_CLASSES: selected,
                    CONF_FAVORITE_RIDER: user_input.get(CONF_FAVORITE_RIDER) or None,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(CLASS_SUPERBIKE, default=CLASS_SUPERBIKE in current_classes): bool,
                vol.Optional(CLASS_SUPERSPORT, default=CLASS_SUPERSPORT in current_classes): bool,
                vol.Optional(CLASS_SPORTBIKE, default=CLASS_SPORTBIKE in current_classes): bool,
                vol.Optional(CONF_FAVORITE_RIDER, default=current_rider): vol.Any(
                    None, vol.Coerce(int)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
