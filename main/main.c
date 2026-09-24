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

#include "wifi_conn.h"
#include "taskpad_mqtt.h"
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

    ui_set_status("Connecting to Wi-Fi...");
    wifi_conn_start();

    ui_set_status("Syncing time...");
    sync_time();

    QueueHandle_t queue = xQueueCreate(8, sizeof(app_event_t));
    input_init(queue);

    ui_set_status("Connecting to MQTT...");
    taskpad_mqtt_start(queue);

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
            break;

        case APP_EVT_CONN_DOWN:
            ui_set_status("MQTT disconnected");
            break;
        }
    }
}
