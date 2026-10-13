# Mapping the BORA JOY API

BORA does not publish an API. To connect the integration to real cooktops we
need to learn what the BORA JOY app sends and receives. This page describes how
to capture that traffic from **your own account and your own appliance**.

## What we need to find out

1. **Login**: the auth endpoint and flow (plain token, OAuth2/OIDC with PKCE,
   AWS Cognito, Azure AD B2C, ...), and how tokens are refreshed.
2. **Appliance list**: the endpoint that returns the paired cooktops (id,
   model, name, firmware).
3. **State**: how live state reaches the app:
   - REST polling (`GET .../state`),
   - a push channel (WebSocket, MQTT over WSS, SignalR, Firebase), or
   - **local only** over Bluetooth LE, so the cloud has no live state.
4. **Field names** for zones, power levels, timers, Assist, extractor and filter.

## Option A: HTTP Toolkit or mitmproxy on Android

1. Use an Android phone or emulator (Android Studio AVD with a *Google APIs*
   image, not *Google Play*, so it can be rooted).
2. Install [HTTP Toolkit](https://httptoolkit.com/) (easiest) or
   [mitmproxy](https://mitmproxy.org/).
3. Modern apps only trust system CAs, so on a rooted emulator use HTTP Toolkit's
   "Android device via ADB" option. It installs its CA as a system CA.
4. If you see TLS errors only for BORA hosts, the app pins certificates. Use
   [Frida](https://frida.re/) with a generic unpinning script, or patch the APK
   with `apk-mitm`.
5. Use the app normally: log in, open the cooktop, switch zones on and off,
   start a timer, start an Assist, change the extractor level. Write down
   **what you did and when** so requests can be matched to actions.
6. Export the session as HAR, then open it and **remove passwords and tokens**
   before sharing it.

If the app turns out to be Flutter (look for `libflutter.so` in the APK), it
ignores the system proxy. In that case use HTTP Toolkit's VPN-based
interception or `reflutter`.

## Option B: Bluetooth LE

The cooktop also has a Bluetooth radio. If the cloud has no live state:

1. On Android, enable *Developer options → Enable Bluetooth HCI snoop log*.
2. Use the app with the cooktop, then grab the log with
   `adb bugreport` and open `btsnoop_hci.log` in Wireshark.
3. Look for GATT services, characteristics and notifications that change when
   you change a power level.

A BLE implementation would use Home Assistant's `bluetooth` integration (and
ESPHome Bluetooth proxies if the cooktop is far from the HA host).

## Plugging the results into the integration

- Endpoints and auth: `custom_components/bora_joy/api.py`
  (`API_BASE_URL`, `LOGIN_PATH`, `BoraJoyCloudClient`).
- Field mapping: `parse_cooktop()` in the same file. Everything else (entities,
  events, translations) works off the models in `models.py` and does not need
  to change.
- After the first real connection, download the diagnostics from the
  integration page. The `raw` section holds the untouched payload so the
  mapping can be refined.

## Ground rules

- Only capture traffic from your own account and appliance.
- Keep the integration read-only until the protocol is well understood. The
  cooktop itself requires on-device confirmation for actions sent from the app,
  and a home automation should not switch on a heat source unattended.
