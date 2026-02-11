#include "mqtt_manager.h"
#include "config.h"
#include "sensor_array.h"
#include "web_server.h"
#include "load_cell.h"
#include "vibration.h"
#include "audio_capture.h"

#include <WiFi.h>
#include <PubSubClient.h>
#include <Preferences.h>

static WiFiClient espClient;
static PubSubClient mqttClient(espClient);
static Preferences prefs;

static String broker;
static String prefix;
static String deviceName;
static unsigned long lastReconnectAttempt = 0;

// --- Throttle state (from bridge status messages) ---
static bool throttleAcquired = false;
static int throttleAddress = 0;
static float throttleSpeed = 0.0f;
static bool throttleForward = true;
static String lastThrottleStatus = "";

// Build a full sensor topic: {prefix}/speed-cal/{name}/{suffix}
static String buildTopic(const char* suffix) {
    return prefix + "/speed-cal/" + deviceName + "/" + suffix;
}

// Build a throttle bridge topic: {prefix}/speed-cal/throttle/{suffix}
static String buildThrottleTopic(const char* suffix) {
    return prefix + "/speed-cal/" THROTTLE_TOPIC_NAME "/" + suffix;
}

// Parse bridge status messages and update local throttle state
static void parseThrottleStatus(const String& status) {
    lastThrottleStatus = status;

    if (status.startsWith("ACQUIRED")) {
        throttleAcquired = true;
        // Parse address: "ACQUIRED 3"
        int space = status.indexOf(' ');
        if (space > 0) {
            throttleAddress = status.substring(space + 1).toInt();
        }
    } else if (status.startsWith("FAILED")) {
        throttleAcquired = false;
    } else if (status.startsWith("SPEED")) {
        // "SPEED 0.500"
        int space = status.indexOf(' ');
        if (space > 0) {
            throttleSpeed = status.substring(space + 1).toFloat();
        }
    } else if (status == "FORWARD") {
        throttleForward = true;
    } else if (status == "REVERSE") {
        throttleForward = false;
    } else if (status == "STOPPED") {
        throttleSpeed = 0.0f;
    } else if (status == "ESTOPPED") {
        throttleSpeed = 0.0f;
    } else if (status.startsWith("RELEASED")) {
        throttleAcquired = false;
        throttleAddress = 0;
        throttleSpeed = 0.0f;
    } else if (status == "READY") {
        // Bridge is ready but no throttle acquired yet
    }
}

// MQTT message callback — handles sensor commands and throttle status
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
    String topicStr(topic);

    // --- Sensor command topics ---
    if (topicStr == buildTopic("arm")) {
        sensor_arm();
        Serial.println("MQTT: Armed");
        web_send_status();
        mqtt_publish_status("");
    } else if (topicStr == buildTopic("stop")) {
        sensor_disarm();
        Serial.println("MQTT: Disarmed");
        web_send_status();
    } else if (topicStr == buildTopic("status")) {
        Serial.println("MQTT: Status requested");
        web_send_status();
    } else if (topicStr == buildTopic("tare")) {
        load_cell_tare();
        Serial.println("MQTT: Tare");
        web_send_load();
    } else if (topicStr == buildTopic("load")) {
        Serial.println("MQTT: Load requested");
        web_send_load();
    } else if (topicStr == buildTopic("vibration")) {
        vibration_start_capture();
        Serial.println("MQTT: Vibration capture started");
    } else if (topicStr == buildTopic("audio")) {
        audio_start_capture();
        Serial.println("MQTT: Audio capture started");

    // --- Throttle bridge status ---
    } else if (topicStr == buildThrottleTopic("status")) {
        // Null-terminate payload
        char buf[128];
        unsigned int copyLen = length < sizeof(buf) - 1 ? length : sizeof(buf) - 1;
        memcpy(buf, payload, copyLen);
        buf[copyLen] = '\0';
        String status(buf);

        Serial.printf("MQTT: Bridge status: %s\n", status.c_str());
        parseThrottleStatus(status);
        web_send_throttle_status();
    }
}

static void mqttConnect() {
    if (broker.length() == 0) {
        return;  // No broker configured
    }

    String clientId = "speedcal-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    Serial.printf("MQTT: Connecting to %s as %s...\n", broker.c_str(), clientId.c_str());

    if (mqttClient.connect(clientId.c_str())) {
        Serial.println("MQTT: Connected!");

        // Subscribe to sensor command topics
        mqttClient.subscribe(buildTopic("arm").c_str());
        mqttClient.subscribe(buildTopic("stop").c_str());
        mqttClient.subscribe(buildTopic("status").c_str());
        mqttClient.subscribe(buildTopic("tare").c_str());
        mqttClient.subscribe(buildTopic("load").c_str());
        mqttClient.subscribe(buildTopic("vibration").c_str());
        mqttClient.subscribe(buildTopic("audio").c_str());

        // Subscribe to throttle bridge status
        mqttClient.subscribe(buildThrottleTopic("status").c_str());

        Serial.printf("MQTT: Subscribed to %s/{arm,stop,status,tare,load,vibration,audio}\n",
            (prefix + "/speed-cal/" + deviceName).c_str());
        Serial.printf("MQTT: Subscribed to %s/status\n",
            (prefix + "/speed-cal/" THROTTLE_TOPIC_NAME).c_str());
    } else {
        Serial.printf("MQTT: Connection failed, rc=%d\n", mqttClient.state());
    }
}

// --- Public API ---

void mqtt_init() {
    // Load settings from NVS
    prefs.begin(MQTT_NVS_NAMESPACE, true);
    broker = prefs.getString("broker", "");
    prefix = prefs.getString("prefix", MQTT_DEFAULT_PREFIX);
    deviceName = prefs.getString("name", MQTT_DEFAULT_NAME);
    prefs.end();

    mqttClient.setServer(broker.c_str(), MQTT_PORT);
    mqttClient.setBufferSize(MQTT_BUFFER_SIZE);
    mqttClient.setCallback(mqttCallback);

    if (broker.length() > 0) {
        Serial.printf("MQTT: Broker=%s, Prefix=%s, Name=%s\n",
            broker.c_str(), prefix.c_str(), deviceName.c_str());
        mqttConnect();
    } else {
        Serial.println("MQTT: No broker configured. Set via web UI.");
    }
}

void mqtt_process() {
    if (broker.length() == 0) {
        return;
    }

    if (!mqttClient.connected()) {
        unsigned long now = millis();
        if (now - lastReconnectAttempt > MQTT_RECONNECT_MS) {
            lastReconnectAttempt = now;
            mqttConnect();
        }
    } else {
        mqttClient.loop();
    }
}

bool mqtt_is_connected() {
    return mqttClient.connected();
}

String mqtt_get_broker() { return broker; }
String mqtt_get_prefix() { return prefix; }
String mqtt_get_name() { return deviceName; }

void mqtt_configure(const String& newBroker, const String& newPrefix, const String& newName) {
    broker = newBroker;
    prefix = newPrefix.length() > 0 ? newPrefix : String(MQTT_DEFAULT_PREFIX);
    deviceName = newName.length() > 0 ? newName : String(MQTT_DEFAULT_NAME);

    prefs.begin(MQTT_NVS_NAMESPACE, false);
    prefs.putString("broker", broker);
    prefs.putString("prefix", prefix);
    prefs.putString("name", deviceName);
    prefs.end();

    Serial.printf("MQTT: Config saved. Broker=%s, Prefix=%s, Name=%s\n",
        broker.c_str(), prefix.c_str(), deviceName.c_str());

    // Disconnect and reconnect with new settings
    mqttClient.disconnect();
    mqttClient.setServer(broker.c_str(), MQTT_PORT);
    lastReconnectAttempt = 0;  // Force immediate reconnect
}

// --- Sensor publish functions ---

void mqtt_publish_result(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("result").c_str(), json.c_str());
        Serial.println("MQTT: Published result");
    }
}

void mqtt_publish_status(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("status").c_str(), json.c_str());
    }
}

void mqtt_publish_error(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("error").c_str(), json.c_str());
    }
}

void mqtt_publish_load(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("load").c_str(), json.c_str());
    }
}

void mqtt_publish_vibration(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("vibration").c_str(), json.c_str());
    }
}

void mqtt_publish_audio(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("audio").c_str(), json.c_str());
    }
}

void mqtt_publish_pull_test(const String& json) {
    if (mqttClient.connected()) {
        mqttClient.publish(buildTopic("pull_test").c_str(), json.c_str());
    }
}

// --- Throttle bridge relay ---

void mqtt_publish_throttle(const char* suffix, const String& payload) {
    if (mqttClient.connected()) {
        String topic = buildThrottleTopic(suffix);
        mqttClient.publish(topic.c_str(), payload.c_str());
        Serial.printf("MQTT: Throttle %s: %s\n", suffix, payload.c_str());
    }
}

bool mqtt_get_throttle_acquired() { return throttleAcquired; }
int mqtt_get_throttle_address() { return throttleAddress; }
float mqtt_get_throttle_speed() { return throttleSpeed; }
bool mqtt_get_throttle_is_forward() { return throttleForward; }
String mqtt_get_throttle_status() { return lastThrottleStatus; }
