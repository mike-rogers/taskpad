# TaskPad

A small desk gadget that nags you (politely) about periodic chores — change
the furnace filter, dose the dog, swap smoke detector batteries. Home
Assistant is the source of truth; this device displays what's coming due and
lets you check things off with a button.

The device talks MQTT and announces itself with MQTT discovery, so it appears
in HA as a proper device (with online/offline connectivity and a
last-completed-task sensor) — no API tokens involved.

Hardware:

- SparkFun Pro Micro ESP32-C3
- 2.8" 240x320 ST7789 TFT (SPI)
- Two momentary buttons for now; Adafruit ANO rotary encoder (I2C) later

## Wiring (defaults, changeable in menuconfig)

| LCD pin   | ESP32-C3 GPIO |
|-----------|---------------|
| VCC       | 3V3           |
| GND       | GND           |
| SCL / SCK | 6             |
| SDA / MOSI| 7             |
| CS        | 10            |
| DC        | 4             |
| RES / RST | 5             |
| BLK       | 3             |

| Button          | GPIO                    |
|-----------------|-------------------------|
| Done (complete) | 1 → button → GND        |
| Down (select)   | 9 (onboard BOOT button) |

## Home Assistant setup

Terminology note: recent HA renamed "Add-ons" to **Apps**, and the config
directory File Editor shows is **`homeassistant/`** (formerly `/config` —
same place, new name; HA core itself still calls it `/config` internally,
which is why file paths below use that form).

Tasks live in a native HA **to-do list**, so adding and editing chores
happens on the To-do sidebar page — no YAML edits per task. Completions are
appended to a permanent log file, `/config/taskpad_history.log`.

1. Install the **File Editor** app (Settings → Apps → App Store) so you can
   edit YAML files, and the **Mosquitto broker** app if it isn't already
   installed. Once Mosquitto is running, Settings → Devices & Services will
   offer to set up the MQTT integration — accept it.
2. Create a dedicated HA user (e.g. `taskpad`) under Settings → People →
   Users; the device logs into the broker with it.
3. In File Editor, open `configuration.yaml` (in the root `homeassistant/`
   directory) and add this block at the top, above `default_config:`:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
     allowlist_external_dirs:
       - /config
   ```

   (The allowlist is what permits the File integration to write the history
   log. It must be in place, and HA restarted, BEFORE you set up the File
   integration in step 6 — the integration validates the path when you add
   it, and rejects it with "Access to the selected file path is not
   allowed" otherwise.)
4. Create the `packages` folder first using File Editor's New Folder button —
   naming a new file `packages/taskpad.yaml` does NOT auto-create the folder;
   it errors instead. Then create `taskpad.yaml` inside it and paste in the
   contents of `ha/taskpad.yaml` from this repo.
5. Validate with Developer Tools → YAML → Check configuration, then restart
   HA.
6. Add two integrations under Settings → Devices & Services → Add
   integration:
   - **Local to-do**: create a list named `TaskPad`. Confirm its entity id
     is `todo.taskpad` (Developer Tools → States); the package references
     that id.
   - **File**: choose the notification service type, file path
     `/config/taskpad_history.log`, timestamps enabled. The integration
     names the entity generically (`notify.file`), so rename it: Settings →
     Devices & Services → Entities → `notify.file` → settings (gear icon) →
     set Entity ID to `notify.taskpad_history`.
7. Add your chores on the **To-do** sidebar page: name, first due date, and
   the repeat interval in the description field — `interval: 90` (days),
   `interval: 2w`, `interval: 3m`, or `interval: 1y`. Anything missing or
   unparseable falls back to 30 days.

## Custom integration (replaces the package)

`custom_components/taskpad/` supersedes the YAML package, Local to-do, and
File integration: an integration-owned `todo.taskpad` entity with
structured intervals, direct MQTT handling (no automations), the same
completion-relative rescheduling and history log, a `taskpad.complete`
service, and a `taskpad_completed` event. Ticking the checkbox on the
To-do card runs the full completion flow (unlike the package setup).

Install: copy the folder to `custom_components/taskpad/` in the HA config
directory, restart HA, then Settings → Devices & Services → Add
integration → TaskPad. Use the import field to pull your open items from
the existing list, then delete the old Local to-do list and remove the
package's `script:`/`automation:` blocks (double handlers = double
successors). Tip: the Samba share app makes copying the folder a
drag-and-drop from a mounted network share.

The package setup steps below describe the pre-integration architecture;
they're kept as documentation of the fallback path, not required setup.

## Build & flash

```sh
idf.py set-target esp32c3
idf.py menuconfig   # TaskPad Configuration: Wi-Fi, MQTT broker + creds, pins
idf.py build flash monitor
```

Note: use an IP address or DNS hostname for the broker URI — `.local` mDNS
names don't resolve from the device without adding the `espressif/mdns`
component.

`sdkconfig` holds your Wi-Fi and MQTT passwords, and is gitignored.

## Behavior

- HA publishes the task list to the retained `taskpad/tasks` topic whenever
  the to-do list changes (plus hourly, to catch due-date edits); the device
  gets updates instantly and current state on every reconnect — no polling.
- Shows tasks due within 14 days (configurable); overdue tasks always show.
- Row color by urgency: green → yellow (≤7 days) → orange (≤2 days) →
  red (overdue).
- BOOT moves the selection; the Done button publishes to `taskpad/complete`,
  which runs `script.taskpad_complete`: the to-do item is closed out (it
  stays in the completed pile as a visual record), a successor item is
  created due **completion date + interval**, and a timestamped line is
  appended to `/config/taskpad_history.log` — the permanent record, immune
  to HA's ~10-day recorder purge.
- To complete a chore from HA instead of the device, run
  `script.taskpad_complete` (e.g. from a dashboard button) with the item's
  name. Ticking the checkbox on the To-do page completes the item WITHOUT
  scheduling the next occurrence or logging.
- Availability via MQTT last-will: unplug the device and its Connectivity
  entity in HA goes off.
