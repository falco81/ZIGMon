#pragma once
#include "FreeRTOS.h"
typedef struct tskTaskControlBlock* TaskHandle_t;
typedef void (*TaskFunction_t)(void*);
BaseType_t xTaskCreate(TaskFunction_t fn, const char* name, uint32_t stackDepth, void* param,
                       UBaseType_t prio, TaskHandle_t* created);
BaseType_t xTaskCreatePinnedToCore(TaskFunction_t fn, const char* name, uint32_t stackDepth, void* param,
                                   UBaseType_t prio, TaskHandle_t* created, BaseType_t core);
void vTaskDelete(TaskHandle_t);
BaseType_t xTaskNotifyGive(TaskHandle_t);
uint32_t ulTaskNotifyTake(BaseType_t clearOnExit, TickType_t wait);
void vTaskDelay(TickType_t);
