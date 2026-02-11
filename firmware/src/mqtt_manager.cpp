#include "mqtt_manager.h"
#include "config.h"
#include "sensor_array.h"
#include "web_server.h"

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

// Build a full topic: {prefix}/speed-cal/{name}/{suffix}
static String buildTopic(const char* suffix) {
    return prefix + "/speed-cal/" + deviceName + "/" + suffix;
}

// MQTT message callback — handles arm, stop, status commands
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
    String topicStr(topic);
    String armTopic = buildTopic("arm");
    String stopTopic = buildTopic("stop");
    String statusTopic = buildTopic("status");

    if (topicStr == armTopic) {
        sensor_arm();
        Serial.println("MQTT: Armed");
        web_send_status();
        // Publish status confirmation
        mqtt_publish_status("");  // Will be filled by caller or we build it here
    } else if (topicStr == stopTopic) {
        sensor_disarm();
        Serial.println("MQTT: Disarmed");
        web_send_status();
    } else if (topicStr == statusTopic) {
        Serial.println("MQTT: Status requested");
        // Status will be published by the caller after building JSON
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

        // Subscribe to command topics
        mqttClient.subscribe(buildTopic("arm").c_str());
        mqttClient.subscribe(buildTopic("stop").c_str());
        mqttClient.subscribe(buildTopic("status").c_str());

        Serial.printf("MQTT: Subscribed to %s/{arm,stop,status}\n",
            (prefix + "/speed-cal/" + deviceName).c_str());
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
