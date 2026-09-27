# Releasing TaskPad

## Firmware release (public, via CI)

1. Bump `TASKPAD_FW_VERSION` in `main/fw_version.h`.
2. Commit, then tag and push:

   ```sh
   git tag vX.Y.Z
   git push origin main --tags
   ```

3. CI (`.github/workflows/firmware.yml`) builds against ESP-IDF v6.0 and
   attaches two assets to the GitHub release:
   - `taskpad.bin` — the OTA application image
   - `taskpad-factory.bin` — esptool-merged full-flash image
4. The release publish triggers `.github/workflows/pages.yml`, which
   redeploys the project page and browser flasher with the new factory
   image. (The binary is copied into the Pages artifact deliberately:
   GitHub release assets don't send CORS headers, so ESP Web Tools can't
   fetch them cross-origin.)

## Updating your own device (local, no CI)

1. `idf.py build`
2. `./scripts/release_firmware.sh` — stages `taskpad.bin` + `version.txt`
   into `custom_components/taskpad/firmware/`
3. Copy `custom_components/taskpad/firmware/*` to the HA config share
   (plain `cp`, not Finder — the Samba add-on vetoes `._*` metadata files
   and Finder copies fail with error -8062).
4. Home Assistant → TaskPad device page → the Firmware entity offers the
   update (poll is ~15 min; force with the `homeassistant.update_entity`
   action) → Install. The device pulls, flashes the idle OTA slot, and
   reboots; a boot that never reaches MQTT rolls back automatically.

## Integration release

1. Bump `version` in `custom_components/taskpad/manifest.json` **and**
   `VERSION` in `custom_components/taskpad/const.py` (they must match —
   the versioned Lovelace resource URL busts card caches).
2. Local install: copy the changed files to the share and restart HA.
3. HACS installs pick up new tags/default-branch commits via HACS's
   normal update flow.

## Invariants worth knowing

- Firmware and integration versions are independent; the update entity
  compares the device's reported version (retained `taskpad/status`)
  against `firmware/version.txt`, and only offers an update when the
  served `taskpad.bin` actually exists next to it.
- The OTA slots are 1984KB each and the image is ~1.75MB (~14% headroom).
  Budget flash before adding large components.
- A commit that shouldn't trigger the firmware CI can include `[skip ci]`
  in its message.
