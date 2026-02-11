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
