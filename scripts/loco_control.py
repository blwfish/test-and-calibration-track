#!/usr/bin/env python3
"""
Locomotive Control CLI

Sends MQTT commands to the JMRI throttle bridge to control a DCC
locomotive. For testing on roller track, calibration runs, etc.

Usage:
  python3 loco_control.py [--broker HOST] [--address ADDR]

Prerequisites:
  pip3 install paho-mqtt

  JMRI must be running with:
  - SPROG (or other command station) connection
  - MQTT connection to the same broker
  - jmri_throttle_bridge.py script loaded and running
"""

import argparse
import json
import sys
import time
import threading

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip3 install paho-mqtt")
    sys.exit(1)


# --- MQTT Topics ---
TOPIC_PREFIX = "/cova/speed-cal/throttle/"
TOPIC_STATUS = TOPIC_PREFIX + "status"

# ESP32 sensor topics
SENSOR_PREFIX = "/cova/speed-cal/speed-cal/"
SENSOR_RESULT = SENSOR_PREFIX + "result"
SENSOR_ARM = SENSOR_PREFIX + "arm"
SENSOR_STOP = SENSOR_PREFIX + "stop"
SENSOR_STATUS = SENSOR_PREFIX + "status"


class LocoController:
    def __init__(self, broker, port=1883):
        self.broker = broker
        self.port = port
        self.connected = False
        self.bridge_ready = False
        self.current_address = None
        self.last_status = None
        self.last_result = None

        self.client = mqtt.Client(client_id="loco-control-cli")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def connect(self):
        """Connect to the MQTT broker."""
        print(f"Connecting to MQTT broker {self.broker}:{self.port}...")
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            # Wait for connection
            for _ in range(50):
                if self.connected:
                    return True
                time.sleep(0.1)
            print("ERROR: Connection timeout")
            return False
        except Exception as e:
            print(f"ERROR: {e}")
            return False

    def disconnect(self):
        """Disconnect from broker."""
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            print("Connected to MQTT broker")
            # Subscribe to bridge status and sensor results
            client.subscribe(TOPIC_STATUS)
            client.subscribe(SENSOR_RESULT)
            client.subscribe(SENSOR_STATUS)
        else:
            print(f"Connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            print("Disconnected unexpectedly")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")

        if topic == TOPIC_STATUS:
            self.last_status = payload
            if payload == "READY":
                self.bridge_ready = True
                print("[bridge] Ready")
            elif payload.startswith("ACQUIRED"):
                print(f"[bridge] {payload}")
            elif payload.startswith("ERROR"):
                print(f"[bridge] {payload}")
            elif payload.startswith("SPEED"):
                pass  # quiet on speed acks
            elif payload in ("FORWARD", "REVERSE", "STOPPED", "ESTOPPED"):
                print(f"[bridge] {payload}")
            else:
                print(f"[bridge] {payload}")

        elif topic == SENSOR_RESULT:
            self.last_result = payload
            try:
                r = json.loads(payload)
                speed = r.get("avg_speed_mph", "?")
                direction = r.get("direction", "?")
                sensors = r.get("sensors_triggered", "?")
                duration = r.get("duration_ms", "?")
                if isinstance(duration, (int, float)):
                    duration = f"{duration:.1f}"
                print(f"\n  Result: {speed} scale mph, direction {direction}, "
                      f"{sensors} sensors, {duration} ms")
                if "speeds_mph" in r:
                    print(f"  Intervals: {r['speeds_mph']} mph")
            except json.JSONDecodeError:
                print(f"[sensor] {payload}")

        elif topic == SENSOR_STATUS:
            pass  # sensor status updates are noisy

    def _publish(self, topic_suffix, payload=""):
        """Publish to a throttle bridge topic."""
        topic = TOPIC_PREFIX + topic_suffix
        self.client.publish(topic, payload)

    def _wait_status(self, prefix, timeout=5.0):
        """Wait for a status message starting with prefix."""
        self.last_status = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.last_status and self.last_status.startswith(prefix):
                return self.last_status
            time.sleep(0.05)
        return None

    # --- Throttle commands ---

    def acquire(self, address, long_addr=None):
        """Acquire a throttle for the given DCC address."""
        if long_addr is None:
            long_addr = address >= 128
        addr_type = "L" if long_addr else "S"
        self._publish("acquire", f"{address} {addr_type}")
        result = self._wait_status("ACQUIRED", timeout=35)
        if result:
            self.current_address = address
            return True
        else:
            print("ERROR: throttle acquire timeout or failure")
            return False

    def speed(self, value):
        """Set speed (0.0 to 1.0)."""
        self._publish("speed", f"{value:.3f}")

    def forward(self):
        """Set direction forward."""
        self._publish("direction", "FORWARD")

    def reverse(self):
        """Set direction reverse."""
        self._publish("direction", "REVERSE")

    def stop(self):
        """Stop (speed = 0)."""
        self._publish("stop")

    def estop(self):
        """Emergency stop."""
        self._publish("estop")

    def function(self, num, state):
        """Set function on/off."""
        self._publish("function", f"{num} {'ON' if state else 'OFF'}")

    def release(self):
        """Release the throttle."""
        self._publish("release")
        self.current_address = None

    # --- Sensor commands ---

    def arm_sensors(self):
        """Arm the ESP32 sensors for a speed measurement."""
        self.last_result = None
        self.client.publish(SENSOR_ARM, "")
        print("Sensors armed")

    def stop_sensors(self):
        """Cancel sensor measurement."""
        self.client.publish(SENSOR_STOP, "")
        print("Sensors disarmed")

    # --- Compound operations ---

    def shuttle(self, speed_setting, runs=2, pause=3.0):
        """
        Run the loco back and forth on rollers.
        speed_setting: 0.0 to 1.0
        runs: number of direction changes
        pause: seconds between direction changes
        """
        print(f"\nShuttle: speed={speed_setting}, runs={runs}, pause={pause}s")
        print("Press Ctrl+C to stop\n")

        try:
            self.forward()
            time.sleep(0.5)
            self.speed(speed_setting)

            for i in range(runs):
                time.sleep(pause)
                self.stop()
                time.sleep(1.0)
                if i % 2 == 0:
                    self.reverse()
                else:
                    self.forward()
                time.sleep(0.5)
                self.speed(speed_setting)

            time.sleep(pause)
            self.stop()
            print("Shuttle complete")

        except KeyboardInterrupt:
            self.stop()
            print("\nStopped")


def print_help():
    """Print available commands."""
    print("""
Commands:
  acquire ADDR [L|S]  - Acquire throttle (L=long, S=short, auto if omitted)
  speed VALUE         - Set speed (0.0 to 1.0, or integer 1-126 for speed step)
  fwd / forward       - Set direction forward
  rev / reverse       - Set direction reverse
  stop                - Stop (speed = 0)
  estop               - Emergency stop
  f NUM on|off        - Set function (e.g. 'f 0 on' for headlight)
  release             - Release throttle

  arm                 - Arm ESP32 sensors for speed measurement
  disarm              - Cancel sensor measurement

  shuttle SPD [N] [P] - Run back and forth (speed, runs, pause_secs)

  status              - Show current state
  help                - Show this message
  quit / exit         - Stop loco and exit
""")


def parse_speed(value_str):
    """Parse a speed value. If integer 1-126, convert to 0.0-1.0 range."""
    val = float(value_str)
    if val > 1.0:
        # Treat as speed step (1-126) -> convert to 0.0-1.0
        val = val / 126.0
        val = min(1.0, val)
    return val


def main():
    parser = argparse.ArgumentParser(description="Locomotive Control CLI")
    parser.add_argument("--broker", default="192.168.68.250",
                        help="MQTT broker address (default: 192.168.68.250)")
    parser.add_argument("--port", type=int, default=1883,
                        help="MQTT broker port (default: 1883)")
    parser.add_argument("--address", type=int, default=None,
                        help="DCC address to acquire on startup")
    args = parser.parse_args()

    ctrl = LocoController(args.broker, args.port)
    if not ctrl.connect():
        sys.exit(1)

    # Auto-acquire if address provided
    if args.address is not None:
        time.sleep(0.5)  # let bridge status arrive
        ctrl.acquire(args.address)

    print_help()

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break

            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ("quit", "exit", "q"):
                ctrl.stop()
                time.sleep(0.3)
                ctrl.release()
                break

            elif cmd == "acquire":
                if len(parts) < 2:
                    print("Usage: acquire ADDRESS [L|S]")
                    continue
                addr = int(parts[1])
                long_addr = None
                if len(parts) >= 3:
                    long_addr = parts[2].upper() == "L"
                ctrl.acquire(addr, long_addr)

            elif cmd == "speed":
                if len(parts) < 2:
                    print("Usage: speed VALUE (0.0-1.0 or 1-126)")
                    continue
                spd = parse_speed(parts[1])
                ctrl.speed(spd)
                print(f"Speed: {spd:.3f}")

            elif cmd in ("fwd", "forward"):
                ctrl.forward()

            elif cmd in ("rev", "reverse"):
                ctrl.reverse()

            elif cmd == "stop":
                ctrl.stop()

            elif cmd == "estop":
                ctrl.estop()

            elif cmd == "f":
                if len(parts) < 3:
                    print("Usage: f NUM on|off")
                    continue
                fnum = int(parts[1])
                fstate = parts[2].lower() in ("on", "1", "true")
                ctrl.function(fnum, fstate)

            elif cmd == "release":
                ctrl.release()

            elif cmd == "arm":
                ctrl.arm_sensors()

            elif cmd == "disarm":
                ctrl.stop_sensors()

            elif cmd == "shuttle":
                spd = parse_speed(parts[1]) if len(parts) > 1 else 0.3
                runs = int(parts[2]) if len(parts) > 2 else 4
                pause = float(parts[3]) if len(parts) > 3 else 3.0
                ctrl.shuttle(spd, runs, pause)

            elif cmd == "status":
                print(f"  Broker:  {ctrl.broker}:{ctrl.port}")
                print(f"  Connected: {ctrl.connected}")
                print(f"  Bridge:  {'ready' if ctrl.bridge_ready else 'not detected'}")
                print(f"  Address: {ctrl.current_address or 'none'}")

            elif cmd == "help":
                print_help()

            else:
                print(f"Unknown command: '{cmd}' (type 'help')")

    except KeyboardInterrupt:
        print("\nStopping...")
        ctrl.stop()
        time.sleep(0.3)

    ctrl.release()
    time.sleep(0.3)
    ctrl.disconnect()
    print("Bye!")


if __name__ == "__main__":
    main()
