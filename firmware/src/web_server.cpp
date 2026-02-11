#include "web_server.h"
#include "config.h"
#include "sensor_array.h"
#include "speed_calc.h"
#include "wifi_manager.h"

#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>
#include <LittleFS.h>

static AsyncWebServer server(HTTP_PORT);
static AsyncWebSocket ws(WS_PATH);

// --- WebSocket event handler ---

static void onWsEvent(AsyncWebSocket* srv, AsyncWebSocketClient* client,
                      AwsEventType type, void* arg, uint8_t* data, size_t len) {
    if (type == WS_EVT_CONNECT) {
        Serial.printf("WS client %u connected\n", client->id());
        // Send current status on connect
        web_send_status();
    } else if (type == WS_EVT_DISCONNECT) {
        Serial.printf("WS client %u disconnected\n", client->id());
    } else if (type == WS_EVT_DATA) {
        // Parse incoming command
        AwsFrameInfo* info = (AwsFrameInfo*)arg;
        if (info->final && info->index == 0 && info->len == len && info->opcode == WS_TEXT) {
            // Null-terminate
            char cmd[64];
            size_t copyLen = len < sizeof(cmd) - 1 ? len : sizeof(cmd) - 1;
            memcpy(cmd, data, copyLen);
            cmd[copyLen] = '\0';

            JsonDocument doc;
            if (deserializeJson(doc, cmd) == DeserializationError::Ok) {
                const char* action = doc["action"];
                if (action) {
                    if (strcmp(action, "arm") == 0) {
                        sensor_arm();
                        Serial.println("WS: Armed");
                        web_send_status();
                    } else if (strcmp(action, "disarm") == 0) {
                        sensor_disarm();
                        Serial.println("WS: Disarmed");
                        web_send_status();
                    } else if (strcmp(action, "status") == 0) {
                        web_send_status();
                    }
                }
            }
        }
    }
}

// --- Build JSON payloads ---

static String buildStatusJson() {
    JsonDocument doc;
    doc["type"] = "status";
    doc["state"] = sensor_state_name(sensor_get_state());
    doc["sensors"] = NUM_SENSORS;
    doc["spacing_mm"] = SENSOR_SPACING_MM;
    doc["scale_factor"] = HO_SCALE_FACTOR;
    doc["wifi_mode"] = wifi_is_sta() ? "STA" : "AP";
    doc["ip"] = wifi_get_ip();
    doc["ssid"] = wifi_get_ssid();
    doc["uptime_ms"] = millis();

    if (sensor_get_state() == STATE_MEASURING) {
        const RunResult& r = sensor_get_result();
        doc["sensors_triggered"] = r.sensorsTriggered;
    }

    String json;
    serializeJson(doc, json);
    return json;
}

static String buildResultJson() {
    const RunResult& run = sensor_get_result();
    SpeedResult speed;
    bool hasSpeed = speed_calculate(run, speed);

    JsonDocument doc;
    doc["type"] = "result";
    doc["direction"] = (run.direction == DIR_A_TO_B) ? "A-B" :
                       (run.direction == DIR_B_TO_A) ? "B-A" : "unknown";
    doc["sensors_triggered"] = run.sensorsTriggered;
    doc["duration_ms"] = run.runDurationUs / 1000.0f;

    // Raw timestamps relative to first trigger
    uint32_t firstTs = UINT32_MAX;
    for (int i = 0; i < NUM_SENSORS; i++) {
        if (run.triggered[i] && run.timestamps[i] < firstTs) {
            firstTs = run.timestamps[i];
        }
    }
    JsonArray ts = doc["timestamps_us"].to<JsonArray>();
    JsonArray trig = doc["triggered"].to<JsonArray>();
    for (int i = 0; i < NUM_SENSORS; i++) {
        trig.add(run.triggered[i]);
        ts.add(run.triggered[i] ? (long)(run.timestamps[i] - firstTs) : -1);
    }

    if (hasSpeed) {
        JsonArray intervals = doc["intervals_us"].to<JsonArray>();
        JsonArray speeds_mms = doc["speeds_mm_s"].to<JsonArray>();
        JsonArray speeds_mph = doc["speeds_mph"].to<JsonArray>();
        for (int i = 0; i < speed.intervalCount; i++) {
            intervals.add(speed.intervalsUs[i]);
            speeds_mms.add(serialized(String(speed.intervalSpeedsMmS[i], 1)));
            speeds_mph.add(serialized(String(speed.scaleSpeedsMph[i], 1)));
        }
        doc["avg_speed_mph"] = serialized(String(speed.avgScaleSpeedMph, 1));
    }

    String json;
    serializeJson(doc, json);
    return json;
}

// --- Public API ---

void web_send_status() {
    String json = buildStatusJson();
    ws.textAll(json);
}

void web_send_result() {
    String json = buildResultJson();
    ws.textAll(json);
    // Also print to serial for debugging
    Serial.println(json);
}

void web_init() {
    // Initialize LittleFS
    if (!LittleFS.begin(true)) {
        Serial.println("ERROR: LittleFS mount failed!");
        return;
    }
    Serial.println("LittleFS mounted.");

    // WebSocket
    ws.onEvent(onWsEvent);
    server.addHandler(&ws);

    // REST API: WiFi scan
    server.on("/api/wifi/scan", HTTP_GET, [](AsyncWebServerRequest* req) {
        int n = WiFi.scanComplete();
        if (n == WIFI_SCAN_FAILED) {
            WiFi.scanNetworks(true);  // async scan
            req->send(200, "application/json", "{\"scanning\":true}");
        } else if (n == WIFI_SCAN_RUNNING) {
            req->send(200, "application/json", "{\"scanning\":true}");
        } else {
            JsonDocument doc;
            JsonArray nets = doc["networks"].to<JsonArray>();
            for (int i = 0; i < n; i++) {
                JsonObject net = nets.add<JsonObject>();
                net["ssid"] = WiFi.SSID(i);
                net["rssi"] = WiFi.RSSI(i);
                net["open"] = (WiFi.encryptionType(i) == WIFI_AUTH_OPEN);
            }
            doc["scanning"] = false;
            String json;
            serializeJson(doc, json);
            WiFi.scanDelete();
            req->send(200, "application/json", json);
        }
    });

    // REST API: WiFi connect
    server.on("/api/wifi/connect", HTTP_POST,
        [](AsyncWebServerRequest* req) {},  // no body handler needed
        NULL,
        [](AsyncWebServerRequest* req, uint8_t* data, size_t len, size_t index, size_t total) {
            JsonDocument doc;
            if (deserializeJson(doc, data, len) == DeserializationError::Ok) {
                String ssid = doc["ssid"] | "";
                String pass = doc["password"] | "";
                if (ssid.length() > 0) {
                    req->send(200, "application/json", "{\"ok\":true}");
                    wifi_save_and_connect(ssid, pass);
                } else {
                    req->send(400, "application/json", "{\"error\":\"missing ssid\"}");
                }
            } else {
                req->send(400, "application/json", "{\"error\":\"bad json\"}");
            }
        }
    );

    // REST API: WiFi disconnect (revert to AP)
    server.on("/api/wifi/disconnect", HTTP_POST, [](AsyncWebServerRequest* req) {
        req->send(200, "application/json", "{\"ok\":true}");
        wifi_clear_and_reboot();
    });

    // REST API: WiFi status
    server.on("/api/wifi/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["mode"] = wifi_is_sta() ? "STA" : "AP";
        doc["ip"] = wifi_get_ip();
        doc["ssid"] = wifi_get_ssid();
        String json;
        serializeJson(doc, json);
        req->send(200, "application/json", json);
    });

    // REST API: sensor status
    server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        req->send(200, "application/json", buildStatusJson());
    });

    // Captive portal redirects
    server.on("/generate_204", HTTP_GET, [](AsyncWebServerRequest* req) {
        req->redirect("http://" + wifi_get_ip());
    });
    server.on("/hotspot-detect.html", HTTP_GET, [](AsyncWebServerRequest* req) {
        req->redirect("http://" + wifi_get_ip());
    });

    // Serve static files from LittleFS
    server.serveStatic("/", LittleFS, "/").setDefaultFile("index.html");

    // Catch-all: redirect to index (for AP captive portal)
    server.onNotFound([](AsyncWebServerRequest* req) {
        if (!wifi_is_sta()) {
            req->redirect("http://" + wifi_get_ip());
        } else {
            req->send(404, "text/plain", "Not found");
        }
    });

    server.begin();
    Serial.printf("Web server started on port %d\n", HTTP_PORT);
}
