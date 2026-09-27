#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"

#include "wifi_conn.h"

static const char *TAG = "wifi";

static EventGroupHandle_t s_events;
#define GOT_IP_BIT BIT0

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id,
                          void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, GOT_IP_BIT);
        ESP_LOGW(TAG, "disconnected, retrying");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evt = data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&evt->ip_info.ip));
        xEventGroupSetBits(s_events, GOT_IP_BIT);
    }
}

void wifi_conn_start(void)
{
    s_events = xEventGroupCreate();

    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, NULL, NULL));

    wifi_config_t sta_cfg = {
        .sta = {
            .threshold.authmode = strlen(CONFIG_TASKPAD_WIFI_PASSWORD)
                                      ? WIFI_AUTH_WPA2_PSK
                                      : WIFI_AUTH_OPEN,
        },
    };
    strlcpy((char *)sta_cfg.sta.ssid, CONFIG_TASKPAD_WIFI_SSID,
            sizeof(sta_cfg.sta.ssid));
    strlcpy((char *)sta_cfg.sta.password, CONFIG_TASKPAD_WIFI_PASSWORD,
            sizeof(sta_cfg.sta.password));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
    // Mains-powered device: disable modem power save. The default doze
    // drops/delays multicast, which makes mDNS discovery unreliable.
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    xEventGroupWaitBits(s_events, GOT_IP_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}
