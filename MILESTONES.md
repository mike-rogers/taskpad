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

## M2 — Blocked / prerequisite tasks

- [ ] Firmware: long-press detection on Done (and later the ANO center
      button); publishes `{"task_id": ...}` to `taskpad/blocked`
- [ ] Integration: creates a linked one-shot prep item ("Prep: <name>", due
      today, no interval), marks the parent blocked, stores the link by uid
- [ ] Completing the prep item auto-unblocks the parent; completing the
      parent directly auto-closes the orphaned prep item
- [ ] Published task list gains a `blocked` flag; device renders blocked
      items distinctly
- [ ] History log records blocked/unblocked transitions

## M3 — Discovery & adoption

- [ ] Firmware: mDNS advertisement (`_taskpad._tcp`, TXT: id + version) and
      a small local HTTP endpoint that accepts broker config on first boot;
      config persisted to NVS
- [ ] Integration: zeroconf discovery in the manifest → "New device found"
      card → config flow pushes broker credentials to the device
- [ ] Remove Wi-Fi/broker secrets from menuconfig (Wi-Fi still via
      menuconfig until M4)
- [ ] Remove device-side MQTT discovery configs (the integration owns the
      device registration); firmware sheds the discovery payloads

## M4 — Improv Wi-Fi provisioning (BLE)

- [ ] Firmware: Improv-over-BLE per the published spec; factory-fresh
      device is provisioned from the HA companion app, then M3 discovery
      takes over
- [ ] Remove the last menuconfig secrets

## M5 — OTA updates

- [ ] Partition relayout: two OTA app slots (verify headroom for the
      ~1.4MB image within 4MB flash)
- [ ] Firmware: `esp_https_ota` pull, rollback on failed boot
- [ ] Integration: `update` entity on the device page serving/pointing to
      firmware binaries

## M6 — Stretch

- [ ] Adafruit ANO rotary encoder input backend (I2C seesaw) behind the
      existing input abstraction
- [ ] HACS packaging (`hacs.json`, repo structure) and publication
- [ ] Lovelace dashboard example
