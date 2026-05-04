#!/bin/bash
# Deploy satellite.py to both satellites with correct configuration

set -e

REPO_DIR="/srv/jarvis/linux-voice-assistant-fork"
SATELLITE_FILE="linux_voice_assistant/satellite.py"
EXTRA_FILES=(
    "linux_voice_assistant/transcript_filter.py"
    "linux_voice_assistant/openwakeword_compat.py"
    "linux_voice_assistant/__main__.py"
    "linux_voice_assistant/lwake_detector.py"
    "linux_voice_assistant/models.py"
)

echo "==================================================================="
echo "Deploying LVA Jarvis Integration to Satellites"
echo "==================================================================="

# Deploy to sat1 (Family Room)
echo ""
echo "Deploying to sat1 (Family Room - 10.0.0.150)..."
scp "${REPO_DIR}/${SATELLITE_FILE}" lva@10.0.0.150:/home/lva/linux-voice-assistant/linux_voice_assistant/
for f in "${EXTRA_FILES[@]}"; do
    scp "${REPO_DIR}/${f}" lva@10.0.0.150:/home/lva/linux-voice-assistant/${f}
done
ssh lva@10.0.0.150 "sed -i 's/SATELLITE_NAME = \"[^\"]*\"/SATELLITE_NAME = \"Family Room\"/' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py"
ssh lva@10.0.0.150 "grep 'SATELLITE_NAME\|ORCHESTRATOR_URL' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py | head -2"
echo "Restarting sat1 LVA service..."
ssh lva@10.0.0.150 "systemctl --user restart lva"
echo "✓ sat1 deployed"

# Deploy to sat2 (Office)
echo ""
echo "Deploying to sat2 (Office - 10.0.0.151)..."
scp "${REPO_DIR}/${SATELLITE_FILE}" lva@10.0.0.151:/home/lva/linux-voice-assistant/linux_voice_assistant/
for f in "${EXTRA_FILES[@]}"; do
    scp "${REPO_DIR}/${f}" lva@10.0.0.151:/home/lva/linux-voice-assistant/${f}
done
ssh lva@10.0.0.151 "sed -i 's/SATELLITE_NAME = \"[^\"]*\"/SATELLITE_NAME = \"Office\"/' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py"
ssh lva@10.0.0.151 "grep 'SATELLITE_NAME\|ORCHESTRATOR_URL' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py | head -2"
echo "Restarting sat2 LVA service..."
ssh lva@10.0.0.151 "systemctl --user restart lva"
echo "✓ sat2 deployed"

# Reload HA ESPHome entries so satellites reconnect immediately
echo ""
echo "Reloading HA ESPHome integration for both satellites..."
HA_TOKEN=$(ssh lva@10.0.0.150 "grep -oP 'HA_TOKEN = \"\\K[^\"]+' /home/lva/satellite_health_monitor.py")
sleep 5
curl -s -X POST "http://10.0.0.16:8123/api/services/homeassistant/reload_config_entry" \
  -H "Authorization: Bearer ${HA_TOKEN}" -H "Content-Type: application/json" \
  -d '{"entry_id": "01KDRWHB84JKT2EKSX2KQX7J6W"}' > /dev/null && echo "✓ HA ESPHome reloaded"

echo ""
echo "==================================================================="
echo "Deployment complete!"
echo "==================================================================="
echo ""
echo "Verify services:"
echo "  ssh lva@10.0.0.150 'systemctl --user status lva'"
echo "  ssh lva@10.0.0.151 'systemctl --user status lva'"
echo ""
