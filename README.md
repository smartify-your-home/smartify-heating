# smartify Heizung

Home-Assistant-Integration mit Karte für die Raumregelung:

- **Modus gesamt** Auto / Hand / Aus und **je Raum** Global / Auto / Hand / Aus
- **Fensterabschaltung** (Modus Auto): Thermostat aus, solange ein Kontakt offen ist
- **Fensterempfehlung** `oeffnen` / `schliessen` / `keine_aktion` mit Gap und Hysterese
- **Mehrere Fensterkontakte pro Raum**
- Karte im smartify-Stil mit **einklappbaren Räumen** und einem Editor mit einklappbaren Bereichen

Die Logik läuft im Backend und arbeitet damit auch ohne geöffnetes Dashboard. Die Integration liefert die Karte selbst aus und registriert die Lovelace-Ressource automatisch (wie die smartify Flow Card).

## Installation

1. HACS → Benutzerdefinierte Repositories → `https://github.com/smartify-your-home/smartify-heating`, Kategorie **Integration**
2. „smartify Heizung“ installieren, Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **smartify Heizung**
4. Dashboard → Karte hinzufügen → **smartify Heizung**
5. Karte bearbeiten → Bereich **Räume** → Räume anlegen → **Speichern**

## Modi

| Modus | Wirkung auf das Thermostat |
|---|---|
| **Auto** | Thermostat an (`heat`), regelt selbst. Fensterabschaltung aktiv. |
| **Hand** | Thermostat an, keine Fensterabschaltung. |
| **Aus** | Thermostat aus (`off`). |
| **Global** (nur Raum) | Raum folgt dem Gesamtmodus. |

- Ein globales **Aus** übersteuert alle Räume. Ein globales Auto/Hand gilt nur für Räume auf „Global“.
- Der Modus wird **nur bei einem Wechsel** auf das Thermostat geschrieben (und einmal beim Start). Ein manueller Eingriff am Thermostat bleibt danach bestehen.
- Die Wärmepumpe bzw. der Heizkreis selbst (z. B. HC2) wird **nicht** geschaltet.

## Fensterempfehlung

Eingangswerte: Raumtemperatur (Sensor oder Ist-Wert des Thermostats), Soll (Thermostat oder fester Wert) und Außentemperatur.

| Empfehlung | Bedingung (Standardwerte) |
|---|---|
| **oeffnen** | Fenster zu **und** Ist ≥ Soll + 1,0 K **und** außen ≥ 2,0 K kälter als innen |
| **schliessen** | Fenster offen **und** (Ist ≤ Soll + 0,3 K **oder** außen < 1,0 K kälter **oder** 15 min offen) |
| **keine_aktion** | alles dazwischen |

- **Gap**: Öffnen ab +1,0 K, Schließen bei +0,3 K. Dazwischen bleibt ein offenes Fenster ohne Meldung offen.
- **Hysterese** 0,3 K: Eine laufende Öffnen-Empfehlung endet erst bei +0,7 K bzw. 1,7 K Außendifferenz.
- **Haltezeit** 5 min bei geschlossenem Fenster. Schließ-Empfehlungen kommen sofort.
- **Max. Lüftungsdauer** 15 min, danach **Pause** von 30 min ohne neue Öffnen-Empfehlung. Im Kühlbetrieb ist das Limit aus.
- Ohne Fensterkontakt wird für den Raum keine Empfehlung erzeugt.

Alle Werte sind im Karteneditor unter **Fensterlogik** einstellbar.

## Entitäten

Das Präfix ist das **Kürzel** des Raums (Editor → Räume).

| Entität | Inhalt |
|---|---|
| `select.heizung_modus` | Modus gesamt |
| `select.<kürzel>_heizmodus` | Raummodus; Attribute `wirksamer_modus`, `fensterabschaltung` |
| `sensor.<kürzel>_fenster_empfehlung` | Empfehlung; Attribute `grund`, `innen`, `soll`, `aussen`, `offen_seit` |
| `binary_sensor.<kürzel>_fenster_offen` | offen, sobald ein Kontakt offen ist |
| `sensor.fenster_empfehlung_gesamt` | `schliessen` vor `oeffnen` vor `keine_aktion`; Attribute mit Raumnamen |

Gibt es bereits Entitäten mit denselben IDs (z. B. alte Template-Sensoren), hängt Home Assistant `_2` an. Darum zuerst die alten Sensoren entfernen.

## Karte

```yaml
type: custom:smartify-heating-card
title: Heizung
show_header: true        # Gesamtmodus, Außentemperatur, Zusammenfassung
columns: 0               # 0 = automatisch
min_column_width: 220
collapsible: true        # Räume ein-/ausklappbar (Zustand je Browser gemerkt)
start_collapsed: false
show_graph: true         # Verlauf aus dem Raumtemperatursensor
hours_to_show: 24
show_controls: true
show_mode: true
show_recommendation: true
hide_no_action: false
show_windows: true
rooms: []                # Raum-IDs zur Auswahl; leer = alle
```

Die Räume, die Außentemperatur, der Kühlschalter und die Fensterlogik gelten für die ganze Installation. Sie werden im Editor gespeichert (nur Administratoren), nicht im Dashboard-YAML. Die Sicherung erfolgt als JSON im Editor-Bereich **Sicherung & Wiederherstellung**.
