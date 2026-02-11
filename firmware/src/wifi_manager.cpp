#include "wifi_manager.h"
#include "config.h"
#include <WiFi.h>
#include <DNSServer.h>
#include <Preferences.h>

static Preferences prefs;
static DNSServer dnsServer;
static bool staMode = false;
static bool dnsRunning = false;

void wifi_init() {
    // Try to load saved credentials
    prefs.begin(WIFI_NVS_NAMESPACE, true);  // read-only
    String ssid = prefs.getString("ssid", "");
    String pass = prefs.getString("pass", "");
    prefs.end();

    if (ssid.length() > 0) {
        // Attempt STA connection
        Serial.printf("WiFi: Connecting to '%s'...\n", ssid.c_str());
        WiFi.mode(WIFI_STA);
        WiFi.begin(ssid.c_str(), pass.c_str());

        unsigned long start = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_STA_TIMEOUT) {
            delay(250);
            Serial.print(".");
        }
        Serial.println();

        if (WiFi.status() == WL_CONNECTED) {
            staMode = true;
            Serial.printf("WiFi: Connected! IP: %s\n", WiFi.localIP().toString().c_str());
            return;
        }
        Serial.println("WiFi: STA connection failed, falling back to AP.");
    }

    // Start AP mode
    WiFi.mode(WIFI_AP);
    WiFi.softAP(WIFI_AP_SSID);
    staMode = false;

    // Start DNS for captive portal
    dnsServer.start(53, "*", WiFi.softAPIP());
    dnsRunning = true;

    Serial.printf("WiFi: AP mode, SSID='%s', IP: %s\n",
        WIFI_AP_SSID, WiFi.softAPIP().toString().c_str());
}

void wifi_process() {
    if (dnsRunning) {
        dnsServer.processNextRequest();
    }
}

bool wifi_is_sta() {
    return staMode;
}

String wifi_get_ip() {
    return staMode ? WiFi.localIP().toString() : WiFi.softAPIP().toString();
}

String wifi_get_ssid() {
    return staMode ? WiFi.SSID() : String(WIFI_AP_SSID);
}

void wifi_save_and_connect(const String& ssid, const String& password) {
    prefs.begin(WIFI_NVS_NAMESPACE, false);
    prefs.putString("ssid", ssid);
    prefs.putString("pass", password);
    prefs.end();
    Serial.printf("WiFi: Credentials saved for '%s'. Rebooting...\n", ssid.c_str());
    delay(500);
    ESP.restart();
}

void wifi_clear_and_reboot() {
    prefs.begin(WIFI_NVS_NAMESPACE, false);
    prefs.clear();
    prefs.end();
    Serial.println("WiFi: Credentials cleared. Rebooting to AP mode...");
    delay(500);
    ESP.restart();
}
