#!/bin/bash
# Deploy satellite.py to both satellites with correct configuration

set -e

REPO_DIR="/srv/jarvis/linux-voice-assistant-fork"
SATELLITE_FILE="linux_voice_assistant/satellite.py"

echo "==================================================================="
echo "Deploying LVA Jarvis Integration to Satellites"
echo "==================================================================="

# Deploy to sat1 (Family Room)
echo ""
echo "Deploying to sat1 (Family Room - 10.0.0.150)..."
scp "${REPO_DIR}/${SATELLITE_FILE}" lva@10.0.0.150:/home/lva/linux-voice-assistant/linux_voice_assistant/
ssh lva@10.0.0.150 "sed -i 's/SATELLITE_NAME = \"[^\"]*\"/SATELLITE_NAME = \"Family Room\"/' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py"
ssh lva@10.0.0.150 "grep 'SATELLITE_NAME\|ORCHESTRATOR_URL' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py | head -2"
echo "Restarting sat1 LVA service..."
ssh lva@10.0.0.150 "systemctl --user restart lva"
echo "✓ sat1 deployed"

# Deploy to sat2 (Office)
echo ""
echo "Deploying to sat2 (Office - 10.0.0.151)..."
scp "${REPO_DIR}/${SATELLITE_FILE}" lva@10.0.0.151:/home/lva/linux-voice-assistant/linux_voice_assistant/
ssh lva@10.0.0.151 "sed -i 's/SATELLITE_NAME = \"[^\"]*\"/SATELLITE_NAME = \"Office\"/' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py"
ssh lva@10.0.0.151 "grep 'SATELLITE_NAME\|ORCHESTRATOR_URL' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py | head -2"
echo "Restarting sat2 LVA service..."
ssh lva@10.0.0.151 "systemctl --user restart lva"
echo "✓ sat2 deployed"

echo ""
echo "==================================================================="
echo "Deployment complete!"
echo "==================================================================="
echo ""
echo "Verify services:"
echo "  ssh lva@10.0.0.150 'systemctl --user status lva'"
echo "  ssh lva@10.0.0.151 'systemctl --user status lva'"
echo ""
