"""Auto-register the EuroMoto Lovelace dashboard on integration setup."""
from __future__ import annotations

import json
import logging
import pathlib
import uuid
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_DASHBOARD_URL_PATH = "euromoto"
_STORAGE_KEY = f"lovelace.{_DASHBOARD_URL_PATH}"
_STORAGE_VERSION = 1

_YAML_PATH = pathlib.Path(__file__).parent / "lovelace" / "dashboard.yaml"

# Dashboard metadata written to both live collection and .storage/lovelace.dashboards
_DASH_META: dict[str, Any] = {
    "url_path": _DASHBOARD_URL_PATH,
    "title": "EuroMoto",
    "icon": "mdi:racing-helmet",
    "show_in_sidebar": True,
    "require_admin": False,
}


def _load_config() -> dict:
    raw = _YAML_PATH.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.startswith("#")]
    return yaml.safe_load("\n".join(lines))


async def _write_dashboard_config(hass: HomeAssistant) -> None:
    """Overwrite Lovelace storage with our YAML config."""
    try:
        store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        config = await hass.async_add_executor_job(_load_config)
        await store.async_save({"config": config})
        _LOGGER.debug(
            "EuroMoto: wrote dashboard config to storage (%d views)",
            len(config.get("views", [])),
        )
    except Exception as exc:
        _LOGGER.debug("EuroMoto: could not write dashboard YAML to storage: %s", exc)


def _write_dashboards_storage_sync(config_dir: str) -> bool:
    """Add our entry to .storage/lovelace.dashboards (runs in executor)."""
    storage_path = pathlib.Path(config_dir) / ".storage" / "lovelace.dashboards"
    try:
        if storage_path.exists():
            raw = json.loads(storage_path.read_text())
        else:
            raw = {
                "version": 1,
                "minor_version": 1,
                "key": "lovelace.dashboards",
                "data": {"items": []},
            }

        items: list[dict] = raw.get("data", {}).get("items", [])
        if any(item.get("url_path") == _DASHBOARD_URL_PATH for item in items):
            return False  # already present

        items.append({"id": str(uuid.uuid4()), **_DASH_META})
        raw.setdefault("data", {})["items"] = items
        storage_path.write_text(json.dumps(raw, indent=2))
        return True
    except Exception as exc:
        _LOGGER.debug("EuroMoto: could not write lovelace.dashboards storage: %s", exc)
        return False


async def _ensure_in_dashboards_storage(hass: HomeAssistant) -> None:
    """Write dashboard entry to .storage/lovelace.dashboards for next-restart pickup."""
    added = await hass.async_add_executor_job(
        _write_dashboards_storage_sync, hass.config.config_dir
    )
    if added:
        _LOGGER.debug(
            "EuroMoto: added to lovelace.dashboards storage "
            "(effective on next HA restart if live registration fails)"
        )


async def _register_live(hass: HomeAssistant) -> bool:
    """Try to register the dashboard in the running HA session. Returns True on success."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return False

    # hass.data["lovelace"] may be a LovelaceData dataclass or a plain dict
    if isinstance(lovelace, dict):
        dashboards = lovelace.get("dashboards")
    else:
        dashboards = getattr(lovelace, "dashboards", None)

    if dashboards is None:
        return False

    # ── HA 2025+: dashboards is a plain dict {url_path: LovelaceDashboard} ─────
    if isinstance(dashboards, dict):
        if _DASHBOARD_URL_PATH in dashboards:
            return True
        try:
            from homeassistant.components.lovelace.dashboard import (
                LovelaceStorageDashboard,
            )

            dash_config = {"id": _DASHBOARD_URL_PATH, "mode": "storage", **_DASH_META}
            dashboard = LovelaceStorageDashboard(hass, _DASHBOARD_URL_PATH, dash_config)
            await dashboard.async_setup()
            dashboards[_DASHBOARD_URL_PATH] = dashboard
            _LOGGER.info(
                "EuroMoto: dashboard registered via LovelaceStorageDashboard at /%s",
                _DASHBOARD_URL_PATH,
            )
            return True
        except Exception as exc:
            _LOGGER.debug("EuroMoto: LovelaceStorageDashboard registration failed: %s", exc)
            return False

    # ── Older HA: dashboards is a StorageCollection ───────────────────────────
    try:
        items = list(dashboards.async_items())
        existing = {
            (i.get("url_path") if isinstance(i, dict) else getattr(i, "url_path", None))
            for i in items
        }
        if _DASHBOARD_URL_PATH in existing:
            return True

        for method_name in ("async_create_item", "async_create"):
            method = getattr(dashboards, method_name, None)
            if method is not None:
                await method(_DASH_META)
                _LOGGER.info(
                    "EuroMoto: dashboard registered via %s at /%s",
                    method_name,
                    _DASHBOARD_URL_PATH,
                )
                return True

        _LOGGER.debug(
            "EuroMoto: no known create method on dashboards collection (methods=%s)",
            [a for a in dir(dashboards) if "create" in a.lower()],
        )
        return False
    except Exception as exc:
        _LOGGER.debug("EuroMoto: StorageCollection registration failed: %s", exc)
        return False


async def async_register_dashboard(hass: HomeAssistant) -> None:
    """Create the EuroMoto Lovelace dashboard (sidebar entry + config)."""
    try:
        # 1. Remove any legacy panel that bypasses the Lovelace API ("Neuer Abschnitt" bug).
        try:
            from homeassistant.components import frontend as _fe
            _fe.async_remove_panel(hass, _DASHBOARD_URL_PATH)
        except Exception:
            pass

        # 2. Write dashboard config to .storage/lovelace.euromoto (our YAML).
        await _write_dashboard_config(hass)

        # 3. Write entry to .storage/lovelace.dashboards so HA loads it on next restart.
        await _ensure_in_dashboards_storage(hass)

        # 4. Try live registration for the current session (no restart needed).
        if await _register_live(hass):
            return

        # 5. Retry once after HA finishes booting (setup_entry runs early).
        _LOGGER.debug("EuroMoto: lovelace not ready yet – retrying after homeassistant_started")

        async def _retry_on_start(_event: Any) -> None:
            if not await _register_live(hass):
                _LOGGER.debug(
                    "EuroMoto: live dashboard registration not possible in this session; "
                    "storage already written – dashboard will appear after next HA restart."
                )

        hass.bus.async_listen_once("homeassistant_started", _retry_on_start)

    except Exception as exc:
        _LOGGER.debug("EuroMoto: dashboard setup failed (non-fatal): %s", exc)


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the EuroMoto dashboard when the integration is deleted."""
    try:
        lovelace = hass.data.get("lovelace")
        if lovelace is not None:
            if isinstance(lovelace, dict):
                dashboards = lovelace.get("dashboards")
            else:
                dashboards = getattr(lovelace, "dashboards", None)

            if dashboards is not None:
                if isinstance(dashboards, dict):
                    dashboard = dashboards.pop(_DASHBOARD_URL_PATH, None)
                    if dashboard is not None:
                        try:
                            await dashboard.async_teardown()
                        except Exception:
                            pass
                else:
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
                                for mn in ("async_delete_item", "async_delete"):
                                    method = getattr(dashboards, mn, None)
                                    if method is not None:
                                        await method(item_id)
                                        break
                                break
                    except Exception as exc:
                        _LOGGER.debug("EuroMoto: collection removal failed: %s", exc)

        await Store(hass, _STORAGE_VERSION, _STORAGE_KEY).async_remove()

        try:
            from homeassistant.components import frontend as _fe
            _fe.async_remove_panel(hass, _DASHBOARD_URL_PATH)
        except Exception:
            pass

    except Exception as exc:
        _LOGGER.debug("EuroMoto: dashboard removal failed (non-fatal): %s", exc)
