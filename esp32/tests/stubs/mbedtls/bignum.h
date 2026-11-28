#pragma once
#include <stddef.h>
typedef struct mbedtls_mpi { int s; size_t n; void* p; } mbedtls_mpi;
void mbedtls_mpi_init(mbedtls_mpi* X);
void mbedtls_mpi_free(mbedtls_mpi* X);
int mbedtls_mpi_read_binary(mbedtls_mpi* X, const unsigned char* buf, size_t buflen);
