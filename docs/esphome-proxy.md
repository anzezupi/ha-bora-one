# BORA appliances through an ESPHome Bluetooth proxy

BORA appliances only answer over an encrypted (bonded) Bluetooth link and
accept new bonds only while their pairing mode is active. With the default
ESPHome Bluetooth proxy settings a proxy can pair once, but loses the bond
again on the next reconnect, so Home Assistant needs the pairing mode every
time. The settings below fix that. They were worked out with a BORA X BO
(firmware 01.08.009) and an ESP32-C3 on ESPHome 2026.10 (ESP-IDF 5.5.6);
the same applies to a classic ESP32.

## Why the defaults fail

1. **Weak key.** The X BO sends a Security Request with MITM. A proxy with
   `io_capability: none` can only do Just Works, so its stored key is
   "unauthenticated". On the next connection ESP-IDF decides that key is too
   weak for the MITM request and starts a new pairing instead of encrypting.
   Outside pairing mode the oven refuses (`reason 0x0c`) and ESP-IDF deletes
   the bond. Fix: `display_yes_no` + `sc_mitm_bond` and accept the numeric
   comparison automatically, which yields an authenticated key like a phone.
2. **Identity address.** If the appliance distributes an identity address,
   ESP-IDF files the bond under it. Requesting only the LTK from the
   responder keeps the bond under the public address the appliance uses.
3. **Keys dropped after re-encryption (ESP-IDF bug).** After encrypting with a
   stored bond, `smp_check_auth_req()` clears the LE keys of the in-memory
   device record. On the next disconnect the record counts as unpaired and is
   deleted (`Deleting unpaired device`), so the following connection pairs
   again and fails. The bond is still in NVS; reloading it every 10 s with
   `btc_storage_load_bonded_devices()` restores it.
4. `CONFIG_BT_BLE_SMP_REMOVE_BOND_ON_PAIR_FAIL_AS_CENTRAL: n` keeps the bond
   in NVS when a pairing attempt fails.

## Setup

Copy [`esphome/bora_bond_fix.h`](esphome/bora_bond_fix.h) next to the proxy's
YAML in the ESPHome config folder, then add the following to the proxy's
configuration (replace the MAC with your appliance's Bluetooth address):

```yaml
esphome:
  includes:
    - bora_bond_fix.h

esp32:
  framework:
    sdkconfig_options:
      CONFIG_BT_BLE_SMP_REMOVE_BOND_ON_PAIR_FAIL_AS_CENTRAL: n

esp32_ble:
  io_capability: display_yes_no
  auth_req_mode: sc_mitm_bond

bluetooth_proxy:
  active: true
  cache_services: false

interval:
  - interval: 10s
    then:
      - lambda: |-
          uint8_t rsp_key = ESP_BLE_ENC_KEY_MASK;
          esp_ble_gap_set_security_param(ESP_BLE_SM_SET_RSP_KEY, &rsp_key, sizeof(rsp_key));
          if (esp_ble_get_bond_device_num() > 0) {
            btc_storage_load_bonded_devices();
          }

ble_client:
  - mac_address: D0:AB:D5:XX:XX:XX
    id: bora_appliance
    auto_connect: false   # only answers the numeric comparison
    on_numeric_comparison_request:
      then:
        - ble_client.numeric_comparison_reply:
            id: bora_appliance
            accept: true
```

Then:

1. Remove any old entry of the proxy from the appliance's list of paired
   devices.
2. Start the pairing mode on the appliance and add (or reload) the BORA One
   integration. The proxy pairs and stores the bond.
3. End the pairing mode. Later connections, also after the appliance or the
   proxy restarted, only encrypt with the stored bond.

Use only one proxy for the appliance. A second proxy without a bond would be
picked when its signal is better and then fail outside pairing mode.

`auto_connect: false` matters: the `ble_client` never connects by itself, it
only answers the numeric comparison when Home Assistant pairs through the
proxy. Accepting the comparison without showing a number is what the
appliance's pairing mode is for: only pair while you started it yourself.
