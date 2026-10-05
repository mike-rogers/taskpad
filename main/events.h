#pragma once

// Application events, delivered to the main control loop's queue.
typedef enum {
    APP_EVT_BTN_DOWN,      // move selection to the next task
    APP_EVT_BTN_UP,        // move selection to the previous task
    APP_EVT_BTN_DONE,      // complete the selected task
    APP_EVT_BTN_DONE_LONG, // mark the selected task blocked (needs prep)
    APP_EVT_TASKS_UPDATED, // new task list arrived over MQTT
    APP_EVT_CONN_UP,       // MQTT connected
    APP_EVT_CONN_DOWN,     // MQTT disconnected
} app_event_t;
