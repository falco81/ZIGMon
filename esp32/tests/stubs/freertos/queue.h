#pragma once
#include "FreeRTOS.h"
typedef struct QueueDefinition* QueueHandle_t;
QueueHandle_t xQueueCreate(UBaseType_t length, UBaseType_t itemSize);
BaseType_t xQueueSend(QueueHandle_t, const void* item, TickType_t wait);
BaseType_t xQueueReceive(QueueHandle_t, void* item, TickType_t wait);
BaseType_t xQueueReset(QueueHandle_t);
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t);
