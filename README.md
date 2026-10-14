# BORA One for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/anzezupi/ha-bora-one/actions/workflows/validate.yml/badge.svg)](https://github.com/anzezupi/ha-bora-one/actions/workflows/validate.yml)
[![Donate with PayPal](https://img.shields.io/badge/Donate-PayPal-0070BA.svg?logo=paypal)](https://paypal.me/anzezupi)

Custom integration (HACS) that shows what your BORA cooktop is doing in Home
Assistant: cooking zones, power levels, timers, BORA Assist, the cooktop
extractor and the odour filter. It talks to the cooktop **locally over
Bluetooth**, the same way the BORA One app does. No cloud account needed.

> **Status: early.** The protocol has been verified against recordings of a
> real BORA X Pure, but this integration has not yet been tested on a real
> cooktop inside Home Assistant. Reports are very welcome.

The integration is **read-only**. It never switches anything on the cooktop.

## How it works and why Bluetooth

BORA cooktops (X Pure, Pure, S Pure, M Pure) connect to Wi-Fi only to send
data to BORA's cloud (Microsoft Azure IoT Hub). They expose nothing on the
local network, and the BORA One app reads the live status only over
Bluetooth. This integration does the same.

The cooktop turns Bluetooth off about a minute after it is switched off.
That is normal: the integration then shows **Off** and reconnects as soon as
the cooktop is switched on again.

## Requirements

- A Bluetooth adapter on the Home Assistant host **within range of the
  cooktop** (a few metres), or an
  [ESPHome Bluetooth proxy](https://esphome.github.io/bluetooth-proxies/) in
  the kitchen. See the
  [Home Assistant Bluetooth docs](https://www.home-assistant.io/integrations/bluetooth/)
  for supported adapters.
- Connectivity enabled on the cooktop (user menu item **Con**).

## Installation

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/anzezupi/ha-bora-one` as an *Integration*.
2. Install **BORA One** and restart Home Assistant.
3. Switch the cooktop on. Home Assistant should discover it; otherwise go to
   *Settings → Devices & services → Add integration → BORA One*.
4. Pairing: turn off Bluetooth on the phone with the BORA One app, press
   **Submit**, then tap the pulsing **Connect** button on the cooktop.

**One connection at a time:** the cooktop accepts one Bluetooth client. While
Home Assistant is connected, the BORA One app cannot connect. Turn off the
**Allow Bluetooth connection** switch of the device to let the app connect,
and turn it on again afterwards.

There is also a **demo cooktop** (simulated cooking session) to try the
entities, dashboards and automations without an appliance.

## Entities

### Cooktop

| Entity | Type | Notes |
|---|---|---|
| Status | sensor (enum) | off, standby, cooking, paused, after_run, error |
| Active zones | sensor | number of heating zones |
| Extractor mode | sensor (enum) | off, manual, automatic, power_boost, after_run |
| Extractor fan level | sensor | 0–9 |
| After-run end | sensor (timestamp) | automatic extractor after-run |
| After-run duration | sensor (min) | configured after-run time |
| Error code | sensor | BORA error code(s), or `none` |
| Odour filter lifetime (raw) | sensor | disabled by default, unit unknown |
| Bluetooth connection | binary sensor | on while connected (cooktop on) |
| Cooking, Residual heat, Paused | binary sensor | |
| Child lock, Cleaning lock | binary sensor | |
| Extractor running | binary sensor | |
| Odour filter change | binary sensor (problem) | recirculation models |
| Error | binary sensor (problem) | |
| Allow Bluetooth connection | switch | release the cooktop for the phone app |

### For each cooking zone

| Entity | Type | Notes |
|---|---|---|
| State | sensor (enum) | off, on, power_boost, keep_warm, heat_up, assist, residual_heat |
| Power level | sensor | 0–9; P is shown as 9 with state power_boost |
| Timer end | sensor (timestamp) | zone cut-off timer |
| Keep warm | sensor (enum) | melting, keep_warm, simmering |
| Assist programme | sensor (enum) | frying, pasta (boil), … |
| Assist phase | sensor (enum) | preheat, confirmation_required, active, expired |
| Assist target temperature | sensor (°C) | Fry |
| Active, Residual heat | binary sensor | |
| Assist confirmation required | binary sensor | the cooktop waits for you |

## Events

`bora_one_event` with a `type` field:

| type | extra data |
|---|---|
| `switched_on` / `switched_off` | |
| `cooking_started` / `cooking_finished` | |
| `zone_timer_finished` | `zone` |
| `assist_target_reached` | `zone`, `temperature` |
| `assist_finished` | `zone`, `program` |
| `after_run_finished` | |
| `filter_service_required` | |

Example: notify when the frying pan is hot.

```yaml
automation:
  - alias: Pan is hot
    triggers:
      - trigger: event
        event_type: bora_one_event
        event_data:
          type: assist_target_reached
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Pan reached {{ trigger.event.data.temperature }} °C"
```

## Credits

The Bluetooth protocol implementation comes from
[ha-bora](https://github.com/kalsdjf23/ha-bora) by kalsdjf23 (MIT), see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Support

If this integration is useful to you, you can buy me a coffee via
[PayPal](https://paypal.me/anzezupi). Thank you!

## Disclaimer

Not affiliated with or endorsed by BORA Vertriebs GmbH & Co KG.
