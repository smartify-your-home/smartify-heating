# Changelog

## v0.1.3

- Grund `zu_kalt` („Unter Soll“) statt „Im Sollbereich“, wenn der Raum unter Soll liegt

## v0.1.2

- Behoben: blockierender Dateizugriff beim Start (Warnung „Detected blocking call to open“)
- Entitätsnamen über Geräte: „Bad Heizmodus“ statt „smartify Heizung … “
- Räume ohne Heizung: optionale Referenz-Entität (z. B. `input_number`)
- Neuer Dienst `smartify_heating.set_config` zum Setzen/Importieren der Konfiguration (Admin)

## v0.1.1

- Eigenes Icon und Logo (Ordner `brand/`, hell und dunkel) – wird ab Home Assistant 2026.3 angezeigt

## v0.1.0

- Erste Version: Integration `smartify_heating` mit Card `smartify-heating-card`
- Modus gesamt und je Raum: Auto / Hand / Aus (Raum zusätzlich „Global“)
- Fensterabschaltung im Modus Auto, mehrere Kontakte pro Raum
- Fensterempfehlung `oeffnen` / `schliessen` / `keine_aktion` mit Gap, Hysterese, Haltezeit, max. Lüftungsdauer und Pause
- Räume ohne Heizung: nur Fensterempfehlung mit Referenztemperatur (Standard 20 °C)
- Karteneditor mit einklappbaren Bereichen, Raumverwaltung und JSON-Sicherung
