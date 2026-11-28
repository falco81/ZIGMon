// ZIGMon ESP32 Gateway - the Yeelock module: Xiaomi Yeelock BLE locks, several per gateway.
#pragma once

#include "core_module.h"

namespace gw {

// The one instance, registered in ZigmonGateway.ino.
Module* yeelockModule();

}  // namespace gw
