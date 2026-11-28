// stub: ESP-IDF 5 esp_http_client.h (the parts used)
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct esp_http_client* esp_http_client_handle_t;
typedef enum { HTTP_METHOD_GET = 0, HTTP_METHOD_POST, HTTP_METHOD_PUT } esp_http_client_method_t;
typedef struct {
  const char* url;
  const char* host;
  int port;
  const char* cert_pem;
  size_t cert_len;
  esp_http_client_method_t method;
  int timeout_ms;
  bool disable_auto_redirect;
  int buffer_size;
  int buffer_size_tx;
  void* user_data;
  bool skip_cert_common_name_check;
  const char* common_name;
  esp_err_t (*crt_bundle_attach)(void* conf);
  bool keep_alive_enable;
} esp_http_client_config_t;
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t* config);
esp_err_t esp_http_client_set_header(esp_http_client_handle_t client, const char* key, const char* value);
esp_err_t esp_http_client_open(esp_http_client_handle_t client, int write_len);
int esp_http_client_write(esp_http_client_handle_t client, const char* buffer, int len);
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t client);
int esp_http_client_get_status_code(esp_http_client_handle_t client);
int esp_http_client_read(esp_http_client_handle_t client, char* buffer, int len);
esp_err_t esp_http_client_close(esp_http_client_handle_t client);
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t client);
