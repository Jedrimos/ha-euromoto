# EURO MOTO / IDM – Home Assistant Integration

Eine HACS Custom Component für Home Assistant, die Daten der
**Internationalen Deutschen Motorradmeisterschaft (IDM / EURO MOTO)** bereitstellt.

[![HACS Validation](https://github.com/Jedrimos/ha-euromoto/actions/workflows/validate.yml/badge.svg)](https://github.com/Jedrimos/ha-euromoto/actions/workflows/validate.yml)

---

## Was macht diese Integration?

Die Integration ruft folgende Daten von `euromoto.racing` ab und stellt sie als Home-Assistant-Sensoren bereit:

- **Rennkalender** – alle Rennwochenenden der aktuellen Saison mit Datum, Strecke und Status
- **Nächstes Event** – detaillierte Streckeninfos (Länge, Kurven, Adresse) und Links zu Tickets/Livestream
- **Meisterschaftsstände** – aus den offiziellen PDF-Ergebnisberichten (Superbike, Supersport, Sportbike)
- **Rennwochenende-Sensor** – aktiv/inaktiv, ideal für Automationen

Daten werden alle **6 Stunden** aktualisiert, während eines Rennwochenendes alle **30 Minuten**.

---

## Installation via HACS

### Schritt 1 – Custom Repository hinzufügen

1. HACS öffnen → **Integrationen** → Drei-Punkte-Menü (oben rechts) → **Benutzerdefinierte Repositories**
2. URL eingeben: `https://github.com/Jedrimos/ha-euromoto`
3. Kategorie: **Integration**
4. **Hinzufügen** klicken

### Schritt 2 – Integration installieren

1. In HACS nach **EURO MOTO / IDM** suchen
2. **Herunterladen** klicken
3. Home Assistant neu starten

### Schritt 3 – Integration einrichten

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**
2. Nach **EURO MOTO** suchen
3. Gewünschte Klassen-Standings auswählen (Superbike, Supersport, Sportbike)

---

## Sensoren

### `sensor.euromoto_next_event`

**State:** Name der nächsten Strecke, z.B. `Sachsenring`

| Attribut | Beispiel |
|---|---|
| `date_start` | `2026-05-08` |
| `date_end` | `2026-05-10` |
| `days_until` | `0` (laufend) |
| `is_race_weekend` | `true` |
| `country` | `DE` |
| `track_url` | `https://euromoto.racing/strecke/sachsenring/` |
| `track_length_km` | `3.67` |
| `track_corners_right` | `3` |
| `track_corners_left` | `10` |
| `track_longest_straight_m` | `780` |
| `track_address` | `Hohensteiner Str. 2, 09353 Oberlungwitz` |
| `tickets_url` | `https://tickets.euromoto.racing/` |
| `livestream_url` | `https://euromoto.racing/live/` |
| `livetiming_url` | `http://livetiming.bike-promotion.com/#/channel/c1` |

---

### `sensor.euromoto_season_calendar`

**State:** Anzahl verbleibender Events, z.B. `6`

**Attribute:** `season`, `total_events`, `completed_events`, `remaining_events`, `events` (Liste aller Runden mit Status `completed` / `live` / `upcoming`)

---

### `sensor.euromoto_sbk_standings`

**State:** Name des Führenden in der Superbike-Klasse, z.B. `Marcel Schrötter`

**Attribute:**

```yaml
class: Superbike
season: 2026
last_updated: "2026-05-10T18:30:00+00:00"
standings:
  - pos: 1
    number: 94
    name: Marcel Schrötter
    nation: DE
    bike: BMW
    points: 50
  - pos: 2
    ...
```

Analog: `sensor.euromoto_ssp_standings` (Supersport), `sensor.euromoto_spb_standings` (Sportbike)

---

### `sensor.euromoto_race_weekend`

**State:** `active` / `inactive`

**Attribute:** `event_name`, `day` (z.B. `Saturday`), `livetiming_url`, `livestream_url`

---

## Beispiel-Automationen

### Benachrichtigung 30 Minuten vor dem nächsten Rennen

```yaml
automation:
  - alias: "IDM Rennen startet bald"
    trigger:
      - platform: template
        value_template: >
          {{ state_attr('sensor.euromoto_next_event', 'days_until') | int == 0
             and now().hour == 9 and now().minute == 30 }}
    action:
      - service: notify.mobile_app_mein_handy
        data:
          title: "IDM Rennen heute!"
          message: >
            Heute Rennen auf dem {{ states('sensor.euromoto_next_event') }}.
            Live: {{ state_attr('sensor.euromoto_next_event', 'livestream_url') }}
```

### Licht einschalten während des Rennwochenendes

```yaml
automation:
  - alias: "IDM Rennwochenende – Licht an"
    trigger:
      - platform: state
        entity_id: sensor.euromoto_race_weekend
        to: "active"
    action:
      - service: light.turn_on
        target:
          entity_id: light.wohnzimmer
        data:
          brightness_pct: 100
          color_name: red
```

### TTS-Ansage wenn Führungswechsel

```yaml
automation:
  - alias: "IDM Neuer Führender"
    trigger:
      - platform: state
        entity_id: sensor.euromoto_sbk_standings
    condition:
      - condition: template
        value_template: "{{ trigger.from_state.state != trigger.to_state.state }}"
    action:
      - service: tts.speak
        data:
          message: >
            Führungswechsel in der IDM Superbike!
            Neuer Führender: {{ states('sensor.euromoto_sbk_standings') }}
```

---

## Known Limitations

- **Live-Timing:** Das Echtzeit-Timing (`livetiming.raceresults.de`) ist noch nicht implementiert. Der Sensor zeigt nur den Link. Ein WebSocket-Protokoll muss noch reverse-engineered werden.
- **Standings-Aktualisierung:** Die Meisterschaftsstände werden nur nach abgeschlossenen Rennwochenenden veröffentlicht. Unmittelbar zu Saisonbeginn (vor dem ersten Rennen) sind die Standings leer.
- **Website-Struktur:** Die Seite `euromoto.racing` basiert auf WordPress. Bei größeren Layout-Änderungen kann das Parsing fehlschlagen. Fehler werden im HA-Log protokolliert, die Integration stürzt nicht ab.
- **PDF-Verfügbarkeit:** Ergebnis-PDFs werden nach jedem Rennwochenende manuell hochgeladen. Es kann einige Stunden dauern bis sie verfügbar sind.

---

## Entwicklung & Beitragen

```bash
git clone https://github.com/Jedrimos/ha-euromoto
cd ha-euromoto
pip install beautifulsoup4 pdfplumber aiohttp pytest pytest-asyncio homeassistant
pytest tests/ -v
```

Issues und Pull Requests sind willkommen: [GitHub Issues](https://github.com/Jedrimos/ha-euromoto/issues)
