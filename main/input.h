#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

// Input abstraction: today two debounced GPIO buttons posting APP_EVT_BTN_*
// events, later the Adafruit ANO rotary encoder over I2C behind the same
// events.
void input_init(QueueHandle_t event_queue);
