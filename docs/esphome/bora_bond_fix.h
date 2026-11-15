#pragma once
// Workaround for ESP-IDF 5.5.6 (Bluedroid): after re-encrypting a link with a
// stored bond, the stack clears the LE keys of the in-memory device record
// (smp_check_auth_req -> btm_sec_clear_ble_keys). On the next disconnect the
// record then counts as "unpaired" and is deleted, so the following connection
// tries to pair again. The bond is still in NVS; this reloads it into the
// stack's device records. Safe to call repeatedly.
extern "C" int btc_storage_load_bonded_devices(void);
