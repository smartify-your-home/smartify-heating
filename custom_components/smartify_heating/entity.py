"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME, SIGNAL_UPDATE
from .controller import HeatingController


class SmartifyHeatingEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, ctrl: HeatingController, room: dict | None, key: str, platform: str, object_id: str) -> None:
        self.ctrl = ctrl
        self.room = room
        rid = room["id"] if room else "global"
        self._attr_unique_id = f"{DOMAIN}_{rid}_{key}"
        self.entity_id = f"{platform}.{object_id}"
        if room:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, rid)}, name=f"Heizung {room['name']}",
                manufacturer="smartify", model="Raum", via_device=(DOMAIN, "global"),
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "global")}, name=NAME, manufacturer="smartify", model="Heizung",
            )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state))
