#pragma once

#include <stddef.h>

#include "tasks.h"

void ui_init(void);
void ui_show_tasks(const task_item_t *tasks, size_t count, size_t selected);
void ui_set_status(const char *text);
