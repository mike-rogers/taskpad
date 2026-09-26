#pragma once

#include <stdbool.h>
#include "esp_err.h"

// Broker configuration pushed by the Home Assistant integration during
// adoption and persisted in NVS. Wi-Fi stays in menuconfig until M4.
typedef struct {
    char mqtt_uri[128];
    char mqtt_user[64];
    char mqtt_pass[64];
} device_cfg_t;

// Load the stored config; returns false when the device is unprovisioned.
bool device_cfg_load(device_cfg_t *cfg);

esp_err_t device_cfg_save(const device_cfg_t *cfg);
