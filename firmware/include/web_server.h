#pragma once

#include <Arduino.h>

// Initialize the async web server and WebSocket.
void web_init();

// Send a run result to all connected WebSocket clients as JSON.
// Call this when a measurement completes.
void web_send_result();

// Send current status to all connected WebSocket clients.
void web_send_status();
