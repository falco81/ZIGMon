#pragma once
#include <stddef.h>
typedef enum { MBEDTLS_MD_NONE = 0, MBEDTLS_MD_SHA1 = 5, MBEDTLS_MD_SHA256 = 9 } mbedtls_md_type_t;
typedef struct mbedtls_md_info_t mbedtls_md_info_t;
typedef struct mbedtls_md_context_t {
  const mbedtls_md_info_t* md_info;
  void* md_ctx;
  void* hmac_ctx;
} mbedtls_md_context_t;
const mbedtls_md_info_t* mbedtls_md_info_from_type(mbedtls_md_type_t md_type);
void mbedtls_md_init(mbedtls_md_context_t* ctx);
void mbedtls_md_free(mbedtls_md_context_t* ctx);
int mbedtls_md_setup(mbedtls_md_context_t* ctx, const mbedtls_md_info_t* md_info, int hmac);
int mbedtls_md(const mbedtls_md_info_t* md_info, const unsigned char* input, size_t ilen, unsigned char* output);
int mbedtls_md_hmac_starts(mbedtls_md_context_t* ctx, const unsigned char* key, size_t keylen);
int mbedtls_md_hmac_update(mbedtls_md_context_t* ctx, const unsigned char* input, size_t ilen);
int mbedtls_md_hmac_finish(mbedtls_md_context_t* ctx, unsigned char* output);
int mbedtls_md_hmac_reset(mbedtls_md_context_t* ctx);
int mbedtls_md_hmac(const mbedtls_md_info_t* md_info, const unsigned char* key, size_t keylen,
                    const unsigned char* input, size_t ilen, unsigned char* output);
