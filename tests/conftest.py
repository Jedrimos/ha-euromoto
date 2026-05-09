"""Stub homeassistant and heavy dependencies so tests run without full installs."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _stub_module(name: str) -> types.ModuleType:
    """Create a real ModuleType stub with a MagicMock as its attribute source."""
    if name in sys.modules:
        return sys.modules[name]  # type: ignore[return-value]
    mod = types.ModuleType(name)
    mod.__path__ = []  # mark as package
    # Allow attribute access to return MagicMock instances
    _magic = MagicMock()

    class _AttrForwarding(types.ModuleType):
        def __getattr__(self, item: str) -> object:
            return getattr(_magic, item)

    real_mod = _AttrForwarding(name)
    real_mod.__path__ = []
    real_mod.__spec__ = None  # type: ignore[assignment]
    sys.modules[name] = real_mod
    return real_mod


_HA_STUBS = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.calendar",
    "homeassistant.components.weather",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.switch",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.restore_state",
    "homeassistant.data_entry_flow",
    "voluptuous",
    "pdfplumber",
]

for _name in _HA_STUBS:
    _stub_module(_name)

# Concrete attributes that must be real objects (used in class definitions)
_ha_const = sys.modules["homeassistant.const"]
_ha_const.Platform = types.SimpleNamespace(
    SENSOR="sensor", CALENDAR="calendar", WEATHER="weather",
    BINARY_SENSOR="binary_sensor", SWITCH="switch",
)  # type: ignore[assignment]

# UnitOf* constants used by weather.py
for _unit_ns in ("UnitOfTemperature", "UnitOfSpeed", "UnitOfPressure"):
    setattr(_ha_const, _unit_ns, types.SimpleNamespace(
        CELSIUS="°C", KILOMETERS_PER_HOUR="km/h", HPA="hPa",
        FAHRENHEIT="°F", METERS_PER_SECOND="m/s", INHG="inHg",
    ))

from typing import Generic, TypeVar as _TV
_T = _TV("_T")

class _GenericBase(Generic[_T]):
    pass

_ha_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]
_ha_coordinator.DataUpdateCoordinator = _GenericBase  # type: ignore[assignment]
_ha_coordinator.CoordinatorEntity = _GenericBase  # type: ignore[assignment]
_ha_coordinator.UpdateFailed = Exception  # type: ignore[assignment]

_ha_sensor = sys.modules["homeassistant.components.sensor"]
_ha_sensor.SensorEntity = object  # type: ignore[assignment]

_ha_calendar = sys.modules["homeassistant.components.calendar"]
_ha_calendar.CalendarEntity = object  # type: ignore[assignment]

# CalendarEvent as a real dataclass so calendar.py works in tests
import dataclasses as _dc
from datetime import date as _date, datetime as _dt

@_dc.dataclass
class _CalendarEvent:
    start: _date | _dt
    end: _date | _dt
    summary: str
    description: str | None = None
    location: str | None = None

_ha_calendar.CalendarEvent = _CalendarEvent  # type: ignore[assignment]

_ha_weather = sys.modules["homeassistant.components.weather"]
_ha_weather.WeatherEntity = object  # type: ignore[assignment]

_ha_binary = sys.modules["homeassistant.components.binary_sensor"]
_ha_binary.BinarySensorEntity = object  # type: ignore[assignment]
_ha_binary.BinarySensorDeviceClass = types.SimpleNamespace(RUNNING="running")  # type: ignore[assignment]

_ha_switch = sys.modules["homeassistant.components.switch"]
_ha_switch.SwitchEntity = object  # type: ignore[assignment]

_ha_device_registry = sys.modules["homeassistant.helpers.device_registry"]
_ha_device_registry.DeviceInfo = dict  # type: ignore[assignment]

_ha_restore = sys.modules["homeassistant.helpers.restore_state"]
_ha_restore.RestoreEntity = object  # type: ignore[assignment]

_ha_config = sys.modules["homeassistant.config_entries"]
_ha_config.ConfigEntry = object  # type: ignore[assignment]
_ha_config.ConfigFlow = object  # type: ignore[assignment]
_ha_config.OptionsFlow = object  # type: ignore[assignment]

_ha_flow = sys.modules["homeassistant.data_entry_flow"]
_ha_flow.FlowResult = dict  # type: ignore[assignment]
