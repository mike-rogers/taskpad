#pragma once

#define TASKS_MAX 16

typedef struct {
    char id[40];    // HA to-do item uid (a 36-char UUID)
    char name[64];  // human-readable name
    char due[11];   // "YYYY-MM-DD"
    int days_left;  // negative = overdue
} task_item_t;
