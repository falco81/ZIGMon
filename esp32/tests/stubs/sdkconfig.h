// stub: the target comes from -DCONFIG_IDF_TARGET_<X>=1 (tests/run.sh)
#pragma once
#if defined(CONFIG_IDF_TARGET_ESP32S3)
#define CONFIG_IDF_TARGET "esp32s3"
#elif defined(CONFIG_IDF_TARGET_ESP32C3)
#define CONFIG_IDF_TARGET "esp32c3"
#define CONFIG_FREERTOS_UNICORE 1
#else
#define CONFIG_IDF_TARGET "esp32"
#endif
