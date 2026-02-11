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
import os
import sys
import time
import threading

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# Import sibling module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jmri_config import read_mqtt_config


# --- Default MQTT settings (used when JMRI config not found) ---
DEFAULT_BROKER = "192.168.68.250"
DEFAULT_PORT = 1883
DEFAULT_PREFIX = "/cova/speed-cal"


class LocoController:
    def __init__(self, broker, port=1883, prefix=DEFAULT_PREFIX):
        if mqtt is None:
            raise ImportError("paho-mqtt not installed. Run: pip3 install paho-mqtt")

        self.broker = broker
        self.port = port
        self.connected = False
        self.bridge_ready = False
        self.current_address = None
        self.last_status = None
        self.last_result = None

        # Build topic paths from configurable prefix
        self.prefix = prefix.rstrip("/")
        self.t_throttle = self.prefix + "/throttle/"
        self.t_status = self.t_throttle + "status"
        self.t_sensor = self.prefix + "/speed-cal/"
        self.t_roster = self.prefix + "/roster/"
        self.t_cv = self.prefix + "/cv/"

        # Request-response correlation
        self._pending = {}  # request_id -> {"event": Event, "result": dict}
        self._req_counter = 0
        self._req_lock = threading.Lock()

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
            client.subscribe(self.t_status)
            client.subscribe(self.t_sensor + "result")
            client.subscribe(self.t_sensor + "status")
            client.subscribe(self.t_sensor + "load")
            client.subscribe(self.t_sensor + "vibration")
            client.subscribe(self.t_sensor + "audio")
            # Subscribe to roster and CV responses
            client.subscribe(self.t_roster + "info")
            client.subscribe(self.t_roster + "import_status")
            client.subscribe(self.t_cv + "result")
        else:
            print(f"Connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            print("Disconnected unexpectedly")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")

        if topic == self.t_status:
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

        elif topic == self.t_sensor + "result":
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

        elif topic == self.t_sensor + "status":
            pass  # sensor status updates are noisy

        elif topic == self.t_sensor + "load":
            try:
                r = json.loads(payload)
                grams = r.get("grams", "?")
                tared = "tared" if r.get("tared") else "untared"
                print(f"\n  Load cell: {grams} g ({tared})")
            except json.JSONDecodeError:
                print(f"[load] {payload}")

        elif topic == self.t_sensor + "vibration":
            try:
                r = json.loads(payload)
                pp = r.get("peak_to_peak", "?")
                rms = r.get("rms", "?")
                samples = r.get("samples", "?")
                dur = r.get("duration_ms", "?")
                print(f"\n  Vibration: p2p={pp}, rms={rms} ({samples} samples, {dur}ms)")
            except json.JSONDecodeError:
                print(f"[vibration] {payload}")

        elif topic == self.t_sensor + "audio":
            try:
                r = json.loads(payload)
                rms_db = r.get("rms_db", "?")
                peak_db = r.get("peak_db", "?")
                samples = r.get("samples", "?")
                dur = r.get("duration_ms", "?")
                print(f"\n  Audio: rms={rms_db} dB, peak={peak_db} dB ({samples} samples, {dur}ms)")
            except json.JSONDecodeError:
                print(f"[audio] {payload}")

        elif topic in (self.t_roster + "info",
                       self.t_roster + "import_status",
                       self.t_cv + "result"):
            self._handle_response(topic, payload)

    def _handle_response(self, topic, payload):
        """Route a JSON response to the waiting request by request_id."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            print(f"[response] bad JSON: {payload}")
            return

        request_id = data.get("request_id", "")
        if request_id and request_id in self._pending:
            self._pending[request_id]["result"] = data
            self._pending[request_id]["event"].set()

        # Also print for interactive use
        if topic == self.t_roster + "info":
            self._print_roster_info(data)
        elif topic == self.t_roster + "import_status":
            self._print_import_status(data)
        elif topic == self.t_cv + "result":
            self._print_cv_result(data)

    def _print_roster_info(self, data):
        if data.get("found"):
            for e in data.get("entries", []):
                sp = "yes" if e.get("has_speed_profile") else "no"
                print(f"\n  Roster: {e['roster_id']}, addr={e.get('address')}, "
                      f"decoder={e.get('decoder_model', '?')}, "
                      f"speed profile={sp}")
        else:
            print(f"\n  Roster: {data.get('error', 'not found')}")

    def _print_import_status(self, data):
        if data.get("success"):
            print(f"\n  Import: {data.get('entries_imported', 0)} entries "
                  f"imported to '{data.get('roster_id')}'")
        else:
            print(f"\n  Import failed: {data.get('error', 'unknown')}")

    def _print_cv_result(self, data):
        op = data.get("operation", "?")
        cv = data.get("cv", "?")
        val = data.get("value", "?")
        status = data.get("status", "?")
        if op == "read":
            print(f"\n  CV {cv} = {val} ({status})")
        elif op == "write":
            print(f"\n  CV {cv} <- {val} ({status})")
        elif op in ("read_batch_complete", "write_batch_complete"):
            results = data.get("results", [])
            ok = sum(1 for r in results if r.get("status") == "OK")
            print(f"\n  Batch {op}: {ok}/{len(results)} OK")

    # --- Request-response helpers ---

    def _next_request_id(self, prefix="req"):
        with self._req_lock:
            self._req_counter += 1
            return f"{prefix}-{self._req_counter}"

    def _wait_for_request(self, request_id, timeout=30.0):
        """Wait for a response matching request_id. Returns parsed JSON or None."""
        entry = {"event": threading.Event(), "result": None}
        self._pending[request_id] = entry
        entry["event"].wait(timeout=timeout)
        self._pending.pop(request_id, None)
        return entry["result"]

    # --- Throttle commands ---

    def _publish(self, topic_suffix, payload=""):
        """Publish to a throttle bridge topic."""
        topic = self.t_throttle + topic_suffix
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
        self.client.publish(self.t_sensor + "arm", "")
        print("Sensors armed")

    def stop_sensors(self):
        """Cancel sensor measurement."""
        self.client.publish(self.t_sensor + "stop", "")
        print("Sensors disarmed")

    def tare_load_cell(self):
        """Tare (zero) the load cell."""
        self.client.publish(self.t_sensor + "tare", "")
        print("Load cell tare requested")

    def read_load_cell(self):
        """Request a load cell reading."""
        self.client.publish(self.t_sensor + "load", "")
        print("Load cell reading requested")

    def capture_vibration(self):
        """Start a vibration capture."""
        self.client.publish(self.t_sensor + "vibration", "")
        print("Vibration capture started")

    def capture_audio(self):
        """Start an audio capture."""
        self.client.publish(self.t_sensor + "audio", "")
        print("Audio capture started")

    # --- Roster commands ---

    def query_roster(self, roster_id=None, address=None, timeout=10.0):
        """Query JMRI roster by roster_id or address. Returns parsed response or None."""
        request_id = self._next_request_id("rq")
        payload = {"request_id": request_id}
        if roster_id:
            payload["roster_id"] = roster_id
        elif address is not None:
            payload["address"] = address
        self.client.publish(self.t_roster + "query", json.dumps(payload))
        return self._wait_for_request(request_id, timeout=timeout)

    def import_speed_profile(self, roster_id, entries, scale_factor=87.1,
                             clear_existing=True, timeout=30.0):
        """Import speed profile into a JMRI roster entry.

        entries: list of {"speed_step": int, "speed_mph": float, "direction": str}
        Returns parsed response or None on timeout.
        """
        request_id = self._next_request_id("imp")
        payload = {
            "request_id": request_id,
            "roster_id": roster_id,
            "scale_factor": scale_factor,
            "clear_existing": clear_existing,
            "entries": entries,
        }
        self.client.publish(self.t_roster + "import_profile", json.dumps(payload))
        return self._wait_for_request(request_id, timeout=timeout)

    # --- CV commands ---

    def read_cv(self, cv, timeout=30.0):
        """Read a single CV. Returns {"cv", "value", "status"} or None."""
        request_id = self._next_request_id("cvr")
        payload = {"request_id": request_id, "cv": cv}
        self.client.publish(self.t_cv + "read", json.dumps(payload))
        return self._wait_for_request(request_id, timeout=timeout)

    def read_cvs(self, cvs, timeout=None):
        """Read multiple CVs. Returns batch result or None."""
        if timeout is None:
            timeout = len(cvs) * 30.0
        request_id = self._next_request_id("cvr")
        payload = {"request_id": request_id, "cvs": cvs}
        self.client.publish(self.t_cv + "read", json.dumps(payload))
        return self._wait_for_request(request_id, timeout=timeout)

    def write_cv(self, cv, value, timeout=30.0):
        """Write a single CV. Returns result dict or None."""
        request_id = self._next_request_id("cvw")
        payload = {"request_id": request_id, "cv": cv, "value": value}
        self.client.publish(self.t_cv + "write", json.dumps(payload))
        return self._wait_for_request(request_id, timeout=timeout)

    def write_cvs(self, writes, timeout=None):
        """Write multiple CVs. writes: [{"cv": N, "value": V}, ...]. Returns batch result or None."""
        if timeout is None:
            timeout = len(writes) * 30.0
        request_id = self._next_request_id("cvw")
        payload = {"request_id": request_id, "writes": writes}
        self.client.publish(self.t_cv + "write", json.dumps(payload))
        return self._wait_for_request(request_id, timeout=timeout)

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
  load                - Read load cell
  tare                - Tare (zero) load cell
  vibration           - Start vibration capture
  audio               - Start audio capture

  roster ID           - Query JMRI roster entry by ID
  roster-addr ADDR    - Query JMRI roster entry by DCC address
  cv-read CV          - Read a decoder CV
  cv-write CV VALUE   - Write a decoder CV

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


def resolve_mqtt_args(args):
    """Fill in broker/port/prefix from JMRI config if not given on CLI."""
    jmri = read_mqtt_config()
    if jmri:
        if args.broker is None:
            args.broker = jmri.broker
            print(f"Auto-detected MQTT broker from JMRI: {jmri.broker}")
        if args.port is None:
            args.port = jmri.port
        if args.prefix is None and jmri.channel:
            args.prefix = jmri.channel + "/speed-cal"
            print(f"Auto-detected MQTT prefix from JMRI: {args.prefix}")
    elif args.broker is None or args.port is None:
        print("No JMRI MQTT config found; using defaults")

    # Apply defaults for anything still unset
    if args.broker is None:
        args.broker = DEFAULT_BROKER
    if args.port is None:
        args.port = DEFAULT_PORT
    if args.prefix is None:
        args.prefix = DEFAULT_PREFIX


def main():
    if mqtt is None:
        print("ERROR: paho-mqtt not installed. Run: pip3 install paho-mqtt")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Locomotive Control CLI")
    parser.add_argument("--broker", default=None,
                        help="MQTT broker address (auto-detected from JMRI config)")
    parser.add_argument("--port", type=int, default=None,
                        help="MQTT broker port (auto-detected from JMRI config)")
    parser.add_argument("--prefix", default=None,
                        help="MQTT topic prefix (auto-detected from JMRI config)")
    parser.add_argument("--address", type=int, default=None,
                        help="DCC address to acquire on startup")
    args = parser.parse_args()

    resolve_mqtt_args(args)

    ctrl = LocoController(args.broker, args.port, prefix=args.prefix)
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

            elif cmd == "load":
                ctrl.read_load_cell()

            elif cmd == "tare":
                ctrl.tare_load_cell()

            elif cmd == "vibration":
                ctrl.capture_vibration()

            elif cmd == "audio":
                ctrl.capture_audio()

            elif cmd == "roster":
                if len(parts) < 2:
                    print("Usage: roster ROSTER_ID")
                    continue
                roster_id = " ".join(parts[1:])
                ctrl.query_roster(roster_id=roster_id)

            elif cmd == "roster-addr":
                if len(parts) < 2:
                    print("Usage: roster-addr ADDRESS")
                    continue
                ctrl.query_roster(address=int(parts[1]))

            elif cmd == "cv-read":
                if len(parts) < 2:
                    print("Usage: cv-read CV_NUMBER")
                    continue
                ctrl.read_cv(int(parts[1]))

            elif cmd == "cv-write":
                if len(parts) < 3:
                    print("Usage: cv-write CV_NUMBER VALUE")
                    continue
                ctrl.write_cv(int(parts[1]), int(parts[2]))

            elif cmd == "shuttle":
                spd = parse_speed(parts[1]) if len(parts) > 1 else 0.3
                runs = int(parts[2]) if len(parts) > 2 else 4
                pause = float(parts[3]) if len(parts) > 3 else 3.0
                ctrl.shuttle(spd, runs, pause)

            elif cmd == "status":
                print(f"  Broker:  {ctrl.broker}:{ctrl.port}")
                print(f"  Prefix:  {ctrl.prefix}")
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
