// stub: ESP-IDF 5 esp_https_server.h
#pragma once
#include "esp_http_server.h"
typedef enum { HTTPD_SSL_TRANSPORT_SECURE, HTTPD_SSL_TRANSPORT_INSECURE } httpd_ssl_transport_mode_t;
typedef struct httpd_ssl_config {
  httpd_config_t httpd;
  const uint8_t* servercert;
  size_t servercert_len;
  const uint8_t* cacert_pem;
  size_t cacert_len;
  const uint8_t* prvtkey_pem;
  size_t prvtkey_len;
  bool use_ecdsa_peripheral;
  uint8_t ecdsa_key_efuse_blk;
  httpd_ssl_transport_mode_t transport_mode;
  uint16_t port_secure;
  uint16_t port_insecure;
  bool session_tickets;
  bool use_secure_element;
  void* user_cb;
  void* ssl_userdata;
  void* cert_select_cb;
  const char** alpn_protos;
} httpd_ssl_config_t;
httpd_ssl_config_t httpd_ssl_config_default_stub(void);
#define HTTPD_SSL_CONFIG_DEFAULT() httpd_ssl_config_default_stub()
esp_err_t httpd_ssl_start(httpd_handle_t* handle, httpd_ssl_config_t* config);
