#include <string.h>

#include "nvs.h"

#include "device_cfg.h"

#define NAMESPACE "taskpad"

bool device_cfg_load(device_cfg_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    nvs_handle_t handle;
    if (nvs_open(NAMESPACE, NVS_READONLY, &handle) != ESP_OK) {
        return false;
    }
    size_t size = sizeof(cfg->mqtt_uri);
    bool ok = nvs_get_str(handle, "mqtt_uri", cfg->mqtt_uri, &size) == ESP_OK &&
              cfg->mqtt_uri[0] != '\0';
    size = sizeof(cfg->mqtt_user);
    if (nvs_get_str(handle, "mqtt_user", cfg->mqtt_user, &size) != ESP_OK) {
        cfg->mqtt_user[0] = '\0';
    }
    size = sizeof(cfg->mqtt_pass);
    if (nvs_get_str(handle, "mqtt_pass", cfg->mqtt_pass, &size) != ESP_OK) {
        cfg->mqtt_pass[0] = '\0';
    }
    nvs_close(handle);
    return ok;
}

esp_err_t device_cfg_save(const device_cfg_t *cfg)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }
    if ((err = nvs_set_str(handle, "mqtt_uri", cfg->mqtt_uri)) == ESP_OK &&
        (err = nvs_set_str(handle, "mqtt_user", cfg->mqtt_user)) == ESP_OK &&
        (err = nvs_set_str(handle, "mqtt_pass", cfg->mqtt_pass)) == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    return err;
}
