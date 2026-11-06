"""Constants for smartify Heizung."""

DOMAIN = "smartify_heating"
NAME = "smartify Heizung"
RESOURCE_PATH = "/smartify_heating/smartify-heating-card.js"
STORAGE_KEY = "smartify_heating"
STORAGE_VERSION = 1
SIGNAL_UPDATE = "smartify_heating_update"

# Modi (Optionsschlüssel; Anzeige über Übersetzungen)
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_OFF = "off"
MODE_GLOBAL = "global"
GLOBAL_MODES = [MODE_AUTO, MODE_MANUAL, MODE_OFF]
ROOM_MODES = [MODE_GLOBAL, MODE_AUTO, MODE_MANUAL, MODE_OFF]

# Fensterempfehlung – Werte kompatibel zu den bisherigen Template-Sensoren
REC_OPEN = "oeffnen"
REC_CLOSE = "schliessen"
REC_NONE = "keine_aktion"
REC_STATES = [REC_OPEN, REC_CLOSE, REC_NONE]

DEFAULT_PARAMS = {
    # Öffnen empfehlen, wenn Ist >= Soll + open_above (K) ...
    "open_above": 1.0,
    # ... und außen mindestens so viel kälter ist als innen (K)
    "open_min_delta": 2.0,
    # Hysterese, damit eine laufende Öffnen-Empfehlung nicht flattert (K)
    "hysteresis": 0.3,
    # Schließen empfehlen, wenn Ist <= Soll + close_margin (K)
    "close_margin": 0.3,
    # ... oder außen nicht mehr ausreichend kälter ist (K)
    "close_delta": 1.0,
    # ... oder das Fenster länger als max_vent_min offen ist (0 = aus; nur Heizbetrieb)
    "max_vent_min": 15,
    # Pause nach einer Lüftungsdauer-Schließempfehlung, bevor wieder Öffnen empfohlen wird
    "cooldown_min": 30,
    # Mindest-Haltezeit einer Empfehlung bei geschlossenem Fenster
    "hold_min": 5,
    # Referenztemperatur für Räume ohne Heizung (nur Fensterempfehlung),
    # wenn im Raum kein eigener Wert gesetzt ist
    "target_without_heating": 20.0,
    # Fensterabschaltung (nur Modus Auto): Thermostat aus nach X s offen ...
    "shutdown_delay_s": 60,
    # ... und wieder ein nach X s alle Kontakte zu
    "restore_delay_s": 30,
}

DEFAULT_GLOBALS = {
    "outside_sensor": "",
    "cooling_switch": "",
}
