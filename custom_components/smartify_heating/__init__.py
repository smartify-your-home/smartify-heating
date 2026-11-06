"""smartify Heizung: Raum-Modi, Fensterabschaltung, Fensterempfehlung und Card.

Die Integration liefert smartify-heating-card.js aus und registriert die
Lovelace-Ressource automatisch (wie smartify-flow-card).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, RESOURCE_PATH
from .controller import HeatingController

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_FILE = Path(__file__).parent / "frontend" / "smartify-heating-card.js"
PLATFORMS = ["select", "sensor", "binary_sensor"]


def _card_version() -> str:
    with (Path(__file__).parent / "manifest.json").open(encoding="utf-8") as file:
        return json.load(file)["version"]


def _is_own_resource(url: str) -> bool:
    """Match only our known paths; do not touch other cards' resources."""
    return url.split("?", 1)[0] in {RESOURCE_PATH}


async def _async_register_resource(hass: HomeAssistant, version: str) -> None:
    """Idempotently install or update our module resource in storage mode."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        _LOGGER.warning("Lovelace is unavailable; could not register Heating Card")
        return

    mode = getattr(lovelace, "resource_mode", None)
    resources = getattr(lovelace, "resources", None)
    if isinstance(lovelace, dict):
        mode = lovelace.get("resource_mode", mode)
        resources = lovelace.get("resources", resources)

    if mode == "yaml" or not isinstance(resources, ResourceStorageCollection):
        _LOGGER.warning(
            "Lovelace resources use YAML mode. Add this module manually "
            "to lovelace.resources: %s?v=%s (type: module)",
            RESOURCE_PATH,
            version,
        )
        return

    # REQUIRED: resource storage can be lazy-loaded. Calling async_items() or
    # async_create_item() before loading may overwrite existing resources.
    # async_get_info() ensures the storage is loaded on supported HA versions.
    await resources.async_get_info()

    desired = f"{RESOURCE_PATH}?v={version}"
    matches = [
        item
        for item in resources.async_items()
        if _is_own_resource(str(item.get("url", "")))
    ]

    # Prefer our current URL; otherwise migrate a single legacy /local/ entry.
    primary = next(
        (item for item in matches if str(item.get("url", "")).split("?", 1)[0] == RESOURCE_PATH),
        matches[0] if matches else None,
    )
    if primary is None:
        await resources.async_create_item({"res_type": "module", "url": desired})
        _LOGGER.info("Registered Smartify Heating Card resource %s", desired)
        return

    if primary.get("url") != desired or primary.get("res_type") != "module":
        await resources.async_update_item(
            primary["id"], {"res_type": "module", "url": desired}
        )
        _LOGGER.info("Updated Smartify Heating Card resource to %s", desired)

    # Clean up duplicate known Smartify entries, not unrelated resources.
    for item in matches:
        if item["id"] != primary["id"]:
            await resources.async_delete_item(item["id"])
            _LOGGER.info("Removed duplicate Heating Card resource %s", item["url"])


def _entity_map(hass: HomeAssistant, ctrl: HeatingController) -> dict:
    """Entity-IDs der Integration für die Card (auch nach Umbenennung korrekt)."""
    reg = er.async_get(hass)

    def eid(platform: str, rid: str, key: str):
        return reg.async_get_entity_id(platform, DOMAIN, f"{DOMAIN}_{rid}_{key}")

    rooms = {
        r["id"]: {
            "mode": eid("select", r["id"], "mode"),
            "recommendation": eid("sensor", r["id"], "recommendation"),
            "window": eid("binary_sensor", r["id"], "window"),
        }
        for r in ctrl.data["rooms"]
    }
    return {
        "global_mode": eid("select", "global", "mode"),
        "total": eid("sensor", "global", "recommendation"),
        "rooms": rooms,
    }


@websocket_api.websocket_command({vol.Required("type"): "smartify_heating/config/get"})
@callback
def ws_get(hass: HomeAssistant, connection, msg) -> None:
    ctrl: HeatingController | None = hass.data.get(DOMAIN, {}).get("controller")
    if ctrl is None:
        connection.send_error(msg["id"], "not_loaded", "smartify Heizung ist nicht geladen")
        return
    connection.send_result(msg["id"], {
        "config": ctrl.public_config(),
        "entities": _entity_map(hass, ctrl),
        "can_edit": bool(connection.user and connection.user.is_admin),
        "version": _card_version(),
    })


@websocket_api.websocket_command({
    vol.Required("type"): "smartify_heating/config/save",
    vol.Required("config"): dict,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save(hass: HomeAssistant, connection, msg) -> None:
    state = hass.data.get(DOMAIN, {})
    ctrl: HeatingController | None = state.get("controller")
    entry_id = state.get("entry_id")
    if ctrl is None or entry_id is None:
        connection.send_error(msg["id"], "not_loaded", "smartify Heizung ist nicht geladen")
        return
    await ctrl.async_replace_config(msg["config"])
    # Reload erzeugt/entfernt Entitäten passend zur neuen Raumliste
    await hass.config_entries.async_reload(entry_id)
    new_ctrl = hass.data[DOMAIN]["controller"]
    connection.send_result(msg["id"], {
        "config": new_ctrl.public_config(),
        "entities": _entity_map(hass, new_ctrl),
    })


def _remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry, ctrl: HeatingController) -> None:
    valid = {f"{DOMAIN}_global_mode", f"{DOMAIN}_global_recommendation"}
    for r in ctrl.data["rooms"]:
        valid.add(f"{DOMAIN}_{r['id']}_mode")
        if r["windows"]:
            valid.update({f"{DOMAIN}_{r['id']}_recommendation", f"{DOMAIN}_{r['id']}_window"})
    reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
        if ent.unique_id not in valid:
            reg.async_remove(ent.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not CARD_FILE.is_file():
        _LOGGER.error("Card-JavaScript fehlt: %s", CARD_FILE)
        return False
    version = _card_version()
    state = hass.data.setdefault(DOMAIN, {})
    if not state.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(RESOURCE_PATH, str(CARD_FILE), False)]
        )
        websocket_api.async_register_command(hass, ws_get)
        websocket_api.async_register_command(hass, ws_save)
        state["static_registered"] = True

    ctrl = HeatingController(hass)
    await ctrl.async_load()
    state["controller"] = ctrl
    state["entry_id"] = entry.entry_id
    _remove_stale_entities(hass, entry, ctrl)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await ctrl.async_start()

    try:
        await _async_register_resource(hass, version)
    except Exception:  # noqa: BLE001 – HA bleibt lauffähig
        _LOGGER.exception("Ressource konnte nicht registriert werden: %s?v=%s", RESOURCE_PATH, version)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    state = hass.data.get(DOMAIN, {})
    ctrl = state.pop("controller", None)
    if ctrl is not None:
        await ctrl.async_stop()
    return ok
