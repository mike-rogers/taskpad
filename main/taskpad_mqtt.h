#pragma once

#include <stddef.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_err.h"

#include "tasks.h"
#include "device_cfg.h"

// Connect to the MQTT broker from the adopted (NVS) config and subscribe to
// the retained task list. Posts APP_EVT_* to the given queue. cfg must
// outlive the client (main keeps it static).
void taskpad_mqtt_start(QueueHandle_t event_queue, const device_cfg_t *cfg);

// Copy the latest task list into out, with days_left computed as of now and
// tasks beyond the configured horizon filtered out (overdue always included).
// Returns the number of tasks written.
size_t taskpad_mqtt_get_tasks(task_item_t *out, size_t max);

// Publish a completion; the TaskPad integration closes the item, creates
// its successor, and republishes the task list.
esp_err_t taskpad_mqtt_publish_complete(const char *task_id);

// Publish a block request; the integration creates a linked prep task due
// today and marks this task blocked.
esp_err_t taskpad_mqtt_publish_blocked(const char *task_id);
