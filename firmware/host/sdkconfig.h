/*
 * Stands in for the sdkconfig.h an ESP-IDF build generates, with the one
 * option firmware/idf/main/ui.c reads. The on-screen keys are off by default,
 * which is the simulator's layout; the CMake option HELM_TOUCH_KEYS turns
 * them on.
 */
#ifndef HELM_HOST_SDKCONFIG_H
#define HELM_HOST_SDKCONFIG_H

#ifndef CONFIG_HELM_TOUCH_KEYS
#define CONFIG_HELM_TOUCH_KEYS 0
#endif

#endif /* HELM_HOST_SDKCONFIG_H */
