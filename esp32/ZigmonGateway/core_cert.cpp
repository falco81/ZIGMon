// ZIGMon ESP32 Gateway - on-device certificate generation (mbedTLS).
//
// API notes (checked against mbedTLS 2.28 = ESP-IDF 4.4 / core 2.x, 3.x = ESP-IDF 5 / core 3.x):
//  - mbedtls_x509write_crt_set_serial(mpi) is deprecated since 3.4 in favour of
//    mbedtls_x509write_crt_set_serial_raw(); both paths are below.
//  - mbedtls_pk_ec() returns the ecp keypair in both (inline function in 3.x).
//  - mbedtls_x509write_crt_pem()/mbedtls_pk_write_key_pem() have the same signatures in both.
#include "core_cert.h"

#include "mbedtls/version.h"
#include "mbedtls/bignum.h"
#include "mbedtls/ecp.h"
#include "mbedtls/pk.h"
#include "mbedtls/x509_crt.h"

#include "core_config.h"
#include "core_crypto.h"
#include "core_log.h"
#include "core_sys.h"
#include "core_util.h"

namespace gw {
namespace cert {

static String g_cert, g_key;
static char g_fp[65];

static int rng(void*, unsigned char* out, size_t n) {
  crypto::randomBytes(out, n);
  return 0;
}

static bool generate(String& certPem, String& keyPem) {
  mbedtls_pk_context key;
  mbedtls_x509write_cert crt;
  mbedtls_pk_init(&key);
  mbedtls_x509write_crt_init(&crt);
  bool ok = false;
  const size_t BUF = 1600;
  unsigned char* buf = (unsigned char*)malloc(BUF);
  char subject[64];
  snprintf(subject, sizeof subject, "CN=zigmon-gw-%s,O=ZIGMon", macTail());
  int rc;
  do {
    if (!buf) break;
    if ((rc = mbedtls_pk_setup(&key, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY))) != 0) break;
    if ((rc = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, mbedtls_pk_ec(key), rng, nullptr)) != 0) break;

    mbedtls_x509write_crt_set_version(&crt, MBEDTLS_X509_CRT_VERSION_3);
    mbedtls_x509write_crt_set_md_alg(&crt, MBEDTLS_MD_SHA256);
    mbedtls_x509write_crt_set_subject_key(&crt, &key);
    mbedtls_x509write_crt_set_issuer_key(&crt, &key);  // self-signed
    if ((rc = mbedtls_x509write_crt_set_subject_name(&crt, subject)) != 0) break;
    if ((rc = mbedtls_x509write_crt_set_issuer_name(&crt, subject)) != 0) break;

    unsigned char serial[16];
    crypto::randomBytes(serial, sizeof serial);
    serial[0] &= 0x7F;  // positive
    serial[0] |= 0x01;  // and no leading zero byte
#if MBEDTLS_VERSION_NUMBER >= 0x03040000
    if ((rc = mbedtls_x509write_crt_set_serial_raw(&crt, serial, sizeof serial)) != 0) break;
#else
    {
      mbedtls_mpi s;
      mbedtls_mpi_init(&s);
      rc = mbedtls_mpi_read_binary(&s, serial, sizeof serial);
      if (rc == 0) rc = mbedtls_x509write_crt_set_serial(&crt, &s);
      mbedtls_mpi_free(&s);
      if (rc != 0) break;
    }
#endif
    // The clock is usually not set on first boot, so the validity is fixed: 2025 + 20 years.
    if ((rc = mbedtls_x509write_crt_set_validity(&crt, "20250101000000", "20450101000000")) != 0) break;
    if ((rc = mbedtls_x509write_crt_set_basic_constraints(&crt, 0, -1)) != 0) break;
    if ((rc = mbedtls_x509write_crt_set_key_usage(
             &crt, MBEDTLS_X509_KU_DIGITAL_SIGNATURE | MBEDTLS_X509_KU_KEY_AGREEMENT)) != 0) break;

    memset(buf, 0, BUF);
    if ((rc = mbedtls_x509write_crt_pem(&crt, buf, BUF, rng, nullptr)) != 0) break;
    certPem = (const char*)buf;
    memset(buf, 0, BUF);
    if ((rc = mbedtls_pk_write_key_pem(&key, buf, BUF)) != 0) break;
    keyPem = (const char*)buf;
    ok = true;
  } while (false);
  if (!ok) LOGE("cert", "generation failed (mbedTLS -0x%04x)", (unsigned)(-rc));
  if (buf) {
    secureZero(buf, BUF);
    free(buf);
  }
  mbedtls_x509write_crt_free(&crt);
  mbedtls_pk_free(&key);
  return ok;
}

static bool computeFingerprint() {
  mbedtls_x509_crt crt;
  mbedtls_x509_crt_init(&crt);
  int rc = mbedtls_x509_crt_parse(&crt, (const unsigned char*)g_cert.c_str(), g_cert.length() + 1);
  bool ok = rc == 0 && crt.raw.p && crt.raw.len;
  if (ok) {
    uint8_t h[32];
    crypto::sha256(crt.raw.p, crt.raw.len, h);
    toHex(h, 32, g_fp);
  }
  mbedtls_x509_crt_free(&crt);
  return ok;
}

bool ensure() {
  if (config::loadCert(g_cert, g_key) && computeFingerprint()) {
    LOGI("cert", "certificate loaded");
    return true;
  }
  LOGI("cert", "generating an EC P-256 key and a self-signed certificate...");
  uint32_t t0 = millis();
  if (!generate(g_cert, g_key)) return false;
  if (!computeFingerprint()) {
    LOGE("cert", "the generated certificate does not parse");
    return false;
  }
  if (!config::saveCert(g_cert, g_key)) LOGE("cert", "could not save the certificate to NVS");
  LOGI("cert", "done in %lu ms", (unsigned long)(millis() - t0));
  return true;
}

const uint8_t* certPem() { return (const uint8_t*)g_cert.c_str(); }
size_t certPemLen() { return g_cert.length() + 1; }
const uint8_t* keyPem() { return (const uint8_t*)g_key.c_str(); }
size_t keyPemLen() { return g_key.length() + 1; }
const char* fingerprint() { return g_fp; }

String fingerprintPretty() {
  String s;
  s.reserve(96);
  for (int i = 0; i < 64; i += 2) {
    if (i) s += ':';
    s += (char)toupper(g_fp[i]);
    s += (char)toupper(g_fp[i + 1]);
  }
  return s;
}

}  // namespace cert
}  // namespace gw
