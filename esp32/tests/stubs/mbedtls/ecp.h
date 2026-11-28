#pragma once
#include <stddef.h>
typedef enum { MBEDTLS_ECP_DP_NONE = 0, MBEDTLS_ECP_DP_SECP256R1 = 3 } mbedtls_ecp_group_id;
typedef struct mbedtls_ecp_keypair mbedtls_ecp_keypair;
int mbedtls_ecp_gen_key(mbedtls_ecp_group_id grp_id, mbedtls_ecp_keypair* key,
                        int (*f_rng)(void*, unsigned char*, size_t), void* p_rng);
