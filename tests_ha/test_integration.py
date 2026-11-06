"""Integrationstest mit echtem HA-Core (pytest-homeassistant-custom-component)."""
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_time_changed, async_mock_service,
)
from homeassistant.util import dt as dt_util

DOMAIN = "smartify_heating"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


CFG = {
    "globals": {"outside_sensor": "sensor.aussen", "cooling_switch": ""},
    "rooms": [
        {"id": "bad", "name": "Bad", "slug": "bad", "climate": "climate.bad",
         "temperature_sensor": "sensor.bad_t", "windows": ["binary_sensor.bad_f1", "binary_sensor.bad_f2"]},
        {"id": "wz", "name": "Wohnzimmer", "climate": "climate.wz", "windows": []},
    ],
}


async def tick(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def _states(hass, bad_t="23.2"):
    attrs = {"hvac_modes": ["heat", "off"], "temperature": 22.0, "current_temperature": 22.0}
    hass.states.async_set("climate.bad", "heat", attrs)
    hass.states.async_set("climate.wz", "heat", attrs)
    hass.states.async_set("sensor.bad_t", bad_t)
    hass.states.async_set("sensor.aussen", "4.0")
    hass.states.async_set("binary_sensor.bad_f1", "off")
    hass.states.async_set("binary_sensor.bad_f2", "off")


async def test_full_flow(hass, hass_ws_client, hass_admin_user, freezer):
    for dep in ("http", "lovelace"):
        from homeassistant.setup import async_setup_component
        assert await async_setup_component(hass, dep, {})
    _states(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="smartify Heizung", data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Nach dem Setup mocken (climate registriert sonst seinen echten Dienst darüber)
    calls = async_mock_service(hass, "climate", "set_hvac_mode")
    assert hass.states.get("select.heizung_modus").state == "auto"

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "smartify_heating/config/save", "config": CFG})
    res = await ws.receive_json()
    assert res["success"], res
    await hass.async_block_till_done()
    ents = res["result"]["entities"]
    assert ents["rooms"]["bad"]["recommendation"] == "sensor.bad_fenster_empfehlung"
    assert ents["rooms"]["wz"]["recommendation"] is None  # ohne Kontakt keine Empfehlung
    assert hass.states.get("select.wohnzimmer_heizmodus").state == "global"

    # Öffnen-Empfehlung sofort nach Start (23,2 >= 22 + 1, außen 4)
    await tick(hass, freezer, 20)
    st = hass.states.get("sensor.bad_fenster_empfehlung")
    assert st.state == "oeffnen", st
    assert st.attributes["grund"] == "zu_warm"
    assert hass.states.get("sensor.fenster_empfehlung_gesamt").state == "oeffnen"

    # Zweiter Kontakt öffnet -> Raum offen; Fenster offen im Gap -> keine_aktion
    hass.states.async_set("binary_sensor.bad_f2", "on")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bad_fenster_offen").state == "on"
    assert hass.states.get("sensor.bad_fenster_empfehlung").state == "keine_aktion"

    # Fensterabschaltung nach 60 s
    n = len(calls)
    for _ in range(5):
        await tick(hass, freezer, 15)
    assert any(c.data == {"entity_id": "climate.bad", "hvac_mode": "off"} for c in calls[n:]), calls
    hass.states.async_set("climate.bad", "off", {"hvac_modes": ["heat", "off"], "temperature": 22.0})

    # Raum kühlt ab -> schließen; Kontakt zu -> nach 30 s wieder heat
    hass.states.async_set("sensor.bad_t", "22.2")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bad_fenster_empfehlung").state == "schliessen"
    hass.states.async_set("binary_sensor.bad_f2", "off")
    await hass.async_block_till_done()
    n = len(calls)
    for _ in range(3):
        await tick(hass, freezer, 15)
    assert any(c.data == {"entity_id": "climate.bad", "hvac_mode": "heat"} for c in calls[n:]), calls

    # Global Aus -> alle Thermostate aus
    hass.states.async_set("climate.bad", "heat", {"hvac_modes": ["heat", "off"], "temperature": 22.0})
    n = len(calls)
    await hass.services.async_call("select", "select_option",
                                   {"entity_id": "select.heizung_modus", "option": "off"}, blocking=True)
    await hass.async_block_till_done()
    offs = {c.data["entity_id"] for c in calls[n:] if c.data["hvac_mode"] == "off"}
    assert offs == {"climate.bad", "climate.wz"}

    # Raum entfernen -> Entitäten weg (neue Verbindung, freezer hat die alte gealtert)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 2, "type": "smartify_heating/config/save", "config": {"rooms": CFG["rooms"][:1]}})
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get("select.wohnzimmer_heizmodus") is None

    # Ressource registriert
    await ws.send_json({"id": 3, "type": "lovelace/resources"})
    urls = [r["url"] for r in (await ws.receive_json())["result"]]
    assert any(u.startswith("/smartify_heating/smartify-heating-card.js?v=") for u in urls), urls
