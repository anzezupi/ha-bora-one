# BORA JOY for Home Assistant

Custom integration (HACS) that brings BORA cooktops connected to the
**BORA JOY** app into Home Assistant: cooking zones, power levels, timers,
BORA Assist, the cooktop extractor and the odour filter.

> **Status: early development.** BORA has no public API. The cloud client is a
> scaffold until the app's traffic has been mapped
> ([docs/API_DISCOVERY.md](docs/API_DISCOVERY.md)). Use **demo mode** to try the
> entities, dashboards and automations in the meantime.

Supported appliances: cooktops with connectivity (BORA Pure 2 / X Pure).
Ovens (X BO) are not supported yet.

## Installation

1. HACS → ⋮ → *Custom repositories* → add this repository as an *Integration*.
2. Install **BORA JOY** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → BORA JOY*.
4. Pick **BORA JOY account** or **Demo cooktop**.

Manual install: copy `custom_components/bora_joy` into your
`config/custom_components` folder.

## Entities

One device per cooktop.

### Cooktop

| Entity | Type | Notes |
|---|---|---|
| Status | sensor (enum) | off, standby, cooking, paused, after_run, offline |
| Active zones | sensor | number of heating zones |
| Short timer end | sensor (timestamp) | egg timer |
| Extractor mode | sensor (enum) | off, manual, automatic, power_boost, after_run |
| Extractor fan level | sensor | 0–9 |
| After-run end | sensor (timestamp) | automatic extractor after-run |
| Odour filter remaining | sensor (%) | recirculation models |
| Online | binary sensor | connectivity |
| Power, Cooking, Paused | binary sensor | |
| Child lock, Cleaning lock | binary sensor | |
| Extractor running | binary sensor | |
| Filter service | binary sensor (problem) | |
| Residual heat | binary sensor (heat) | any zone still hot |

### For each cooking zone (front/rear, left/right)

| Entity | Type | Notes |
|---|---|---|
| State | sensor (enum) | off, on, power_boost, keep_warm, assist, paused, no_pan, residual_heat |
| Power level | sensor | 0–9 |
| Timer end | sensor (timestamp) | zone cut-off timer |
| Assist programme | sensor (enum) | none, fry, boil |
| Assist target temperature | sensor (°C) | Fry: 120–220 °C |
| Active | binary sensor | |
| Residual heat | binary sensor | the "H" indicator |
| Pan detected | binary sensor | |

## Events

The integration fires `bora_joy_event` with a `type` field:

| type | extra data |
|---|---|
| `cooking_started` / `cooking_finished` | |
| `zone_timer_finished` | `zone` |
| `assist_target_reached` | `zone`, `temperature` |
| `assist_finished` | `zone`, `program` |
| `short_timer_finished` | |
| `after_run_finished` | |
| `filter_service_required` | |

Example: notify when the frying pan is hot.

```yaml
automation:
  - alias: Pan is hot
    triggers:
      - trigger: event
        event_type: bora_joy_event
        event_data:
          type: assist_target_reached
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Pan reached {{ trigger.event.data.temperature }} °C"
```

## Read-only by design

The integration does not control the cooktop. BORA asks for confirmation on the
cooktop for anything sent from the app, and switching on a heat source from an
automation is a safety risk.

## Contributing API captures

See [docs/API_DISCOVERY.md](docs/API_DISCOVERY.md). Please remove tokens and
passwords before sharing captures.

## Disclaimer

Not affiliated with or endorsed by BORA Vertriebs GmbH & Co KG.
