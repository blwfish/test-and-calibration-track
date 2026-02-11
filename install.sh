#!/bin/bash
#
# Install speed calibration tools for use with JMRI
#
# Installs Python scripts, dependencies, and the JMRI throttle bridge
# into a local directory alongside JMRI on macOS.
#
# Usage:
#   ./install.sh [--prefix DIR]
#
# Default prefix: ~/speed-cal

set -euo pipefail

PREFIX="${HOME}/speed-cal"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--prefix DIR]"
            echo "  Default prefix: ~/speed-cal"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Speed Calibration Tools Installer ==="
echo ""
echo "Install prefix: ${PREFIX}"
echo ""

# --- Check prerequisites ---
echo "Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3 first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python ${PYTHON_VERSION} found"

# Check for JMRI
JMRI_APP=""
for candidate in "/Applications/JMRI" "/Applications/JMRI/PanelPro.app" "/Applications/JMRI/DecoderPro.app"; do
    if [[ -e "$candidate" ]]; then
        JMRI_APP="$candidate"
        break
    fi
done
if [[ -n "$JMRI_APP" ]]; then
    echo "  JMRI found at ${JMRI_APP}"
else
    echo "  WARNING: JMRI not found in /Applications/JMRI — install will continue"
fi

# --- Create directory structure ---
echo ""
echo "Creating directories..."
mkdir -p "${PREFIX}/scripts"
mkdir -p "${PREFIX}/calibration-data"
mkdir -p "${PREFIX}/jmri"

# --- Install Python scripts ---
echo "Installing Python scripts..."
for f in calibrate_speed.py loco_control.py calibration_db.py; do
    cp "${SCRIPT_DIR}/scripts/${f}" "${PREFIX}/scripts/"
    echo "  ${f}"
done

# --- Install JMRI bridge script ---
echo "Installing JMRI throttle bridge..."
cp "${SCRIPT_DIR}/scripts/jmri_throttle_bridge.py" "${PREFIX}/jmri/"
echo "  jmri_throttle_bridge.py"

# --- Install Python dependency ---
echo ""
echo "Installing Python dependencies..."
python3 -m pip install --user --quiet paho-mqtt
echo "  paho-mqtt installed"

# --- Verify import works ---
if python3 -c "import paho.mqtt.client" 2>/dev/null; then
    echo "  Verified: paho-mqtt importable"
else
    echo "  WARNING: paho-mqtt installed but not importable — check your Python path"
fi

# --- Install README ---
echo ""
echo "Installing documentation..."
cp "${SCRIPT_DIR}/INSTALL_README.md" "${PREFIX}/README.md"
echo "  README.md"

# --- Create convenience launcher scripts ---
echo "Creating launcher scripts..."

cat > "${PREFIX}/calibrate" <<'LAUNCHER'
#!/bin/bash
# Run a speed calibration sweep
SCRIPT_DIR="$(cd "$(dirname "$0")/scripts" && pwd)"
exec python3 "${SCRIPT_DIR}/calibrate_speed.py" "$@"
LAUNCHER
chmod +x "${PREFIX}/calibrate"
echo "  calibrate"

cat > "${PREFIX}/loco" <<'LAUNCHER'
#!/bin/bash
# Interactive locomotive control CLI
SCRIPT_DIR="$(cd "$(dirname "$0")/scripts" && pwd)"
exec python3 "${SCRIPT_DIR}/loco_control.py" "$@"
LAUNCHER
chmod +x "${PREFIX}/loco"
echo "  loco"

# --- Summary ---
echo ""
echo "=== Installation complete ==="
echo ""
echo "Installed to: ${PREFIX}"
echo ""
echo "Quick start:"
echo "  1. Start JMRI and load the throttle bridge:"
echo "     Scripting > Run Script > ${PREFIX}/jmri/jmri_throttle_bridge.py"
echo ""
echo "  2. Interactive loco control:"
echo "     ${PREFIX}/loco --address 3 --broker 192.168.68.250"
echo ""
echo "  3. Automated calibration sweep:"
echo "     ${PREFIX}/calibrate --address 3 --broker 192.168.68.250"
echo ""
echo "  4. Dry run (no MQTT, preview only):"
echo "     ${PREFIX}/calibrate --address 3 --dry-run"
echo ""
echo "See ${PREFIX}/README.md for full documentation."
