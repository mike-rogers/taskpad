#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

// Input abstraction: two debounced GPIO buttons plus, when one answers on
// I2C at boot, the Adafruit ANO rotary encoder, all posting the same
// APP_EVT_BTN_* events.
void input_init(QueueHandle_t event_queue);
