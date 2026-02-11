"""
JMRI Throttle Bridge - Jython script for JMRI

Runs inside JMRI as an AbstractAutomaton. Listens for MQTT commands
from the calibration system and translates them into DCC throttle
commands via the SPROG (or whatever command station is configured).

Prerequisites:
  - JMRI running with SPROG connection (or other DCC command station)
  - MQTT connection added in Edit > Preferences > Connections
    (same Mosquitto broker the ESP32 uses)
  - SPROG set as default for Throttle in Preferences > Defaults

To run:
  In JMRI: Scripting > Run Script > select this file

MQTT Command Topics (relative to JMRI's MQTT channel prefix):
  /cova/speed-cal/throttle/acquire   payload: "ADDRESS [L|S]"
  /cova/speed-cal/throttle/speed     payload: "0.0" to "1.0"
  /cova/speed-cal/throttle/direction payload: "FORWARD" or "REVERSE"
  /cova/speed-cal/throttle/stop      payload: (any)
  /cova/speed-cal/throttle/estop     payload: (any)
  /cova/speed-cal/throttle/function  payload: "NUM ON|OFF"
  /cova/speed-cal/throttle/release   payload: (any)

MQTT Status Topic:
  /cova/speed-cal/throttle/status    payload: state messages

Note: JMRI's MQTT adapter may prepend a channel prefix to these topics.
If your JMRI MQTT channel prefix is blank (default since 5.1.2), the
topics above are used as-is. If you have a prefix like "trains/", the
full topic would be "trains//cova/speed-cal/throttle/acquire" etc.
Set your JMRI MQTT channel prefix to blank to avoid double-prefixing.
"""

import jmri
import java

# --- Configuration ---
TOPIC_PREFIX = "/cova/speed-cal/throttle/"

# Command topics (subscribed)
TOPIC_ACQUIRE   = TOPIC_PREFIX + "acquire"
TOPIC_SPEED     = TOPIC_PREFIX + "speed"
TOPIC_DIRECTION = TOPIC_PREFIX + "direction"
TOPIC_STOP      = TOPIC_PREFIX + "stop"
TOPIC_ESTOP     = TOPIC_PREFIX + "estop"
TOPIC_FUNCTION  = TOPIC_PREFIX + "function"
TOPIC_RELEASE   = TOPIC_PREFIX + "release"

# Status topic (published)
TOPIC_STATUS    = TOPIC_PREFIX + "status"


class MqttHandler(jmri.jmrix.mqtt.MqttEventListener):
    """Receives MQTT messages and queues them for the automaton."""

    def __init__(self):
        self.pending = []  # list of (topic, message) tuples

    def notifyMqttMessage(self, topic, message):
        self.pending.append((str(topic), str(message).strip()))

    def poll(self):
        """Return and clear pending messages."""
        msgs = self.pending
        self.pending = []
        return msgs


class ThrottleBridge(jmri.jmrit.automat.AbstractAutomaton):
    """
    JMRI automaton that bridges MQTT commands to the DCC throttle.
    """

    def init(self):
        self.throttle = None
        self.currentAddress = None

        # Get the MQTT adapter
        try:
            memo = jmri.InstanceManager.getDefault(
                jmri.jmrix.mqtt.MqttSystemConnectionMemo
            )
            self.mqtt = memo.getMqttAdapter()
        except Exception as e:
            print("ThrottleBridge: ERROR - No MQTT connection configured in JMRI!")
            print("  Add MQTT connection in Edit > Preferences > Connections")
            print("  Error: " + str(e))
            return

        # Create message handler and subscribe to command topics
        self.handler = MqttHandler()
        for topic in [TOPIC_ACQUIRE, TOPIC_SPEED, TOPIC_DIRECTION,
                      TOPIC_STOP, TOPIC_ESTOP, TOPIC_FUNCTION, TOPIC_RELEASE]:
            self.mqtt.subscribe(topic, self.handler)
            print("ThrottleBridge: subscribed to " + topic)

        self.publish("READY")
        print("ThrottleBridge: ready, waiting for commands")

    def publish(self, message):
        """Publish a status message."""
        try:
            self.mqtt.publish(TOPIC_STATUS, message)
        except Exception as e:
            print("ThrottleBridge: publish error: " + str(e))

    def handle(self):
        """Called repeatedly by the automaton framework."""
        # Poll for MQTT messages
        messages = self.handler.poll()

        if not messages:
            self.waitMsec(50)
            return True

        for topic, payload in messages:
            try:
                self.processCommand(topic, payload)
            except Exception as e:
                error_msg = "ERROR " + str(e)
                print("ThrottleBridge: " + error_msg)
                self.publish(error_msg)

        return True

    def processCommand(self, topic, payload):
        """Process a single MQTT command."""

        if topic.endswith("/acquire"):
            self.doAcquire(payload)

        elif topic.endswith("/speed"):
            self.doSpeed(payload)

        elif topic.endswith("/direction"):
            self.doDirection(payload)

        elif topic.endswith("/stop"):
            self.doStop()

        elif topic.endswith("/estop"):
            self.doEstop()

        elif topic.endswith("/function"):
            self.doFunction(payload)

        elif topic.endswith("/release"):
            self.doRelease()

    def doAcquire(self, payload):
        """Acquire a throttle. Payload: 'ADDRESS [L|S]'"""
        parts = payload.split()
        if len(parts) < 1:
            self.publish("ERROR missing address")
            return

        address = int(parts[0])
        # Default: long address if >= 128, short if < 128
        if len(parts) >= 2:
            isLong = parts[1].upper() == "L"
        else:
            isLong = address >= 128

        # Release any existing throttle
        if self.throttle is not None:
            self.throttle.setSpeedSetting(0)
            self.throttle = None

        print("ThrottleBridge: acquiring throttle for %d (%s)" %
              (address, "long" if isLong else "short"))
        self.publish("ACQUIRING %d" % address)

        # getThrottle blocks until acquired or timeout (30s default)
        self.throttle = self.getThrottle(address, isLong)

        if self.throttle is not None:
            self.currentAddress = address
            self.publish("ACQUIRED %d" % address)
            print("ThrottleBridge: acquired throttle for %d" % address)
        else:
            self.publish("FAILED %d" % address)
            print("ThrottleBridge: FAILED to acquire throttle for %d" % address)

    def doSpeed(self, payload):
        """Set speed. Payload: '0.0' to '1.0'"""
        if self.throttle is None:
            self.publish("ERROR no throttle")
            return

        speed = float(payload)
        speed = max(0.0, min(1.0, speed))
        self.throttle.setSpeedSetting(speed)
        self.publish("SPEED %.3f" % speed)

    def doDirection(self, payload):
        """Set direction. Payload: 'FORWARD' or 'REVERSE'"""
        if self.throttle is None:
            self.publish("ERROR no throttle")
            return

        forward = payload.upper().startswith("F")
        self.throttle.setIsForward(forward)
        self.publish("FORWARD" if forward else "REVERSE")

    def doStop(self):
        """Stop (speed = 0)."""
        if self.throttle is None:
            self.publish("ERROR no throttle")
            return

        self.throttle.setSpeedSetting(0)
        self.publish("STOPPED")

    def doEstop(self):
        """Emergency stop."""
        if self.throttle is None:
            self.publish("ERROR no throttle")
            return

        self.throttle.setSpeedSetting(-1)
        self.publish("ESTOPPED")

    def doFunction(self, payload):
        """Set function. Payload: 'NUM ON|OFF'"""
        if self.throttle is None:
            self.publish("ERROR no throttle")
            return

        parts = payload.split()
        if len(parts) < 2:
            self.publish("ERROR bad function format")
            return

        fnum = int(parts[0])
        fstate = parts[1].upper() == "ON"
        self.throttle.setFunction(fnum, fstate)
        self.publish("FUNCTION %d %s" % (fnum, "ON" if fstate else "OFF"))

    def doRelease(self):
        """Release the current throttle."""
        if self.throttle is not None:
            self.throttle.setSpeedSetting(0)
            addr = self.currentAddress
            self.throttle = None
            self.currentAddress = None
            self.publish("RELEASED %s" % str(addr))
            print("ThrottleBridge: released throttle")
        else:
            self.publish("RELEASED")


# --- Start the bridge ---
bridge = ThrottleBridge()
bridge.setName("SpeedCal Throttle Bridge")
bridge.start()
print("")
print("=== Speed Calibration Throttle Bridge started ===")
print("Listening for commands on " + TOPIC_PREFIX + "*")
print("Publishing status to " + TOPIC_STATUS)
print("")
