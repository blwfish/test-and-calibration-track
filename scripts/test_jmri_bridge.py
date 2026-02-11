#!/usr/bin/env python3
"""
Tests for JMRI bridge MQTT protocol layer.

Tests the Python client side (LocoController roster/CV/import methods)
using a mock MQTT bridge that simulates the JMRI side. Also tests the
JMRI config reader.

Does NOT require JMRI or a real MQTT broker — uses threading to
simulate pub/sub in-process.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jmri_config import (
    JmriMqttConfig, find_profile_xmls, read_mqtt_config,
    _parse_mqtt_connection, _read_mqtt_from_profile,
)


class TestJmriMqttConfig(unittest.TestCase):
    """Tests for jmri_config.py — JMRI profile XML parsing."""

    def _write_profile(self, content):
        """Write a profile.xml to a temp dir and return its path."""
        tmpdir = tempfile.mkdtemp()
        profile_dir = os.path.join(tmpdir, "profile", "abc-uuid")
        os.makedirs(profile_dir)
        path = os.path.join(profile_dir, "profile.xml")
        with open(path, "w") as f:
            f.write(content)
        self._tmpdirs.append(tmpdir)
        return tmpdir

    def setUp(self):
        self._tmpdirs = []

    def tearDown(self):
        import shutil
        for d in self._tmpdirs:
            shutil.rmtree(d, ignore_errors=True)

    def test_parse_mqtt_connection_basic(self):
        """Parse a <connection> element with broker and port."""
        import xml.etree.ElementTree as ET
        xml = '''<connection class="jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"
                   address="192.168.1.50" port="1883" disabled="no">
                   <options>
                     <option><name>0 MQTTchannel</name><value>/trains</value></option>
                   </options>
                 </connection>'''
        elem = ET.fromstring(xml)
        config = _parse_mqtt_connection(elem)
        self.assertEqual(config.broker, "192.168.1.50")
        self.assertEqual(config.port, 1883)
        self.assertEqual(config.channel, "/trains")

    def test_parse_mqtt_connection_defaults(self):
        """Missing attributes use defaults."""
        import xml.etree.ElementTree as ET
        xml = '<connection class="jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"><options/></connection>'
        elem = ET.fromstring(xml)
        config = _parse_mqtt_connection(elem)
        self.assertEqual(config.broker, "localhost")
        self.assertEqual(config.port, 1883)
        self.assertEqual(config.channel, "")

    def test_parse_blank_channel(self):
        """Blank channel prefix (common JMRI default)."""
        import xml.etree.ElementTree as ET
        xml = '''<connection class="jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"
                   address="10.0.0.5" port="1883">
                   <options>
                     <option><name>0 MQTTchannel</name><value></value></option>
                   </options>
                 </connection>'''
        elem = ET.fromstring(xml)
        config = _parse_mqtt_connection(elem)
        self.assertEqual(config.channel, "")

    def test_read_mqtt_from_profile_xml(self):
        """Read MQTT config from a complete profile.xml file."""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<auxiliary-configuration xmlns="http://www.netbeans.org/ns/auxiliary-configuration/1">
    <connections xmlns="http://jmri.org/xml/schema/auxiliary-configuration/connections-2-9-6.xsd">
        <connection xmlns="" class="jmri.jmrix.SerialDriverAdapter" disabled="no"
                    manufacturer="SPROG" systemPrefix="S" userName="SPROG"/>
        <connection xmlns="" class="jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"
                    address="192.168.68.250" port="1883" disabled="no"
                    manufacturer="MQTT" systemPrefix="M" userName="MQTT">
            <options>
                <option><name>0 MQTTchannel</name><value>/cova</value></option>
            </options>
        </connection>
    </connections>
</auxiliary-configuration>'''
        tmpdir = self._write_profile(xml)
        config = read_mqtt_config(tmpdir)
        self.assertIsNotNone(config)
        self.assertEqual(config.broker, "192.168.68.250")
        self.assertEqual(config.port, 1883)
        self.assertEqual(config.channel, "/cova")

    def test_read_mqtt_skips_disabled(self):
        """Disabled MQTT connections are ignored."""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<auxiliary-configuration xmlns="http://www.netbeans.org/ns/auxiliary-configuration/1">
    <connections xmlns="http://jmri.org/xml/schema/auxiliary-configuration/connections-2-9-6.xsd">
        <connection xmlns="" class="jmri.jmrix.mqtt.configurexml.MqttConnectionConfigXml"
                    address="10.0.0.1" port="1883" disabled="yes">
            <options/>
        </connection>
    </connections>
</auxiliary-configuration>'''
        tmpdir = self._write_profile(xml)
        config = read_mqtt_config(tmpdir)
        self.assertIsNone(config)

    def test_read_mqtt_no_mqtt_connection(self):
        """Profile with no MQTT connection returns None."""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<auxiliary-configuration xmlns="http://www.netbeans.org/ns/auxiliary-configuration/1">
    <connections xmlns="http://jmri.org/xml/schema/auxiliary-configuration/connections-2-9-6.xsd">
        <connection xmlns="" class="jmri.jmrix.loconet.hexfile.configurexml.ConnectionConfigXml"
                    disabled="no" manufacturer="Digitrax" systemPrefix="L" userName="LocoNet">
            <options/>
        </connection>
    </connections>
</auxiliary-configuration>'''
        tmpdir = self._write_profile(xml)
        config = read_mqtt_config(tmpdir)
        self.assertIsNone(config)

    def test_read_mqtt_empty_dir(self):
        """Empty directory returns None."""
        tmpdir = tempfile.mkdtemp()
        self._tmpdirs.append(tmpdir)
        config = read_mqtt_config(tmpdir)
        self.assertIsNone(config)

    def test_read_mqtt_nonexistent_dir(self):
        """Nonexistent directory returns None."""
        config = read_mqtt_config("/tmp/no-such-jmri-dir-12345")
        self.assertIsNone(config)

    def test_find_profile_xmls(self):
        """find_profile_xmls locates profile.xml files."""
        xml = '<?xml version="1.0"?><auxiliary-configuration/>'
        tmpdir = self._write_profile(xml)
        results = find_profile_xmls(tmpdir)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].endswith("profile.xml"))


def _ensure_paho_mock():
    """If paho-mqtt is not installed, inject a minimal mock so
    loco_control can be imported for testing."""
    try:
        import paho.mqtt.client
    except ImportError:
        import types
        paho = types.ModuleType("paho")
        paho.mqtt = types.ModuleType("paho.mqtt")

        class MockClient:
            def __init__(self, client_id="", **kwargs):
                self.on_connect = None
                self.on_message = None
                self.on_disconnect = None
            def connect(self, *a, **kw): pass
            def disconnect(self, *a, **kw): pass
            def loop_start(self): pass
            def loop_stop(self): pass
            def subscribe(self, *a, **kw): pass
            def publish(self, *a, **kw): pass

        paho.mqtt.client = types.ModuleType("paho.mqtt.client")
        paho.mqtt.client.Client = MockClient
        sys.modules["paho"] = paho
        sys.modules["paho.mqtt"] = paho.mqtt
        sys.modules["paho.mqtt.client"] = paho.mqtt.client

        # Reload loco_control so it picks up the mock
        import importlib
        if "loco_control" in sys.modules:
            importlib.reload(sys.modules["loco_control"])


_ensure_paho_mock()


class TestLocoControllerProtocol(unittest.TestCase):
    """Tests for LocoController roster/CV/import method JSON payloads.

    These tests verify the payload format and request-response correlation
    without requiring a real MQTT broker. We mock the MQTT client.
    """

    def setUp(self):
        """Set up a LocoController with a mock MQTT client."""
        from loco_control import LocoController

        self.ctrl = LocoController("localhost", 1883)
        self.published = []  # (topic, payload) tuples

        # Mock the MQTT client publish method
        def mock_publish(topic, payload=None, *args, **kwargs):
            self.published.append((topic, payload))
        self.ctrl.client.publish = mock_publish
        self.ctrl.connected = True

    def _simulate_response(self, topic, response_dict, delay=0.01):
        """Simulate a response arriving after a short delay."""
        def deliver():
            time.sleep(delay)
            payload = json.dumps(response_dict).encode("utf-8")

            class FakeMsg:
                pass
            msg = FakeMsg()
            msg.topic = topic
            msg.payload = payload
            self.ctrl._on_message(self.ctrl.client, None, msg)

        t = threading.Thread(target=deliver)
        t.daemon = True
        t.start()
        return t

    def test_query_roster_by_id_payload(self):
        """query_roster publishes correct JSON with roster_id."""
        response = {
            "request_id": "rq-1",
            "found": True,
            "entries": [{"roster_id": "SP 4449", "address": "4449",
                         "decoder_model": "LokSound 5"}]
        }
        self._simulate_response(self.ctrl.t_roster + "info", response)
        result = self.ctrl.query_roster(roster_id="SP 4449", timeout=2.0)

        # Check published payload
        self.assertEqual(len(self.published), 1)
        topic, payload_str = self.published[0]
        self.assertTrue(topic.endswith("/roster/query"))
        payload = json.loads(payload_str)
        self.assertEqual(payload["roster_id"], "SP 4449")
        self.assertIn("request_id", payload)

    def test_query_roster_by_address_payload(self):
        """query_roster publishes correct JSON with address."""
        response = {"request_id": "rq-1", "found": False,
                    "error": "not found"}
        self._simulate_response(self.ctrl.t_roster + "info", response)
        result = self.ctrl.query_roster(address=4449, timeout=2.0)

        topic, payload_str = self.published[0]
        payload = json.loads(payload_str)
        self.assertEqual(payload["address"], 4449)

    def test_query_roster_timeout(self):
        """query_roster returns None on timeout."""
        result = self.ctrl.query_roster(roster_id="ghost", timeout=0.1)
        self.assertIsNone(result)

    def test_import_speed_profile_payload(self):
        """import_speed_profile publishes correct JSON."""
        entries = [
            {"speed_step": 10, "speed_mph": 5.2, "direction": "forward"},
            {"speed_step": 10, "speed_mph": 5.0, "direction": "reverse"},
        ]
        response = {"request_id": "imp-1", "success": True,
                    "entries_imported": 2}
        self._simulate_response(
            self.ctrl.t_roster + "import_status", response)
        result = self.ctrl.import_speed_profile(
            "SP 4449", entries, scale_factor=87.1, timeout=2.0)

        topic, payload_str = self.published[0]
        self.assertTrue(topic.endswith("/roster/import_profile"))
        payload = json.loads(payload_str)
        self.assertEqual(payload["roster_id"], "SP 4449")
        self.assertEqual(payload["scale_factor"], 87.1)
        self.assertEqual(len(payload["entries"]), 2)
        self.assertTrue(payload["clear_existing"])

    def test_import_speed_profile_timeout(self):
        """import_speed_profile returns None on timeout."""
        result = self.ctrl.import_speed_profile(
            "ghost", [], timeout=0.1)
        self.assertIsNone(result)

    def test_read_cv_payload(self):
        """read_cv publishes correct JSON."""
        response = {"request_id": "cvr-1", "operation": "read",
                    "cv": 29, "value": 38, "status": "OK"}
        self._simulate_response(self.ctrl.t_cv + "result", response)
        result = self.ctrl.read_cv(29, timeout=2.0)

        topic, payload_str = self.published[0]
        self.assertTrue(topic.endswith("/cv/read"))
        payload = json.loads(payload_str)
        self.assertEqual(payload["cv"], 29)

    def test_read_cv_timeout(self):
        """read_cv returns None on timeout."""
        result = self.ctrl.read_cv(99, timeout=0.1)
        self.assertIsNone(result)

    def test_write_cv_payload(self):
        """write_cv publishes correct JSON."""
        response = {"request_id": "cvw-1", "operation": "write",
                    "cv": 63, "value": 128, "status": "OK"}
        self._simulate_response(self.ctrl.t_cv + "result", response)
        result = self.ctrl.write_cv(63, 128, timeout=2.0)

        topic, payload_str = self.published[0]
        self.assertTrue(topic.endswith("/cv/write"))
        payload = json.loads(payload_str)
        self.assertEqual(payload["cv"], 63)
        self.assertEqual(payload["value"], 128)

    def test_read_cvs_batch_payload(self):
        """read_cvs publishes batch request."""
        response = {"request_id": "cvr-1", "operation": "read_batch_complete",
                    "results": [{"cv": 1, "value": 3, "status": "OK"},
                                {"cv": 29, "value": 38, "status": "OK"}],
                    "success_count": 2, "error_count": 0}
        self._simulate_response(self.ctrl.t_cv + "result", response)
        result = self.ctrl.read_cvs([1, 29], timeout=2.0)

        topic, payload_str = self.published[0]
        payload = json.loads(payload_str)
        self.assertEqual(payload["cvs"], [1, 29])

    def test_write_cvs_batch_payload(self):
        """write_cvs publishes batch request."""
        writes = [{"cv": 3, "value": 30}, {"cv": 4, "value": 30}]
        response = {"request_id": "cvw-1", "operation": "write_batch_complete",
                    "results": [{"cv": 3, "value": 30, "status": "OK"},
                                {"cv": 4, "value": 30, "status": "OK"}],
                    "success_count": 2, "error_count": 0}
        self._simulate_response(self.ctrl.t_cv + "result", response)
        result = self.ctrl.write_cvs(writes, timeout=2.0)

        topic, payload_str = self.published[0]
        payload = json.loads(payload_str)
        self.assertEqual(len(payload["writes"]), 2)

    def test_request_id_correlation(self):
        """Concurrent requests are routed to correct waiters."""
        # Start two requests that will both be in-flight
        results = [None, None]

        def do_query_1():
            results[0] = self.ctrl.query_roster(roster_id="loco1", timeout=2.0)

        def do_query_2():
            results[1] = self.ctrl.query_roster(roster_id="loco2", timeout=2.0)

        t1 = threading.Thread(target=do_query_1)
        t2 = threading.Thread(target=do_query_2)
        t1.start()
        t2.start()

        # Wait for both publishes
        time.sleep(0.1)

        # Extract the request_ids from published messages
        self.assertEqual(len(self.published), 2)
        req1 = json.loads(self.published[0][1])
        req2 = json.loads(self.published[1][1])

        # Deliver responses (deliberately in reverse order)
        resp2 = {"request_id": req2["request_id"], "found": True,
                 "entries": [{"roster_id": "loco2"}]}
        resp1 = {"request_id": req1["request_id"], "found": True,
                 "entries": [{"roster_id": "loco1"}]}

        # Simulate responses arriving
        payload2 = json.dumps(resp2).encode()
        payload1 = json.dumps(resp1).encode()

        class FakeMsg:
            pass

        msg2 = FakeMsg()
        msg2.topic = self.ctrl.t_roster + "info"
        msg2.payload = payload2
        self.ctrl._on_message(self.ctrl.client, None, msg2)

        msg1 = FakeMsg()
        msg1.topic = self.ctrl.t_roster + "info"
        msg1.payload = payload1
        self.ctrl._on_message(self.ctrl.client, None, msg1)

        t1.join(timeout=2)
        t2.join(timeout=2)

        # Each waiter should get the correct response
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        self.assertEqual(results[0]["entries"][0]["roster_id"], "loco1")
        self.assertEqual(results[1]["entries"][0]["roster_id"], "loco2")

    def test_configurable_prefix(self):
        """LocoController uses configured prefix for all topics."""
        from loco_control import LocoController  # noqa: already mocked
        ctrl = LocoController("localhost", 1883, prefix="/myprefix/cal")
        self.assertTrue(ctrl.t_throttle.startswith("/myprefix/cal/"))
        self.assertTrue(ctrl.t_roster.startswith("/myprefix/cal/"))
        self.assertTrue(ctrl.t_cv.startswith("/myprefix/cal/"))
        self.assertTrue(ctrl.t_sensor.startswith("/myprefix/cal/"))


if __name__ == "__main__":
    unittest.main()
