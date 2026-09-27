#include <stdbool.h>
#include <stdlib.h>
#include <time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "nvs_flash.h"

#include "esp_mac.h"
#include "esp_ota_ops.h"

#include "wifi_conn.h"
#include "taskpad_mqtt.h"
#include "device_cfg.h"
#include "adopt_server.h"
#include "improv_ble.h"
#include "events.h"
#include "ui.h"
#include "input.h"

static const char *TAG = "taskpad";

// With no events, wake hourly so days-left rolls over at midnight.
#define IDLE_TICKS pdMS_TO_TICKS(60 * 60 * 1000)

static task_item_t s_tasks[TASKS_MAX];
static size_t s_count;
static size_t s_selected;

static void sync_time(void)
{
    setenv("TZ", CONFIG_TASKPAD_TZ, 1);
    tzset();
    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    ESP_ERROR_CHECK(esp_netif_sntp_init(&cfg));
    if (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(15000)) != ESP_OK) {
        ESP_LOGW(TAG, "SNTP sync timed out; due dates may be wrong until it lands");
    }
}

// Improv hands us candidate credentials; trial them and persist on success.
static bool improv_try_connect(const char *ssid, const char *password)
{
    ui_set_status("Trying Wi-Fi...");
    if (!wifi_conn_try(ssid, password, 15000)) {
        ui_set_status("Wi-Fi failed - try again from the app");
        return false;
    }
    if (device_cfg_save_wifi(ssid, password) != ESP_OK) {
        ESP_LOGE(TAG, "could not persist Wi-Fi credentials");
    }
    return true;
}

static void refresh(void)
{
    s_count = taskpad_mqtt_get_tasks(s_tasks, TASKS_MAX);
    if (s_selected >= s_count) {
        s_selected = 0;
    }
    ui_show_tasks(s_tasks, s_count, s_selected);
}

static void set_status_time(const char *prefix)
{
    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    char buf[40];
    snprintf(buf, sizeof(buf), "%s %02d:%02d", prefix, tm.tm_hour, tm.tm_min);
    ui_set_status(buf);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ui_init();

    static device_cfg_t cfg;
    bool provisioned = device_cfg_load(&cfg);

    wifi_conn_init();

    // Wi-Fi credentials: NVS (Improv-provisioned) first, then the optional
    // menuconfig dev fallback, else BLE provisioning via the HA app.
    const char *ssid = cfg.wifi_ssid[0] ? cfg.wifi_ssid
                                        : CONFIG_TASKPAD_WIFI_SSID;
    const char *pass = cfg.wifi_ssid[0] ? cfg.wifi_pass
                                        : CONFIG_TASKPAD_WIFI_PASSWORD;
    if (ssid[0]) {
        ui_set_status("Connecting to Wi-Fi...");
        while (!wifi_conn_try(ssid, pass, 20000)) {
            ui_set_status("Wi-Fi retrying...");
        }
    } else {
        uint8_t mac[6];
        static char name[24];
        esp_read_mac(mac, ESP_MAC_WIFI_STA);
        snprintf(name, sizeof(name), "taskpad-%02x%02x%02x", mac[3], mac[4],
                 mac[5]);
        ui_set_status("Set up Wi-Fi with the Home Assistant app");
        improv_ble_start(name, improv_try_connect);
        improv_ble_wait_provisioned();
        improv_ble_stop();
        ui_set_status("Wi-Fi connected");
    }

    ui_set_status("Syncing time...");
    sync_time();
    adopt_server_start(provisioned);

    if (!provisioned) {
        // A successful adoption POST saves the config and reboots us.
        ESP_LOGI(TAG, "unprovisioned: waiting for adoption");
        ui_set_status("Ready to adopt: add TaskPad in Home Assistant");
        for (;;) {
            vTaskDelay(portMAX_DELAY);
        }
    }

    QueueHandle_t queue = xQueueCreate(8, sizeof(app_event_t));
    input_init(queue);

    ui_set_status("Connecting to MQTT...");
    taskpad_mqtt_start(queue, &cfg);

    for (;;) {
        app_event_t evt;
        if (xQueueReceive(queue, &evt, IDLE_TICKS) != pdTRUE) {
            refresh(); // recompute days-left across midnight
            continue;
        }

        switch (evt) {
        case APP_EVT_BTN_DOWN:
            if (s_count > 0) {
                s_selected = (s_selected + 1) % s_count;
                ui_show_tasks(s_tasks, s_count, s_selected);
            }
            break;

        case APP_EVT_BTN_DONE:
            if (s_count > 0) {
                if (taskpad_mqtt_publish_complete(s_tasks[s_selected].id) == ESP_OK) {
                    // HA reschedules and republishes the retained task list,
                    // which arrives as APP_EVT_TASKS_UPDATED.
                    ui_set_status("Completing...");
                } else {
                    ui_set_status("Complete failed");
                }
            }
            break;

        case APP_EVT_BTN_DONE_LONG:
            if (s_count > 0) {
                if (taskpad_mqtt_publish_blocked(s_tasks[s_selected].id) == ESP_OK) {
                    ui_set_status("Marked blocked - prep task created");
                } else {
                    ui_set_status("Block failed");
                }
            }
            break;

        case APP_EVT_TASKS_UPDATED:
            refresh();
            set_status_time("Updated");
            break;

        case APP_EVT_CONN_UP:
            ui_set_status("Connected");
            // A healthy MQTT connection is our post-OTA health check: only
            // now does a freshly flashed image escape bootloader rollback.
            esp_ota_mark_app_valid_cancel_rollback();
            break;

        case APP_EVT_CONN_DOWN:
            ui_set_status("MQTT disconnected");
            break;
        }
    }
}
