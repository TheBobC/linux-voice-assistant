# Push to GitHub - Instructions for Bob

## Current Status

✅ Fork created locally at `/srv/jarvis/linux-voice-assistant-fork`
✅ HTTPS integration committed (3 commits ahead of upstream)
✅ Deployed to both satellites (sat1, sat2)
✅ Satellites now using HTTPS with SSL verification disabled

## Commits in Fork

```
0b3ddd3 - Disable SSL verification for self-signed certificate
afc6c81 - Add deployment docs and script for Jarvis integration
2915b32 - Add Jarvis orchestrator integration with HTTPS
```

## To Push to Your GitHub

### 1. Create GitHub Repository

Go to https://github.com/new and create a new repo:
- Name: `linux-voice-assistant` (or `linux-voice-assistant-jarvis`)
- Description: "Fork of OHF-Voice/linux-voice-assistant with Jarvis orchestrator integration"
- Visibility: Private (recommended) or Public
- Do NOT initialize with README (we already have commits)

### 2. Add GitHub Remote

```bash
cd /srv/jarvis/linux-voice-assistant-fork

# Replace YOUR_GITHUB_USERNAME with your actual GitHub username
git remote add github git@github.com:YOUR_GITHUB_USERNAME/linux-voice-assistant.git

# Or use HTTPS if you prefer:
git remote add github https://github.com/YOUR_GITHUB_USERNAME/linux-voice-assistant.git
```

### 3. Push to GitHub

```bash
git push -u github main
```

### 4. Update Satellites to Track Your Fork

Once pushed to GitHub, update both satellites:

**On sat1:**
```bash
ssh lva@10.0.0.150
cd /home/lva/linux-voice-assistant
git remote set-url origin git@github.com:YOUR_GITHUB_USERNAME/linux-voice-assistant.git
git fetch origin
git reset --hard origin/main
sed -i 's/SATELLITE_NAME = "[^"]*"/SATELLITE_NAME = "Family Room"/' linux_voice_assistant/satellite.py
systemctl --user restart lva
```

**On sat2:**
```bash
ssh lva@10.0.0.151
cd /home/lva/linux-voice-assistant
git remote set-url origin git@github.com:YOUR_GITHUB_USERNAME/linux-voice-assistant.git
git fetch origin
git reset --hard origin/main
sed -i 's/SATELLITE_NAME = "[^"]*"/SATELLITE_NAME = "Office"/' linux_voice_assistant/satellite.py
systemctl --user restart lva
```

## Keeping Your Fork Updated

### Pull upstream changes from OHF-Voice:

```bash
cd /srv/jarvis/linux-voice-assistant-fork
git remote add upstream https://github.com/OHF-Voice/linux-voice-assistant.git
git fetch upstream
git merge upstream/main
# Resolve any conflicts
git push github main
```

### Deploy updated code to satellites:

```bash
cd /srv/jarvis/linux-voice-assistant-fork
./deploy.sh
```

## Notes

- The `deploy.sh` script handles deployment to both satellites automatically
- It sets the correct SATELLITE_NAME for each device
- Both satellites will track your GitHub fork after step 4
- Future updates: edit locally, commit, push to GitHub, run deploy.sh

## Current Deployment (Using Local Fork)

Until you push to GitHub, satellites are deployed from local fork at `/srv/jarvis/linux-voice-assistant-fork` using the deployment script. This is working but not tracked in a remote git repository.
