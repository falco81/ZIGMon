// ZIGMon ESP32 Gateway - the TLS certificate: generated on the device on first boot.
//
// EC P-256 key + self-signed X.509 v3 certificate (CN zigmon-gw-<mac tail>, 20 years), made
// with mbedTLS and kept in NVS. ZIGMon pins its SHA-256 fingerprint at pairing time.
#pragma once

#include <Arduino.h>

namespace gw {
namespace cert {

// Loads the certificate from NVS, or generates and saves a new one (takes ~1-3 s).
bool ensure();

// PEM buffers for esp_https_server, NUL included in the lengths (mbedTLS wants that).
const uint8_t* certPem();
size_t certPemLen();
const uint8_t* keyPem();
size_t keyPemLen();

// SHA-256 of the DER certificate, 64 lowercase hex.
const char* fingerprint();
// The same, grouped "AB:CD:..." for humans comparing two screens.
String fingerprintPretty();

}  // namespace cert
}  // namespace gw
