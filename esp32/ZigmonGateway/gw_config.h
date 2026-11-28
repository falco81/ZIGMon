// ZIGMon ESP32 Gateway - compile-time configuration.
//
// Everything here is a constant of the firmware or of the contract (esp32/PROTOCOL.md).
// User settings live in NVS (see core_config.h), not here: nothing in this file is secret.
#pragma once

#include <stdint.h>
#include <stddef.h>
#if defined(ESP_PLATFORM)
#  include "esp_idf_version.h"   // ESP_IDF_VERSION_MAJOR/MINOR
#endif

#define GW_FW_VERSION        "1.0.0"
#define GW_PROTOCOL_VERSION  1

// ---- Limits (contract section 2) -------------------------------------------------------
#define GW_MAX_BODY              8192     // bytes, any request body
#define GW_MAX_TS_SKEW_S         120      // signed request clock skew while the clock is set
#define GW_REPLAY_WINDOW_S       300      // a nonce is remembered this long
#define GW_REPLAY_RING           64       // contract minimum; see core_proto.h
#define GW_CLOCK_VALID_FROM      1700000000UL  // time() below this = "clock not set"

#define GW_PAIR_CODE_TTL_S       600      // 10 minutes
#define GW_PAIR_MAX_FAILS        5
#define GW_PAIR_LOCK_S           900      // 15 minutes

#define GW_PBKDF2_ROUNDS         10000
#define GW_PBKDF2_SALT           16
#define GW_SESSION_TTL_S         (12UL * 3600UL)
#define GW_MAX_SESSIONS          4
#define GW_LOGIN_FREE_FAILS      5
#define GW_LOGIN_LOCK_BASE_S     60
#define GW_LOGIN_LOCK_MAX_S      3600
#define GW_FIRSTRUN_WINDOW_S     600      // first-run page: 10 minutes from boot / `webinit`
#define GW_PASSWORD_MIN          8
#define GW_PASSWORD_MAX          64

#define GW_EVENTS_RING           32       // events kept for /zigmon/v1/events
#define GW_EVENT_STATE_MAX       384      // bytes of serialized STATE kept per event
#define GW_LONGPOLL_MAX_WAIT_S   25
#define GW_LONGPOLL_WAITERS      2        // concurrent long polls (each holds a TLS socket)

#define GW_LOG_LINES             64
#define GW_LOG_LINE_LEN          120

#define GW_CLI_LINE_MAX          256
#define GW_CLI_MAX_ARGS          12
#define GW_FACTORY_CONFIRM_S     30

#define GW_NVS_NAMESPACE         "zgw"

// ---- HTTP server ------------------------------------------------------------------------
#define GW_HTTPS_PORT            443
#define GW_HTTP_REDIRECT_PORT    80
#define GW_HTTPD_STACK           12288
#define GW_HTTPD_MAX_SOCKETS     4        // each TLS session costs ~35-40 KB of heap

// Long polling hands a request to another task with httpd_req_async_handler_begin(), which
// ESP-IDF has since v5.1 (Arduino core 3.0+). Set to 0 to make /events answer immediately
// (ZIGMon then simply polls).
#ifndef GW_HTTPD_ASYNC
#  if defined(ESP_IDF_VERSION_MAJOR)
#    if (ESP_IDF_VERSION_MAJOR > 5) || (ESP_IDF_VERSION_MAJOR == 5 && ESP_IDF_VERSION_MINOR >= 1)
#      define GW_HTTPD_ASYNC 1
#    else
#      define GW_HTTPD_ASYNC 0
#    endif
#  else
#    define GW_HTTPD_ASYNC 0
#  endif
#endif

// ---- BLE --------------------------------------------------------------------------------
#define GW_BLE_QUEUE             8        // contract: at most 8 waiting jobs, else 409 busy
#define GW_BLE_TASK_STACK        8192
