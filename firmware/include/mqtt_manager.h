#pragma once

#include <Arduino.h>

// Initialize MQTT. Loads broker/prefix/name from NVS.
// Call after wifi_init().
void mqtt_init();

// Call from loop(). Handles reconnection and message processing.
void mqtt_process();

// Returns true if connected to broker.
bool mqtt_is_connected();

// Get current broker address.
String mqtt_get_broker();

// Get current topic prefix.
String mqtt_get_prefix();

// Get current device name.
String mqtt_get_name();

// Save MQTT settings to NVS and reconnect.
void mqtt_configure(const String& broker, const String& prefix, const String& name);

// Publish a speed measurement result (JSON) to {prefix}/speed-cal/{name}/result
void mqtt_publish_result(const String& json);

// Publish status (JSON) to {prefix}/speed-cal/{name}/status
void mqtt_publish_status(const String& json);

// Publish an error (JSON) to {prefix}/speed-cal/{name}/error
void mqtt_publish_error(const String& json);

// Publish load cell reading (JSON) to {prefix}/speed-cal/{name}/load
void mqtt_publish_load(const String& json);

// Publish vibration analysis (JSON) to {prefix}/speed-cal/{name}/vibration
void mqtt_publish_vibration(const String& json);

// Publish audio analysis (JSON) to {prefix}/speed-cal/{name}/audio
void mqtt_publish_audio(const String& json);

// --- Throttle bridge relay (ESP32 → JMRI via MQTT) ---

// Publish a throttle command to {prefix}/speed-cal/throttle/{suffix}
void mqtt_publish_throttle(const char* suffix, const String& payload);

// Throttle state (updated from bridge status messages)
bool mqtt_get_throttle_acquired();
int mqtt_get_throttle_address();
float mqtt_get_throttle_speed();
bool mqtt_get_throttle_is_forward();
String mqtt_get_throttle_status();
