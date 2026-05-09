"""Weather platform – current conditions at the next race track."""
from __future__ import annotations

from homeassistant.components.weather import WeatherEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EuroMotoCoordinator

_DEVICE_INFO = DeviceInfo(identifiers={(DOMAIN, "euromoto")}, name="EuroMoto")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EuroMotoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TrackWeatherEntity(coordinator)], update_before_add=True)


class TrackWeatherEntity(CoordinatorEntity[EuroMotoCoordinator], WeatherEntity):
    _attr_has_entity_name = True
    _attr_name = "Track Weather"
    _attr_unique_id = "euromoto_track_weather"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_device_info = _DEVICE_INFO

    def __init__(self, coordinator: EuroMotoCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def _wx(self) -> dict:
        return self.coordinator.data.track_weather

    @property
    def available(self) -> bool:
        return bool(self._wx)

    @property
    def condition(self) -> str | None:
        return self._wx.get("condition")

    @property
    def native_temperature(self) -> float | None:
        return self._wx.get("temperature")

    @property
    def humidity(self) -> float | None:
        return self._wx.get("humidity")

    @property
    def native_wind_speed(self) -> float | None:
        return self._wx.get("wind_speed")

    @property
    def wind_bearing(self) -> float | None:
        return self._wx.get("wind_bearing")

    @property
    def native_pressure(self) -> float | None:
        return self._wx.get("pressure")

    @property
    def native_precipitation(self) -> float | None:
        return self._wx.get("precipitation")

    @property
    def extra_state_attributes(self) -> dict:
        wx = self._wx
        if not wx:
            return {}
        return {
            "track_name": wx.get("track_name"),
            "latitude": wx.get("latitude"),
            "longitude": wx.get("longitude"),
            "wmo_code": wx.get("wmo_code"),
        }
