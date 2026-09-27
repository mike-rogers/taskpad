#!/usr/bin/env bash
# Stage the built firmware for OTA distribution by the HA integration.
# Run after `idf.py build`; then deploy custom_components/taskpad/ to HA.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/#define TASKPAD_FW_VERSION "\(.*\)"/\1/p' main/fw_version.h)
if [ -z "$VERSION" ]; then
    echo "could not read TASKPAD_FW_VERSION from main/fw_version.h" >&2
    exit 1
fi
if [ ! -f build/taskpad.bin ]; then
    echo "build/taskpad.bin missing - run idf.py build first" >&2
    exit 1
fi

mkdir -p custom_components/taskpad/firmware
cp build/taskpad.bin custom_components/taskpad/firmware/taskpad.bin
printf '%s' "$VERSION" > custom_components/taskpad/firmware/version.txt
echo "staged firmware $VERSION ($(wc -c < build/taskpad.bin | tr -d ' ') bytes)"
