# Jarvis Orchestrator Integration

This fork adds direct integration with Jarvis orchestrator for advanced voice processing.

## Changes from Upstream

- **Direct orchestrator integration**: Satellites call Jarvis orchestrator at `https://10.0.0.9:5000` before falling back to Home Assistant
- **Speaker identification**: Integration with speaker-id service for voice identification
- **Multi-turn conversations**: Conversation ID persistence for context-aware responses
- **Keep-awake functionality**: Dynamic timeout based on orchestrator response
- **HTTPS support**: Uses HTTPS for secure communication with orchestrator

## Configuration

Edit `linux_voice_assistant/satellite.py` line 58:

```python
ORCHESTRATOR_URL = "https://10.0.0.9:5000"  # Jarvis orchestrator
SPEAKER_ID_URL = "http://localhost:5001"     # Local speaker-id service
SATELLITE_NAME = "Family Room"                # Unique per satellite
```

## Deployment

### To sat1 (Family Room - 10.0.0.150):
```bash
cd /srv/jarvis/linux-voice-assistant-fork
scp linux_voice_assistant/satellite.py lva@10.0.0.150:/home/lva/linux-voice-assistant/linux_voice_assistant/
ssh lva@10.0.0.150 "sed -i 's/SATELLITE_NAME = \"Office\"/SATELLITE_NAME = \"Family Room\"/' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py"
ssh lva@10.0.0.150 "systemctl --user restart lva"
```

### To sat2 (Office - 10.0.0.151):
```bash
cd /srv/jarvis/linux-voice-assistant-fork
scp linux_voice_assistant/satellite.py lva@10.0.0.151:/home/lva/linux-voice-assistant/linux_voice_assistant/
ssh lva@10.0.0.151 "sed -i 's/SATELLITE_NAME = \"Family Room\"/SATELLITE_NAME = \"Office\"/' /home/lva/linux-voice-assistant/linux_voice_assistant/satellite.py"
ssh lva@10.0.0.151 "systemctl --user restart lva"
```

## Architecture Flow

```
Wake Word → Transcription → Speaker-ID → Orchestrator (HTTPS) → TTS Response
                                              ↓ (on failure)
                                         Home Assistant
```

## Upstream

Original: https://github.com/OHF-Voice/linux-voice-assistant.git

This fork maintained at: `/srv/jarvis/linux-voice-assistant-fork` (to be pushed to GitHub)

## Commit History

- `2915b32` - Add Jarvis orchestrator integration with HTTPS (2026-01-26)
- `fd4c1d9` - Upstream: Merge pull request #55 from OHF-Voice/synesthesiam-20251111-custom-wakewords

## TODO

- [ ] Push this fork to Bob's GitHub account
- [ ] Update satellite git remotes to pull from GitHub fork
- [ ] Set up automated deployment script
