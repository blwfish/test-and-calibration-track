#!/usr/bin/env python3
"""
JMRI Configuration Reader

Reads MQTT broker address, port, and channel prefix from JMRI's profile
XML files, so the calibration scripts don't need manual --broker/--prefix
flags.

JMRI stores connection config in:
  ~/.jmri/<profile>/profile/<uuid>/profile.xml

The MQTT connection element looks like:
  <connection class="jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"
              address="192.168.68.250" port="1883" ...>
    <options>
      <option><name>0 MQTTchannel</name><value>/cova</value></option>
    </options>
  </connection>
"""

import os
import xml.etree.ElementTree as ET


# Default JMRI user directory
DEFAULT_JMRI_DIR = os.path.expanduser("~/.jmri")

# MQTT connection class identifier in JMRI XML
MQTT_CONFIG_CLASS = "jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"


class JmriMqttConfig:
    """MQTT connection settings extracted from JMRI profile XML."""

    def __init__(self, broker="localhost", port=1883, channel=""):
        self.broker = broker
        self.port = port
        self.channel = channel  # JMRI's "MQTTchannel" prefix (often blank)

    def __repr__(self):
        return (f"JmriMqttConfig(broker={self.broker!r}, port={self.port}, "
                f"channel={self.channel!r})")


def find_profile_xmls(jmri_dir=None):
    """Find all profile.xml files under the JMRI user directory.

    Returns list of absolute paths, newest first.
    """
    jmri_dir = jmri_dir or DEFAULT_JMRI_DIR
    jmri_dir = os.path.expanduser(jmri_dir)

    if not os.path.isdir(jmri_dir):
        return []

    results = []
    for root, dirs, files in os.walk(jmri_dir):
        for f in files:
            if f == "profile.xml":
                results.append(os.path.join(root, f))

    # Sort by modification time, newest first
    results.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return results


def _parse_mqtt_connection(connection_elem):
    """Extract MQTT config from a <connection> XML element."""
    broker = connection_elem.get("address", "localhost")
    port_str = connection_elem.get("port", "1883")
    try:
        port = int(port_str)
    except ValueError:
        port = 1883

    channel = ""
    options = connection_elem.find("options")
    if options is not None:
        for option in options.findall("option"):
            name_elem = option.find("name")
            value_elem = option.find("value")
            if name_elem is not None and name_elem.text == "0 MQTTchannel":
                channel = value_elem.text if value_elem is not None and value_elem.text else ""
                break

    return JmriMqttConfig(broker=broker, port=port, channel=channel)


def read_mqtt_config(jmri_dir=None):
    """Read MQTT connection config from the most recent JMRI profile.

    Searches profile.xml files for an MQTT connection element.
    Returns JmriMqttConfig or None if not found.
    """
    for profile_path in find_profile_xmls(jmri_dir):
        config = _read_mqtt_from_profile(profile_path)
        if config is not None:
            return config
    return None


def _read_mqtt_from_profile(profile_path):
    """Parse a single profile.xml for MQTT connection config."""
    try:
        tree = ET.parse(profile_path)
    except (ET.ParseError, OSError):
        return None

    root = tree.getroot()

    # The XML uses namespaces; connection elements have xmlns=""
    # which means they're in the default (no) namespace. We need to
    # search with and without namespace prefixes.
    for connection in root.iter("connection"):
        config_class = connection.get("class", "")
        if MQTT_CONFIG_CLASS in config_class:
            disabled = connection.get("disabled", "no")
            if disabled.lower() == "yes":
                continue
            return _parse_mqtt_connection(connection)

    # Also try with namespace-aware search
    for elem in root.iter():
        if elem.tag.endswith("connection") or elem.tag == "connection":
            config_class = elem.get("class", "")
            if MQTT_CONFIG_CLASS in config_class:
                disabled = elem.get("disabled", "no")
                if disabled.lower() == "yes":
                    continue
                return _parse_mqtt_connection(elem)

    return None


if __name__ == "__main__":
    # Quick test: print whatever we find
    config = read_mqtt_config()
    if config:
        print(f"Found JMRI MQTT config: {config}")
    else:
        print("No JMRI MQTT configuration found.")
        print(f"Searched in: {DEFAULT_JMRI_DIR}")
        profiles = find_profile_xmls()
        if profiles:
            print(f"Found {len(profiles)} profile.xml files but none had MQTT connections")
        else:
            print("No profile.xml files found")
