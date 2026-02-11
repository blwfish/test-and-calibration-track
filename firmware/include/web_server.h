#pragma once

#include <Arduino.h>

// Initialize the async web server and WebSocket.
void web_init();

// Send a run result to all connected WebSocket clients as JSON.
// Call this when a measurement completes.
void web_send_result();

// Send current status to all connected WebSocket clients.
void web_send_status();

// Send load cell reading to WebSocket clients and MQTT.
void web_send_load();

// Send vibration analysis to WebSocket clients and MQTT.
void web_send_vibration();

// Send audio analysis to WebSocket clients and MQTT.
void web_send_audio();

// Send throttle bridge status to WebSocket clients.
void web_send_throttle_status();

// Send pull test results to WebSocket clients and MQTT.
void web_send_pull_test();

// Send pull test progress to WebSocket clients.
void web_send_pull_progress();
