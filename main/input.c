#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"

#include "input.h"
#include "events.h"
#include "ano_seesaw.h"

#define POLL_MS 10
#define DEBOUNCE_TICKS 3 // consecutive polls a level must hold
#define LONG_PRESS_TICKS (1500 / POLL_MS)

typedef struct {
    app_event_t press_event;
    app_event_t long_press_event;
    bool has_long;
    int held;
    bool consumed; // long-press already fired for this hold
} button_t;

typedef struct {
    int pin;
    button_t btn;
} gpio_button_t;

typedef struct {
    uint32_t bit;
    button_t btn;
} ano_button_t;

static gpio_button_t s_gpio_buttons[] = {
    {
        .pin = CONFIG_TASKPAD_PIN_BTN_DOWN,
        .btn = {.press_event = APP_EVT_BTN_DOWN},
    },
    {
        .pin = CONFIG_TASKPAD_PIN_BTN_DONE,
        .btn = {
            .press_event = APP_EVT_BTN_DONE,
            .long_press_event = APP_EVT_BTN_DONE_LONG,
            .has_long = true,
        },
    },
};

// The ANO's center button mirrors Done; up/down step the selection like
// the wheel does. Left/right are unassigned for now.
static ano_button_t s_ano_buttons[] = {
    {
        .bit = ANO_BTN_SELECT,
        .btn = {
            .press_event = APP_EVT_BTN_DONE,
            .long_press_event = APP_EVT_BTN_DONE_LONG,
            .has_long = true,
        },
    },
    {.bit = ANO_BTN_UP, .btn = {.press_event = APP_EVT_BTN_UP}},
    {.bit = ANO_BTN_DOWN, .btn = {.press_event = APP_EVT_BTN_DOWN}},
};

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

static QueueHandle_t s_queue;
static bool s_has_ano;

static void button_update(button_t *b, bool pressed)
{
    if (pressed) {
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

static void poll_ano(void)
{
    // On a read error, skip this poll and leave button state as it was
    // rather than inventing a release.
    uint32_t pressed;
    if (ano_seesaw_read_buttons(&pressed) == ESP_OK) {
        for (size_t i = 0; i < COUNT(s_ano_buttons); i++) {
            button_update(&s_ano_buttons[i].btn,
                          (pressed & s_ano_buttons[i].bit) != 0);
        }
    }

    // Each detent is one selection step: clockwise moves down the list.
    int32_t delta;
    if (ano_seesaw_read_delta(&delta) == ESP_OK) {
        app_event_t evt = delta > 0 ? APP_EVT_BTN_DOWN : APP_EVT_BTN_UP;
        for (int32_t n = delta > 0 ? delta : -delta; n > 0; n--) {
            xQueueSend(s_queue, &evt, 0);
        }
    }
}

static void input_task(void *arg)
{
    for (;;) {
        for (size_t i = 0; i < COUNT(s_gpio_buttons); i++) {
            button_update(&s_gpio_buttons[i].btn,
                          gpio_get_level(s_gpio_buttons[i].pin) == 0); // active low
        }
        if (s_has_ano) {
            poll_ano();
        }
        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

void input_init(QueueHandle_t event_queue)
{
    s_queue = event_queue;

    uint64_t mask = 0;
    for (size_t i = 0; i < COUNT(s_gpio_buttons); i++) {
        mask |= 1ULL << s_gpio_buttons[i].pin;
    }
    gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));

    s_has_ano = ano_seesaw_init(CONFIG_TASKPAD_PIN_I2C_SDA,
                                CONFIG_TASKPAD_PIN_I2C_SCL);

    xTaskCreate(input_task, "input", 3072, NULL, 5, NULL);
}
