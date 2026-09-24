#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"

#include "input.h"
#include "events.h"

#define POLL_MS 10
#define DEBOUNCE_TICKS 3 // consecutive polls a level must hold
#define LONG_PRESS_TICKS (1500 / POLL_MS)

typedef struct {
    int pin;
    app_event_t press_event;
    app_event_t long_press_event;
    bool has_long;
    int held;
    bool consumed; // long-press already fired for this hold
} button_t;

static button_t s_buttons[] = {
    {
        .pin = CONFIG_TASKPAD_PIN_BTN_DOWN,
        .press_event = APP_EVT_BTN_DOWN,
    },
    {
        .pin = CONFIG_TASKPAD_PIN_BTN_DONE,
        .press_event = APP_EVT_BTN_DONE,
        .long_press_event = APP_EVT_BTN_DONE_LONG,
        .has_long = true,
    },
};

static QueueHandle_t s_queue;

static void input_task(void *arg)
{
    for (;;) {
        for (size_t i = 0; i < sizeof(s_buttons) / sizeof(s_buttons[0]); i++) {
            button_t *b = &s_buttons[i];
            if (gpio_get_level(b->pin) == 0) { // active low
                b->held++;
                if (!b->has_long) {
                    // No long-press variant: fire immediately on debounce.
                    if (b->held == DEBOUNCE_TICKS) {
                        xQueueSend(s_queue, &b->press_event, 0);
                    }
                } else if (b->held == LONG_PRESS_TICKS && !b->consumed) {
                    b->consumed = true;
                    xQueueSend(s_queue, &b->long_press_event, 0);
                }
            } else {
                // With a long-press variant, the short press fires on release
                // so the two can be distinguished.
                if (b->has_long && !b->consumed && b->held >= DEBOUNCE_TICKS) {
                    xQueueSend(s_queue, &b->press_event, 0);
                }
                b->held = 0;
                b->consumed = false;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

void input_init(QueueHandle_t event_queue)
{
    s_queue = event_queue;

    uint64_t mask = 0;
    for (size_t i = 0; i < sizeof(s_buttons) / sizeof(s_buttons[0]); i++) {
        mask |= 1ULL << s_buttons[i].pin;
    }
    gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));

    xTaskCreate(input_task, "input", 2048, NULL, 5, NULL);
}
