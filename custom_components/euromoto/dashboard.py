"""Auto-register the EuroMoto Lovelace dashboard on integration setup."""
from __future__ import annotations

import logging
import pathlib
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_DASHBOARD_URL_PATH = "euromoto"
_STORAGE_KEY = f"lovelace.{_DASHBOARD_URL_PATH}"
_STORAGE_VERSION = 1

_YAML_PATH = pathlib.Path(__file__).parent / "lovelace" / "dashboard.yaml"


def _load_config() -> dict:
    raw = _YAML_PATH.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.startswith("#")]
    return yaml.safe_load("\n".join(lines))


async def async_register_dashboard(hass: HomeAssistant) -> None:
    """Create the EuroMoto Lovelace dashboard (sidebar entry + config)."""
    try:
        # 1. Always write YAML config to storage so updates take effect immediately.
        store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        try:
            config = await hass.async_add_executor_job(_load_config)
            await store.async_save({"config": config})
            _LOGGER.debug(
                "EuroMoto: wrote dashboard config to storage (%d views)",
                len(config.get("views", [])),
            )
        except Exception as exc:
            _LOGGER.warning("EuroMoto: could not write dashboard YAML to storage: %s", exc)

        # 2. Remove any legacy frontend panel left over from earlier installs.
        #    async_register_built_in_panel bypasses the Lovelace dashboard API so HA
        #    cannot find our config and instead creates an empty placeholder ("Neuer Abschnitt").
        try:
            from homeassistant.components import frontend as _fe
            _fe.async_remove_panel(hass, _DASHBOARD_URL_PATH)
        except Exception:
            pass

        # 3. Register via DashboardsCollection – the proper Lovelace API.
        #    This is identical to Settings → Dashboards → Add Dashboard.
        #    It registers both the sidebar entry AND wires up config serving from storage.
        if await _register_via_collection(hass):
            return

        # 4. Lovelace not fully initialised yet (called during async_setup_entry before
        #    HA has finished booting).  Retry once after homeassistant_started.
        _LOGGER.debug("EuroMoto: lovelace not ready yet – retry scheduled after HA start")

        async def _retry_on_start(_event: Any) -> None:
            if not await _register_via_collection(hass):
                _LOGGER.warning(
                    "EuroMoto: dashboard registration still failed after HA start; "
                    "it may appear after the next HA restart."
                )

        hass.bus.async_listen_once("homeassistant_started", _retry_on_start)

    except Exception as exc:
        _LOGGER.warning("EuroMoto: dashboard registration failed (non-fatal): %s", exc)


async def _register_via_collection(hass: HomeAssistant) -> bool:
    """Register dashboard in hass.data['lovelace'].dashboards. Returns True on success."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return False

    # hass.data["lovelace"].dashboards is a DashboardsCollection (StorageCollection)
    dashboards = getattr(lovelace, "dashboards", None)
    if dashboards is None:
        return False

    try:
        items = list(dashboards.async_items())
        existing_paths: set[str | None] = set()
        for item in items:
            if isinstance(item, dict):
                existing_paths.add(item.get("url_path"))
            else:
                existing_paths.add(getattr(item, "url_path", None))

        if _DASHBOARD_URL_PATH not in existing_paths:
            dash_data: dict[str, Any] = {
                "url_path": _DASHBOARD_URL_PATH,
                "title": "EuroMoto",
                "icon": "mdi:racing-helmet",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            }
            # HA 2024+ renamed async_create → async_create_item
            created = False
            for method_name in ("async_create_item", "async_create"):
                method = getattr(dashboards, method_name, None)
                if method is not None:
                    await method(dash_data)
                    created = True
                    _LOGGER.info(
                        "EuroMoto: dashboard registered via %s at /%s",
                        method_name,
                        _DASHBOARD_URL_PATH,
                    )
                    break
            if not created:
                _LOGGER.warning("EuroMoto: DashboardsCollection has no known create method")
                return False
        else:
            _LOGGER.debug(
                "EuroMoto: dashboard already in collection at /%s", _DASHBOARD_URL_PATH
            )

        return True

    except Exception as exc:
        _LOGGER.debug("EuroMoto: DashboardsCollection registration failed: %s", exc)
        return False


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the EuroMoto dashboard when the integration is deleted."""
    try:
        # Remove from DashboardsCollection
        lovelace = hass.data.get("lovelace")
        if lovelace is not None:
            dashboards = getattr(lovelace, "dashboards", None)
            if dashboards is not None:
                try:
                    for item in list(dashboards.async_items()):
                        url_path = (
                            item.get("url_path")
                            if isinstance(item, dict)
                            else getattr(item, "url_path", None)
                        )
                        item_id = (
                            item.get("id")
                            if isinstance(item, dict)
                            else getattr(item, "id", None)
                        )
                        if url_path == _DASHBOARD_URL_PATH and item_id:
                            for method_name in ("async_delete_item", "async_delete"):
                                method = getattr(dashboards, method_name, None)
                                if method is not None:
                                    await method(item_id)
                                    break
                            break
                except Exception as exc:
                    _LOGGER.debug("EuroMoto: collection removal failed: %s", exc)

        # Remove config from storage
        await Store(hass, _STORAGE_VERSION, _STORAGE_KEY).async_remove()

        # Clean up any legacy built-in panel
        try:
            from homeassistant.components import frontend as _fe
            _fe.async_remove_panel(hass, _DASHBOARD_URL_PATH)
        except Exception:
            pass

    except Exception as exc:
        _LOGGER.debug("EuroMoto: dashboard removal failed (non-fatal): %s", exc)
