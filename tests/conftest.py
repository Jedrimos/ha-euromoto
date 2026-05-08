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
    "homeassistant.helpers",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.data_entry_flow",
    "voluptuous",
    "pdfplumber",
]

for _name in _HA_STUBS:
    _stub_module(_name)

# Concrete attributes that must be real objects (used in class definitions)
_ha_const = sys.modules["homeassistant.const"]
_ha_const.Platform = types.SimpleNamespace(SENSOR="sensor")  # type: ignore[assignment]

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

_ha_config = sys.modules["homeassistant.config_entries"]
_ha_config.ConfigEntry = object  # type: ignore[assignment]
_ha_config.ConfigFlow = object  # type: ignore[assignment]
_ha_config.OptionsFlow = object  # type: ignore[assignment]

_ha_flow = sys.modules["homeassistant.data_entry_flow"]
_ha_flow.FlowResult = dict  # type: ignore[assignment]
