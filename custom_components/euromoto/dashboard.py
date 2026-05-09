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
    lines = [ln for ln in raw.splitlines() if not ln.startswith("#")]
    return yaml.safe_load("\n".join(lines))


async def async_register_dashboard(hass: HomeAssistant) -> None:
    """Create the EuroMoto sidebar dashboard (appears immediately, no restart needed)."""
    try:
        # 1. Write Lovelace card config to storage (the panel reads this)
        store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        existing = await store.async_load()
        if not existing:
            try:
                config = await hass.async_add_executor_job(_load_config)
                await store.async_save({"config": config})
                _LOGGER.debug("EuroMoto: wrote dashboard config to storage")
            except Exception as exc:
                _LOGGER.warning("EuroMoto: could not load dashboard YAML: %s", exc)

        # 2. Register the panel via the frontend API (works immediately, no restart)
        try:
            from homeassistant.components import frontend as _fe
            _fe.async_register_built_in_panel(
                hass,
                component_name="lovelace",
                sidebar_title="EuroMoto",
                sidebar_icon="mdi:racing-helmet",
                frontend_url_path=_DASHBOARD_URL_PATH,
                config={"mode": "storage"},
                require_admin=False,
            )
            _LOGGER.info("EuroMoto: dashboard panel registered at /%s", _DASHBOARD_URL_PATH)
            return
        except Exception as exc:
            _LOGGER.debug("EuroMoto: frontend panel registration failed: %s – trying collection API", exc)

        # 3. Fallback: live DashboardsCollection API
        lovelace = hass.data.get("lovelace")
        collection = _find_collection(lovelace)
        if collection is not None:
            try:
                existing_paths = {d.get("url_path") for d in collection.async_items()}
                if _DASHBOARD_URL_PATH not in existing_paths:
                    await collection.async_create({
                        "require_admin": False,
                        "url_path": _DASHBOARD_URL_PATH,
                        "show_in_sidebar": True,
                        "mode": "storage",
                        "icon": "mdi:racing-helmet",
                        "title": "EuroMoto",
                    })
                    _LOGGER.info("EuroMoto: dashboard registered via collection at /%s", _DASHBOARD_URL_PATH)
                return
            except Exception as exc:
                _LOGGER.debug("EuroMoto: collection API failed: %s – trying storage fallback", exc)

        # 4. Last resort: write to lovelace_dashboards storage (requires HA restart)
        await _register_via_storage(hass)

    except Exception as exc:
        _LOGGER.warning("EuroMoto: dashboard registration failed (non-fatal): %s", exc)


def _find_collection(lovelace: object) -> object | None:
    if lovelace is None:
        return None
    for attr in ("dashboards", "storage", "dashboard_storage"):
        candidate = getattr(lovelace, attr, None)
        if candidate is not None and hasattr(candidate, "async_create"):
            return candidate
    if hasattr(lovelace, "get"):
        for key in ("dashboards", "storage"):
            candidate = lovelace.get(key)
            if candidate is not None and hasattr(candidate, "async_create"):
                return candidate
    return None


async def _register_via_storage(hass: HomeAssistant) -> None:
    """Write dashboard metadata to lovelace_dashboards storage (requires restart)."""
    import uuid
    meta_store: Store = Store(hass, _STORAGE_VERSION, "lovelace_dashboards")
    data = await meta_store.async_load() or {"items": []}
    items: list[dict] = data.get("items", [])
    if any(item.get("url_path") == _DASHBOARD_URL_PATH for item in items):
        return
    items.append({
        "id": str(uuid.uuid4()),
        "url_path": _DASHBOARD_URL_PATH,
        "title": "EuroMoto",
        "icon": "mdi:racing-helmet",
        "show_in_sidebar": True,
        "require_admin": False,
        "mode": "storage",
    })
    data["items"] = items
    await meta_store.async_save(data)
    _LOGGER.warning(
        "EuroMoto: dashboard written to storage – will appear after HA restart "
        "(frontend panel API and collection API both unavailable)"
    )


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the EuroMoto dashboard when the integration is deleted."""
    try:
        try:
            from homeassistant.components import frontend as _fe
            _fe.async_remove_panel(hass, _DASHBOARD_URL_PATH)
        except Exception:
            pass
        lovelace = hass.data.get("lovelace")
        collection = _find_collection(lovelace)
        if collection is not None:
            for item in list(collection.async_items()):
                if item.get("url_path") == _DASHBOARD_URL_PATH:
                    await collection.async_delete(item["id"])
                    break
        await Store(hass, _STORAGE_VERSION, _STORAGE_KEY).async_remove()
        meta_store: Store = Store(hass, _STORAGE_VERSION, "lovelace_dashboards")
        data = await meta_store.async_load() or {"items": []}
        data["items"] = [i for i in data.get("items", []) if i.get("url_path") != _DASHBOARD_URL_PATH]
        await meta_store.async_save(data)
    except Exception as exc:
        _LOGGER.debug("EuroMoto: dashboard removal failed (non-fatal): %s", exc)
