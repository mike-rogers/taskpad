# TaskPad Milestones

Each milestone leaves the whole system working end-to-end before the next
begins.

## M0 — Baseline (done, 2026-09-24)

ESP-IDF firmware (ESP32-C3 + ST7789, LVGL, MQTT) plus a Home Assistant YAML
package: Local to-do list backend, completion-relative rescheduling,
permanent history log via the File integration, MQTT discovery device.
Working: button → todo close-out → successor → history line → display
refresh.

## M1 — Custom integration core (done, 2026-09-24)

Replace the YAML package, Local to-do, and File integration with
`custom_components/taskpad/`:

- [x] Integration-owned `todo.taskpad` entity backed by `.storage`
      (structured `interval_days` per item instead of description-string
      parsing being the source of truth; `interval: N[d|w|m|y]` in the
      description remains the input method from the To-do card)
- [x] Config flow (topic prefix, log path, default interval) + options flow
- [x] MQTT: subscribe `taskpad/complete` directly, publish retained
      `taskpad/tasks` on every change (no automations)
- [x] Completion logic in Python: close item, create successor at
      completion date + interval, append history line, fire
      `taskpad_completed` bus event (logbook visibility)
- [x] Ticking the checkbox in the To-do card triggers the SAME completion
      flow (the entity intercepts the status change — the old "don't touch
      the checkbox" rule dies here)
- [x] `taskpad.complete` service (name or uid)
- [x] One-time import from the existing Local to-do list
- [x] Clean uninstall: `async_remove_entry` deletes storage and clears the
      retained tasks topic
- [x] Migration: after verification, remove the package automations/script
      and the Local to-do list

Firmware: unchanged.

## M2 — Blocked / prerequisite tasks (done, 2026-09-24)

- [x] Firmware: long-press detection on Done (and later the ANO center
      button); publishes `{"task_id": ...}` to `taskpad/blocked`
- [x] Integration: creates a linked one-shot prep item ("Prep: <name>", due
      today, no interval), marks the parent blocked, stores the link by uid
- [x] Completing the prep item auto-unblocks the parent; completing the
      parent directly auto-closes the orphaned prep item
- [x] Published task list gains a `blocked` flag; device renders blocked
      items distinctly
- [x] History log records blocked/unblocked transitions

## M2.5 — Task editor: typed services + custom card (done, 2026-09-26)

- [x] Structured periodicity stored as value + unit (days/weeks/months);
      per-task dependency text (`prep_text`) used as the spawned prep item's
      name; storage migration from interval_days-only items
- [x] Services with typed selectors: `taskpad.add_task` (name, first due
      date defaulting to today + period, value + unit, dependency text),
      `taskpad.update_task`, `taskpad.block`
- [x] Task metadata exposed as `todo.taskpad` attributes for the frontend
- [x] `custom:taskpad-card` (vanilla JS, served + auto-registered by the
      integration): task list with urgency colors, blocked/prep rendering,
      complete/block/edit buttons, and a create/edit form with the fields
      above, prefilled on edit
- [x] Legacy `interval:` description parsing retained as fallback input

## M3 — Discovery & adoption (done, 2026-09-26)

- [x] Firmware: mDNS advertisement (`_taskpad._tcp`, TXT: id + version) and
      a small local HTTP endpoint that accepts broker config on first boot;
      config persisted to NVS
- [x] Integration: zeroconf discovery in the manifest → "New device found"
      card → config flow pushes broker credentials to the device
- [x] Remove Wi-Fi/broker secrets from menuconfig (Wi-Fi still via
      menuconfig until M4)
- [x] Remove device-side MQTT discovery configs (the integration owns the
      device registration); firmware sheds the discovery payloads

Note: adoption verified working on first try. Auto-discovery initially
appeared broken; a Linux host resolving both homeassistant.local and the
device disproved the network-filtering theory (the Mac's failures were
macOS Local Network permission gating) and pointed at the config flow
reading the removed ZeroconfServiceInfo.host attribute — fixed to
ip_address. Adoption by IP via Configure -> Adopt device works
regardless of discovery. Full fresh-install path (delete entry ->
discovered card -> adopt) verified end-to-end 2026-09-27; note that HA
only re-surfaces the discovery after a fresh device announcement, so a
device reboot may be needed when re-adding. Discovery flows are
suppressed by design while an entry exists (single_config_entry).

## M4 — Improv Wi-Fi provisioning (BLE) (done, 2026-09-27)

- [x] Firmware: Improv-over-BLE per the published spec; factory-fresh
      device is provisioned from the HA companion app, then M3 discovery
      takes over (self-contained `improv_ble` module, reusable in other
      gadgets: NimBLE GATT service + advertising + RPC, project-specific
      behavior injected via a connect callback)
- [x] Wi-Fi credentials live in NVS; menuconfig values remain an optional
      dev-only fallback (empty by default) rather than being removed

Note: verified with the HA companion app end-to-end (including
fail-fast retry on mistyped credentials). Wi-Fi passwords must be
typed on the phone: mobile OSes expose stored Wi-Fi credentials to
no app, so no provisioning flow can prefill them.

## M5 — OTA updates (done, 2026-09-27)

- [x] Partition relayout: two OTA app slots (verify headroom for the
      ~1.4MB image within 4MB flash)
- [x] Firmware: `esp_https_ota` pull, rollback on failed boot
- [x] Integration: `update` entity on the device page serving/pointing to
      firmware binaries

Note: verified with a live 0.8.0 -> 0.8.1 update installed from the
HA device page. Slot headroom is 14% at the current 1.75MB image;
budget flash before adding large features. Release ritual:
idf.py build -> scripts/release_firmware.sh -> copy firmware/* to
the HA share -> Install in HA.

## M6 — Stretch

- [ ] Adafruit ANO rotary encoder input backend (I2C seesaw) behind the
      existing input abstraction
- [ ] HACS packaging (`hacs.json`, repo structure) and publication
- [ ] Lovelace dashboard example
