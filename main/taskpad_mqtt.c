#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <math.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "mqtt_client.h"
#include "cJSON.h"

#include "taskpad_mqtt.h"
#include "events.h"

static const char *TAG = "taskpad_mqtt";

#define TOPIC_TASKS "taskpad/tasks"
#define TOPIC_COMPLETE "taskpad/complete"
#define TOPIC_BLOCKED "taskpad/blocked"
#define TOPIC_AVAIL "taskpad/availability"

#define TASKS_PAYLOAD_MAX 8192

// Shared by every discovery config so HA groups the entities as one device.
#define DEVICE_JSON                                                       \
    "\"device\":{\"identifiers\":[\"taskpad\"],\"name\":\"TaskPad\","     \
    "\"manufacturer\":\"DIY\",\"model\":\"ESP32-C3 + ST7789 2.8\\\"\","   \
    "\"sw_version\":\"0.2.0\"}"

static const char *DISC_CONNECTIVITY_TOPIC =
    "homeassistant/binary_sensor/taskpad/connectivity/config";
static const char *DISC_CONNECTIVITY =
    "{\"name\":\"Connectivity\",\"unique_id\":\"taskpad_connectivity\","
    "\"state_topic\":\"" TOPIC_AVAIL "\",\"payload_on\":\"online\","
    "\"payload_off\":\"offline\",\"device_class\":\"connectivity\","
    "\"entity_category\":\"diagnostic\"," DEVICE_JSON "}";

static const char *DISC_LAST_COMPLETED_TOPIC =
    "homeassistant/sensor/taskpad/last_completed/config";
static const char *DISC_LAST_COMPLETED =
    "{\"name\":\"Last completed task\",\"unique_id\":\"taskpad_last_completed\","
    "\"state_topic\":\"" TOPIC_COMPLETE "\","
    "\"value_template\":\"{{ value_json.task_id }}\","
    "\"icon\":\"mdi:check-circle-outline\","
    "\"availability_topic\":\"" TOPIC_AVAIL "\"," DEVICE_JSON "}";

static esp_mqtt_client_handle_t s_client;
static QueueHandle_t s_queue;

static SemaphoreHandle_t s_lock;
static task_item_t s_tasks[TASKS_MAX]; // raw list as published by HA
static size_t s_count;

static char s_payload[TASKS_PAYLOAD_MAX]; // reassembly buffer for TOPIC_TASKS

static void post_event(app_event_t evt)
{
    xQueueSend(s_queue, &evt, 0);
}

// Days from today to a "YYYY-MM-DD" date in local time. Comparing at noon
// sidesteps DST-shift off-by-one errors.
static int days_from_today(const char *ymd)
{
    int y, m, d;
    if (sscanf(ymd, "%d-%d-%d", &y, &m, &d) != 3) {
        return INT32_MAX;
    }
    struct tm due = {
        .tm_year = y - 1900,
        .tm_mon = m - 1,
        .tm_mday = d,
        .tm_hour = 12,
        .tm_isdst = -1,
    };
    time_t due_t = mktime(&due);

    time_t now = time(NULL);
    struct tm today;
    localtime_r(&now, &today);
    today.tm_hour = 12;
    today.tm_min = 0;
    today.tm_sec = 0;
    today.tm_isdst = -1;
    time_t today_t = mktime(&today);

    return (int)llround(difftime(due_t, today_t) / 86400.0);
}

static void parse_tasks(const char *json)
{
    cJSON *root = cJSON_Parse(json);
    if (!cJSON_IsArray(root)) {
        ESP_LOGE(TAG, "task payload is not a JSON array");
        cJSON_Delete(root);
        return;
    }

    task_item_t parsed[TASKS_MAX];
    size_t count = 0;
    cJSON *t;
    cJSON_ArrayForEach(t, root) {
        if (count >= TASKS_MAX) {
            break;
        }
        cJSON *id = cJSON_GetObjectItem(t, "id");
        cJSON *name = cJSON_GetObjectItem(t, "name");
        cJSON *due = cJSON_GetObjectItem(t, "due");
        if (!cJSON_IsString(id) || !cJSON_IsString(name) ||
            !cJSON_IsString(due)) {
            continue;
        }
        task_item_t *item = &parsed[count++];
        snprintf(item->id, sizeof(item->id), "%s", id->valuestring);
        snprintf(item->name, sizeof(item->name), "%s", name->valuestring);
        snprintf(item->due, sizeof(item->due), "%s", due->valuestring);
        item->days_left = 0; // computed at read time
        item->blocked = cJSON_IsTrue(cJSON_GetObjectItem(t, "blocked"));
    }
    cJSON_Delete(root);

    xSemaphoreTake(s_lock, portMAX_DELAY);
    memcpy(s_tasks, parsed, count * sizeof(task_item_t));
    s_count = count;
    xSemaphoreGive(s_lock);

    ESP_LOGI(TAG, "task list updated: %u tasks", (unsigned)count);
    post_event(APP_EVT_TASKS_UPDATED);
}

static void on_mqtt_event(void *arg, esp_event_base_t base, int32_t event_id,
                          void *event_data)
{
    esp_mqtt_event_handle_t evt = event_data;

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        esp_mqtt_client_publish(s_client, TOPIC_AVAIL, "online", 0, 1, true);
        esp_mqtt_client_publish(s_client, DISC_CONNECTIVITY_TOPIC,
                                DISC_CONNECTIVITY, 0, 1, true);
        esp_mqtt_client_publish(s_client, DISC_LAST_COMPLETED_TOPIC,
                                DISC_LAST_COMPLETED, 0, 1, true);
        esp_mqtt_client_subscribe(s_client, TOPIC_TASKS, 1);
        post_event(APP_EVT_CONN_UP);
        break;

    case MQTT_EVENT_DISCONNECTED:
        post_event(APP_EVT_CONN_DOWN);
        break;

    case MQTT_EVENT_PUBLISHED:
        ESP_LOGI(TAG, "publish acked by broker (msg_id=%d)", evt->msg_id);
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "mqtt error type=%d", evt->error_handle->error_type);
        break;

    case MQTT_EVENT_DATA:
        // Payloads larger than the client buffer arrive in fragments; the
        // topic is only present on the first one.
        if (evt->current_data_offset == 0 &&
            (evt->topic_len != strlen(TOPIC_TASKS) ||
             strncmp(evt->topic, TOPIC_TASKS, evt->topic_len) != 0)) {
            break;
        }
        if (evt->total_data_len >= TASKS_PAYLOAD_MAX) {
            ESP_LOGE(TAG, "task payload too large (%d bytes)",
                     evt->total_data_len);
            break;
        }
        memcpy(s_payload + evt->current_data_offset, evt->data, evt->data_len);
        if (evt->current_data_offset + evt->data_len == evt->total_data_len) {
            s_payload[evt->total_data_len] = '\0';
            parse_tasks(s_payload);
        }
        break;

    default:
        break;
    }
}

void taskpad_mqtt_start(QueueHandle_t event_queue)
{
    s_queue = event_queue;
    s_lock = xSemaphoreCreateMutex();

    const esp_mqtt_client_config_t cfg = {
        .broker.address.uri = CONFIG_TASKPAD_MQTT_URI,
        .credentials = {
            .username = strlen(CONFIG_TASKPAD_MQTT_USERNAME)
                            ? CONFIG_TASKPAD_MQTT_USERNAME
                            : NULL,
            .authentication.password = strlen(CONFIG_TASKPAD_MQTT_PASSWORD)
                                           ? CONFIG_TASKPAD_MQTT_PASSWORD
                                           : NULL,
        },
        .session.last_will = {
            .topic = TOPIC_AVAIL,
            .msg = "offline",
            .qos = 1,
            .retain = true,
        },
        .buffer.size = 4096,
    };
    s_client = esp_mqtt_client_init(&cfg);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(
        s_client, ESP_EVENT_ANY_ID, on_mqtt_event, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_client));
}

size_t taskpad_mqtt_get_tasks(task_item_t *out, size_t max)
{
    size_t n = 0;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    for (size_t i = 0; i < s_count && n < max; i++) {
        int days = days_from_today(s_tasks[i].due);
        if (days == INT32_MAX || days > CONFIG_TASKPAD_HORIZON_DAYS) {
            continue;
        }
        out[n] = s_tasks[i];
        out[n].days_left = days;
        n++;
    }
    xSemaphoreGive(s_lock);
    return n;
}

static esp_err_t publish_task_id(const char *topic, const char *task_id)
{
    char body[80];
    snprintf(body, sizeof(body), "{\"task_id\":\"%s\"}", task_id);
    int msg_id = esp_mqtt_client_publish(s_client, topic, body, 0, 1, false);
    ESP_LOGI(TAG, "publish to %s %s: %s (msg_id=%d)", topic,
             msg_id >= 0 ? "enqueued" : "FAILED", body, msg_id);
    return msg_id >= 0 ? ESP_OK : ESP_FAIL;
}

esp_err_t taskpad_mqtt_publish_complete(const char *task_id)
{
    return publish_task_id(TOPIC_COMPLETE, task_id);
}

esp_err_t taskpad_mqtt_publish_blocked(const char *task_id)
{
    return publish_task_id(TOPIC_BLOCKED, task_id);
}
