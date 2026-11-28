#pragma once
#include <stddef.h>
#include "ecp.h"
typedef enum { MBEDTLS_PK_NONE = 0, MBEDTLS_PK_RSA, MBEDTLS_PK_ECKEY } mbedtls_pk_type_t;
typedef struct mbedtls_pk_info_t mbedtls_pk_info_t;
typedef struct mbedtls_pk_context { const mbedtls_pk_info_t* pk_info; void* pk_ctx; } mbedtls_pk_context;
void mbedtls_pk_init(mbedtls_pk_context* ctx);
void mbedtls_pk_free(mbedtls_pk_context* ctx);
const mbedtls_pk_info_t* mbedtls_pk_info_from_type(mbedtls_pk_type_t pk_type);
int mbedtls_pk_setup(mbedtls_pk_context* ctx, const mbedtls_pk_info_t* info);
static inline mbedtls_ecp_keypair* mbedtls_pk_ec(const mbedtls_pk_context pk) { return (mbedtls_ecp_keypair*)pk.pk_ctx; }
int mbedtls_pk_write_key_pem(const mbedtls_pk_context* ctx, unsigned char* buf, size_t size);
