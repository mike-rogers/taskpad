#include <stdio.h>
#include <string.h>

#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_panel_ops.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_lvgl_port.h"
#include "lvgl.h"

#include "ui.h"

#define LCD_H_RES 240
#define LCD_V_RES 320
#define LCD_SPI_HOST SPI2_HOST
#define LCD_PIXEL_CLOCK_HZ (40 * 1000 * 1000)
#define LCD_DRAW_BUF_LINES 24 // kept modest: RAM shared with Wi-Fi + BLE

#define HEADER_H 44
#define STATUS_H 42 // two wrapped lines of the status font

static lv_obj_t *s_list;
static lv_obj_t *s_status_label;

static const char *MONTHS[] = { "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };

static lv_color_t urgency_color(int days_left)
{
    if (days_left < 0) {
        return lv_color_hex(0xE53935); // red: overdue
    }
    if (days_left <= 2) {
        return lv_color_hex(0xFB8C00); // orange: imminent
    }
    if (days_left <= 7) {
        return lv_color_hex(0xFDD835); // yellow: this week
    }
    return lv_color_hex(0x43A047); // green: comfortable
}

static void days_text(int days_left, char *buf, size_t len)
{
    if (days_left < 0) {
        snprintf(buf, len, "%dd late", -days_left);
    } else if (days_left == 0) {
        snprintf(buf, len, "today");
    } else if (days_left == 1) {
        snprintf(buf, len, "1 day");
    } else {
        snprintf(buf, len, "%d days", days_left);
    }
}

static void date_text(const char *ymd, char *buf, size_t len)
{
    int y, m, d;
    if (sscanf(ymd, "%d-%d-%d", &y, &m, &d) == 3 && m >= 1 && m <= 12) {
        snprintf(buf, len, "%s %d", MONTHS[m - 1], d);
    } else {
        snprintf(buf, len, "%s", ymd);
    }
}

static void init_panel(esp_lcd_panel_io_handle_t *io,
                       esp_lcd_panel_handle_t *panel)
{
    spi_bus_config_t bus_cfg = {
        .sclk_io_num = CONFIG_TASKPAD_PIN_SCLK,
        .mosi_io_num = CONFIG_TASKPAD_PIN_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_H_RES * LCD_DRAW_BUF_LINES * sizeof(uint16_t),
    };
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_SPI_HOST, &bus_cfg, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = CONFIG_TASKPAD_PIN_DC,
        .cs_gpio_num = CONFIG_TASKPAD_PIN_CS,
        .pclk_hz = LCD_PIXEL_CLOCK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(
        (esp_lcd_spi_bus_handle_t)LCD_SPI_HOST, &io_cfg, io));

    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = CONFIG_TASKPAD_PIN_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(*io, &panel_cfg, panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(*panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(*panel));
#if CONFIG_TASKPAD_LCD_INVERT
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(*panel, true));
#endif
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(*panel, true));

#if CONFIG_TASKPAD_PIN_BACKLIGHT >= 0
    gpio_config_t bl_cfg = {
        .pin_bit_mask = 1ULL << CONFIG_TASKPAD_PIN_BACKLIGHT,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&bl_cfg));
    gpio_set_level(CONFIG_TASKPAD_PIN_BACKLIGHT, 1);
#endif
}

static void build_screen(void)
{
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x101418), 0);

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "TaskPad");
    lv_obj_set_style_text_font(title, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(0xECEFF1), 0);
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 12, 10);

    s_list = lv_obj_create(scr);
    lv_obj_set_size(s_list, LCD_H_RES,
                    LCD_V_RES - HEADER_H - STATUS_H);
    lv_obj_set_pos(s_list, 0, HEADER_H);
    lv_obj_set_style_bg_opa(s_list, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(s_list, 0, 0);
    lv_obj_set_style_pad_all(s_list, 8, 0);
    lv_obj_set_style_pad_row(s_list, 6, 0);
    lv_obj_set_flex_flow(s_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_scrollbar_mode(s_list, LV_SCROLLBAR_MODE_OFF);

    s_status_label = lv_label_create(scr);
    lv_label_set_text(s_status_label, "");
    lv_obj_set_width(s_status_label, LCD_H_RES - 16); // wrap long messages
    lv_obj_set_style_text_align(s_status_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(s_status_label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(s_status_label, lv_color_hex(0x78909C), 0);
    lv_obj_align(s_status_label, LV_ALIGN_BOTTOM_MID, 0, -6);
}

void ui_init(void)
{
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_handle_t panel = NULL;
    init_panel(&io, &panel);

    const lvgl_port_cfg_t port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    ESP_ERROR_CHECK(lvgl_port_init(&port_cfg));

    const lvgl_port_display_cfg_t disp_cfg = {
        .io_handle = io,
        .panel_handle = panel,
        .buffer_size = LCD_H_RES * LCD_DRAW_BUF_LINES,
        .double_buffer = true,
        .hres = LCD_H_RES,
        .vres = LCD_V_RES,
        .monochrome = false,
        .color_format = LV_COLOR_FORMAT_RGB565,
        .rotation = {
            .swap_xy = false,
            .mirror_x = false,
            .mirror_y = false,
        },
        .flags = {
            .buff_dma = true,
            .swap_bytes = true,
        },
    };
    lvgl_port_add_disp(&disp_cfg);

    lvgl_port_lock(0);
    build_screen();
    lvgl_port_unlock();
}

void ui_show_tasks(const task_item_t *tasks, size_t count, size_t selected)
{
    lvgl_port_lock(0);
    lv_obj_clean(s_list);

    if (count == 0) {
        lv_obj_t *label = lv_label_create(s_list);
        lv_label_set_text(label, "All caught up!");
        lv_obj_set_style_text_font(label, &lv_font_montserrat_20, 0);
        lv_obj_set_style_text_color(label, lv_color_hex(0x43A047), 0);
        lvgl_port_unlock();
        return;
    }

    for (size_t i = 0; i < count; i++) {
        const task_item_t *t = &tasks[i];
        // Blocked tasks render muted: they're waiting on their prep task.
        lv_color_t color = t->blocked ? lv_color_hex(0x546E7A)
                                      : urgency_color(t->days_left);
        lv_color_t name_color = t->blocked ? lv_color_hex(0x90A4AE)
                                           : lv_color_hex(0xECEFF1);

        lv_obj_t *row = lv_obj_create(s_list);
        lv_obj_set_size(row, LV_PCT(100), 56);
        lv_obj_set_style_bg_color(row, lv_color_hex(0x1C232B), 0);
        lv_obj_set_style_radius(row, 8, 0);
        lv_obj_set_style_pad_all(row, 8, 0);
        lv_obj_set_scrollbar_mode(row, LV_SCROLLBAR_MODE_OFF);
        // urgency stripe on the left edge
        lv_obj_set_style_border_color(row, color, 0);
        lv_obj_set_style_border_width(row, 4, 0);
        lv_obj_set_style_border_side(row, LV_BORDER_SIDE_LEFT, 0);
        if (i == selected) {
            lv_obj_set_style_outline_width(row, 2, 0);
            lv_obj_set_style_outline_color(row, lv_color_hex(0xECEFF1), 0);
        }

        lv_obj_t *name = lv_label_create(row);
        lv_label_set_text(name, t->name);
        lv_obj_set_size(name, 145, 40);
        lv_obj_set_style_text_font(name, &lv_font_montserrat_16, 0);
        lv_obj_set_style_text_color(name, name_color, 0);
        lv_obj_align(name, LV_ALIGN_TOP_LEFT, 0, 0);

        // Blocked rows get parentheses; the built-in fonts lack the
        // FontAwesome symbol glyphs, so plain ASCII it is.
        char buf[24];
        if (t->blocked) {
            char days_buf[16];
            days_text(t->days_left, days_buf, sizeof(days_buf));
            snprintf(buf, sizeof(buf), "(%s)", days_buf);
        } else {
            days_text(t->days_left, buf, sizeof(buf));
        }
        lv_obj_t *days = lv_label_create(row);
        lv_label_set_text(days, buf);
        lv_obj_set_style_text_font(days, &lv_font_montserrat_20, 0);
        lv_obj_set_style_text_color(days, color, 0);
        lv_obj_align(days, LV_ALIGN_TOP_RIGHT, 0, 0);

        date_text(t->due, buf, sizeof(buf));
        lv_obj_t *date = lv_label_create(row);
        lv_label_set_text(date, buf);
        lv_obj_set_style_text_font(date, &lv_font_montserrat_14, 0);
        lv_obj_set_style_text_color(date, lv_color_hex(0x78909C), 0);
        lv_obj_align(date, LV_ALIGN_BOTTOM_RIGHT, 0, 0);

        if (i == selected) {
            lv_obj_scroll_to_view(row, LV_ANIM_OFF);
        }
    }

    lvgl_port_unlock();
}

void ui_set_status(const char *text)
{
    lvgl_port_lock(0);
    lv_label_set_text(s_status_label, text);
    lvgl_port_unlock();
}
