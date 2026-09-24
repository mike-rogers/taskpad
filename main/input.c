#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"

#include "input.h"
#include "events.h"

#define POLL_MS 10
#define DEBOUNCE_TICKS 3 // consecutive polls a level must hold

typedef struct {
    int pin;
    app_event_t event;
    int held;
    bool fired;
} button_t;

static button_t s_buttons[] = {
    { .pin = CONFIG_TASKPAD_PIN_BTN_DOWN, .event = APP_EVT_BTN_DOWN },
    { .pin = CONFIG_TASKPAD_PIN_BTN_DONE, .event = APP_EVT_BTN_DONE },
};

static QueueHandle_t s_queue;

static void input_task(void *arg)
{
    for (;;) {
        for (size_t i = 0; i < sizeof(s_buttons) / sizeof(s_buttons[0]); i++) {
            button_t *b = &s_buttons[i];
            if (gpio_get_level(b->pin) == 0) { // active low
                if (++b->held >= DEBOUNCE_TICKS && !b->fired) {
                    b->fired = true;
                    xQueueSend(s_queue, &b->event, 0);
                }
            } else {
                b->held = 0;
                b->fired = false;
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
