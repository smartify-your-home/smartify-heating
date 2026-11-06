"""Mode selects: global and per room."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, GLOBAL_MODES, ROOM_MODES
from .entity import SmartifyHeatingEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    ctrl = hass.data[DOMAIN]["controller"]
    entities: list[SelectEntity] = [GlobalModeSelect(ctrl)]
    # Räume ohne Heizung (kein Thermostat) haben nur die Fensterempfehlung
    entities += [RoomModeSelect(ctrl, room) for room in ctrl.data["rooms"] if room["climate"]]
    add(entities)


class GlobalModeSelect(SmartifyHeatingEntity, SelectEntity):
    _attr_icon = "mdi:radiator"
    _attr_translation_key = "global_mode"
    _attr_options = GLOBAL_MODES

    def __init__(self, ctrl) -> None:
        super().__init__(ctrl, None, "mode", "select", "heizung_modus")
        self._attr_name = "Heizung Modus"

    @property
    def current_option(self) -> str:
        return self.ctrl.data["global_mode"]

    async def async_select_option(self, option: str) -> None:
        await self.ctrl.async_set_global_mode(option)


class RoomModeSelect(SmartifyHeatingEntity, SelectEntity):
    _attr_icon = "mdi:thermostat"
    _attr_translation_key = "room_mode"
    _attr_options = ROOM_MODES

    def __init__(self, ctrl, room) -> None:
        super().__init__(ctrl, room, "mode", "select", f"{room['slug']}_heizmodus")
        self._attr_name = f"{room['name']} Heizmodus"

    @property
    def current_option(self) -> str:
        return self.ctrl.room_mode(self.room["id"])

    @property
    def extra_state_attributes(self) -> dict:
        rid = self.room["id"]
        return {
            "wirksamer_modus": self.ctrl.effective(rid),
            "fensterabschaltung": rid in self.ctrl.data["paused"],
            "raum_id": rid,
        }

    async def async_select_option(self, option: str) -> None:
        await self.ctrl.async_set_room_mode(self.room["id"], option)
