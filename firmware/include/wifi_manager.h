#pragma once

#include <Arduino.h>

// Initialize WiFi. Tries STA mode with saved credentials, falls back to AP.
void wifi_init();

// Call from loop() to handle DNS (captive portal in AP mode).
void wifi_process();

// Get current mode: true = STA (connected to network), false = AP.
bool wifi_is_sta();

// Get IP address as string.
String wifi_get_ip();

// Get SSID (connected network in STA, or AP name).
String wifi_get_ssid();

// Save new credentials and reboot into STA mode.
void wifi_save_and_connect(const String& ssid, const String& password);

// Clear saved credentials and reboot into AP mode.
void wifi_clear_and_reboot();
