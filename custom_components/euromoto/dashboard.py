"""Auto-register the EuroMoto Lovelace dashboard on integration setup."""
from __future__ import annotations

import logging
import pathlib

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
    # Strip the comment header before parsing
    lines = [l for l in raw.splitlines() if not l.startswith("#")]
    return yaml.safe_load("\n".join(lines))


async def async_register_dashboard(hass: HomeAssistant) -> None:
    """Create the EuroMoto sidebar dashboard (storage mode) if not already present."""
    try:
        # --- 1. Write initial Lovelace config to storage (skip if user already customised) ---
        store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        existing = await store.async_load()
        if not existing:
            try:
                config = await hass.async_add_executor_job(_load_config)
                await store.async_save({"config": config})
                _LOGGER.debug("EuroMoto: wrote initial dashboard config to storage")
            except Exception as exc:
                _LOGGER.warning("EuroMoto: could not load dashboard YAML: %s", exc)

        # --- 2. Register the dashboard in the Lovelace dashboards collection ---
        lovelace = hass.data.get("lovelace")
        if not lovelace:
            _LOGGER.debug("EuroMoto: lovelace not available yet, skipping dashboard registration")
            return

        dashboards = lovelace.get("dashboards")
        if not dashboards:
            return

        # Idempotent: don't create if the URL path already exists
        try:
            if any(d.get("url_path") == _DASHBOARD_URL_PATH for d in dashboards.async_items()):
                return
        except Exception:
            pass

        await dashboards.async_create({
            "require_admin": False,
            "url_path": _DASHBOARD_URL_PATH,
            "show_in_sidebar": True,
            "mode": "storage",
            "icon": "mdi:racing-helmet",
            "title": "EuroMoto",
        })
        _LOGGER.info("EuroMoto: dashboard registered at /%s", _DASHBOARD_URL_PATH)

    except Exception as exc:
        # Never block integration setup because of dashboard issues
        _LOGGER.warning("EuroMoto: dashboard registration failed (non-fatal): %s", exc)


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the EuroMoto dashboard when the integration is deleted."""
    try:
        lovelace = hass.data.get("lovelace")
        if lovelace:
            dashboards = lovelace.get("dashboards")
            if dashboards:
                for item in list(dashboards.async_items()):
                    if item.get("url_path") == _DASHBOARD_URL_PATH:
                        await dashboards.async_delete(item["id"])
                        break
        store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        await store.async_remove()
    except Exception as exc:
        _LOGGER.debug("EuroMoto: dashboard removal failed (non-fatal): %s", exc)
