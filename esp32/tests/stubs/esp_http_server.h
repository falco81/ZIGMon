// stub: ESP-IDF 5 esp_http_server.h (the parts used)
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#include "esp_err.h"
typedef void* httpd_handle_t;
typedef enum http_method { HTTP_DELETE = 0, HTTP_GET = 1, HTTP_HEAD = 2, HTTP_POST = 3, HTTP_PUT = 4 } httpd_method_t;
#define HTTPD_MAX_URI_LEN 512
typedef struct httpd_req {
  httpd_handle_t handle;
  int method;
  const char uri[HTTPD_MAX_URI_LEN + 1];
  size_t content_len;
  void* aux;
  void* user_ctx;
  void* sess_ctx;
} httpd_req_t;
typedef bool (*httpd_uri_match_func_t)(const char* reference_uri, const char* uri_to_match, size_t match_upto);
typedef struct httpd_config {
  unsigned task_priority;
  size_t stack_size;
  int core_id;
  uint16_t server_port;
  uint16_t ctrl_port;
  uint16_t max_open_sockets;
  uint16_t max_uri_handlers;
  uint16_t max_resp_headers;
  uint16_t backlog_conn;
  bool lru_purge_enable;
  uint16_t recv_wait_timeout;
  uint16_t send_wait_timeout;
  void* global_user_ctx;
  httpd_uri_match_func_t uri_match_fn;
} httpd_config_t;
httpd_config_t httpd_default_config_stub(void);
#define HTTPD_DEFAULT_CONFIG() httpd_default_config_stub()
typedef struct httpd_uri {
  const char* uri;
  httpd_method_t method;
  esp_err_t (*handler)(httpd_req_t* r);
  void* user_ctx;
} httpd_uri_t;
#define HTTPD_SOCK_ERR_FAIL -1
#define HTTPD_SOCK_ERR_INVALID -2
#define HTTPD_SOCK_ERR_TIMEOUT -3
#define HTTPD_RESP_USE_STRLEN -1
esp_err_t httpd_start(httpd_handle_t* handle, const httpd_config_t* config);
esp_err_t httpd_register_uri_handler(httpd_handle_t handle, const httpd_uri_t* uri_handler);
bool httpd_uri_match_wildcard(const char* uri_template, const char* uri_to_match, size_t match_upto);
size_t httpd_req_get_hdr_value_len(httpd_req_t* r, const char* field);
esp_err_t httpd_req_get_hdr_value_str(httpd_req_t* r, const char* field, char* val, size_t val_size);
esp_err_t httpd_req_get_url_query_str(httpd_req_t* r, char* buf, size_t buf_len);
esp_err_t httpd_query_key_value(const char* qry, const char* key, char* val, size_t val_size);
int httpd_req_recv(httpd_req_t* r, char* buf, size_t buf_len);
esp_err_t httpd_resp_set_status(httpd_req_t* r, const char* status);
esp_err_t httpd_resp_set_type(httpd_req_t* r, const char* type);
esp_err_t httpd_resp_set_hdr(httpd_req_t* r, const char* field, const char* value);
esp_err_t httpd_resp_send(httpd_req_t* r, const char* buf, ssize_t buf_len);
esp_err_t httpd_req_async_handler_begin(httpd_req_t* r, httpd_req_t** out);
esp_err_t httpd_req_async_handler_complete(httpd_req_t* r);
