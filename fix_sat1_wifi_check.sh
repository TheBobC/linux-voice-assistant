#!/bin/bash
# Fix satellite_health_monitor.py on sat1 to skip WiFi checks gracefully
# when the wlan0 interface is absent (sat1 uses ethernet, not WiFi).
#
# Run this from BobsJarvis once sat1 is reachable:
#   /srv/jarvis/linux-voice-assistant-fork/fix_sat1_wifi_check.sh
#
# What this script does:
#   1. Reads the health monitor to find the WiFi check code
#   2. Backs up the original
#   3. Adds an os.path.exists('/proc/net/wireless') guard so errors are
#      skipped gracefully instead of crashing/alerting
#   4. Reports what changed

set -e

SAT1="lva@10.0.0.150"
MONITOR="/home/lva/satellite_health_monitor.py"

echo "==================================================================="
echo "Patching sat1: satellite_health_monitor.py WiFi guard"
echo "==================================================================="

# --- Step 1: Verify sat1 is reachable ---
echo ""
echo "Checking sat1 connectivity..."
ssh -o ConnectTimeout=10 "$SAT1" "echo 'sat1 reachable'" || {
    echo "ERROR: Cannot reach sat1. Power it on and retry."
    exit 1
}

# --- Step 2: Show current errors ---
echo ""
echo "Recent errors on sat1 (last 30 lines):"
ssh "$SAT1" "journalctl --user -u lva -n 30 --no-pager 2>/dev/null \
    || journalctl -u lva -n 30 --no-pager 2>/dev/null \
    || echo 'Could not read journal'"

# --- Step 3: Show full health monitor so we can understand the WiFi code ---
echo ""
echo "=== Current satellite_health_monitor.py ==="
ssh "$SAT1" "cat -n $MONITOR" || {
    echo "ERROR: $MONITOR not found on sat1"
    echo "The health monitor may have a different name or location."
    echo "Try: ssh $SAT1 'find /home/lva -name \"*.py\" | xargs grep -l wlan 2>/dev/null'"
    exit 1
}

# --- Step 4: Back up the original ---
BACKUP="${MONITOR}.bak.$(date +%Y%m%d_%H%M%S)"
echo ""
echo "Backing up to $BACKUP ..."
ssh "$SAT1" "cp $MONITOR $BACKUP"

# --- Step 5: Apply targeted WiFi guard ---
# sed replacements to guard /proc/net/wireless reads.
# The guard checks if the wireless proc file exists before reading it.
echo ""
echo "Applying WiFi interface existence guards..."

ssh "$SAT1" python3 - << 'PYEOF'
import pathlib, sys, re, os

path = pathlib.Path("/home/lva/satellite_health_monitor.py")
text = path.read_text()

original = text

# Find all WiFi/wireless references to show the user
print("\n--- WiFi-related lines in original file ---")
for i, line in enumerate(text.splitlines(), 1):
    if any(kw in line for kw in ['wlan', 'wireless', 'WiFi', 'wifi', 'proc/net', 'iwconfig']):
        print(f"  {i:4d}: {line}")
print("--- End of WiFi-related lines ---\n")

if not any(kw in text for kw in ['wlan', '/proc/net/wireless', 'iwconfig', 'wifi', 'WiFi']):
    print("No WiFi-related code found in the health monitor.")
    print("The error notifications may come from a different source.")
    sys.exit(0)

# Strategy: wrap any block that reads /proc/net/wireless with an existence check.
# We find the indentation level of the open() call and wrap it.

# Also handle: subprocess calls to iwconfig
# and: any direct wlan0 socket operations

lines = text.splitlines(keepends=True)
new_lines = []
i = 0
changes_made = []

while i < len(lines):
    line = lines[i]
    stripped = line.rstrip()

    # Guard 1: with open('/proc/net/wireless') ...
    if '/proc/net/wireless' in line and 'open(' in line:
        indent = len(line) - len(line.lstrip())
        ind = ' ' * indent
        # Inject guard before the with-open block
        new_lines.append(f"{ind}# WiFi guard: skip if no wireless interface (ethernet-only device)\n")
        new_lines.append(f"{ind}if not __import__('os').path.exists('/proc/net/wireless'):\n")
        new_lines.append(f"{ind}    pass  # No wlan0 on this device - skip WiFi check\n")
        new_lines.append(f"{ind}else:\n")
        # Indent the open(...) line by 4 more spaces
        new_lines.append("    " + line)
        # Also indent the body of the with block
        i += 1
        while i < len(lines):
            body = lines[i]
            body_stripped = body.strip()
            body_indent = len(body) - len(body.lstrip()) if body.strip() else indent + 1
            # Continue indenting as long as we're inside the block
            if body.strip() == '' or body_indent > indent:
                new_lines.append("    " + body)
                i += 1
            else:
                break
        changes_made.append("Guarded /proc/net/wireless open() call")
        continue

    # Guard 2: iwconfig subprocess call
    if 'iwconfig' in line and ('subprocess' in line or 'os.popen' in line or 'Popen' in line):
        indent = len(line) - len(line.lstrip())
        ind = ' ' * indent
        new_lines.append(f"{ind}# WiFi guard: skip iwconfig if no wireless interface\n")
        new_lines.append(f"{ind}if not __import__('os').path.exists('/sys/class/net/wlan0'):\n")
        new_lines.append(f"{ind}    pass  # No wlan0 on this device - skip iwconfig\n")
        new_lines.append(f"{ind}else:\n")
        new_lines.append("    " + line)
        changes_made.append("Guarded iwconfig call")
        i += 1
        continue

    # Guard 3: direct wlan0 interface checks via socket or netifaces
    if 'wlan0' in line and any(kw in line for kw in ['socket', 'ioctl', 'netifaces', 'SIOCGIW']):
        indent = len(line) - len(line.lstrip())
        ind = ' ' * indent
        new_lines.append(f"{ind}# WiFi guard: skip wlan0 socket op if interface absent\n")
        new_lines.append(f"{ind}if not __import__('os').path.exists('/sys/class/net/wlan0'):\n")
        new_lines.append(f"{ind}    pass  # No wlan0 on this device\n")
        new_lines.append(f"{ind}else:\n")
        new_lines.append("    " + line)
        changes_made.append("Guarded wlan0 socket call")
        i += 1
        continue

    new_lines.append(line)
    i += 1

new_text = ''.join(new_lines)

if not changes_made:
    print("No changes were needed (patterns not matched structurally).")
    print("Manual review required. The WiFi-related lines are shown above.")
    sys.exit(0)

path.write_text(new_text)
print(f"Changes applied: {changes_made}")
print("\n--- Patched WiFi-related lines ---")
for j, ln in enumerate(new_text.splitlines(), 1):
    if any(kw in ln for kw in ['wlan', 'wireless', 'WiFi', 'wifi', 'proc/net', 'iwconfig', 'guard']):
        print(f"  {j:4d}: {ln}")
print("--- End of patched lines ---")
PYEOF

# --- Step 6: Find and restart any health monitor service ---
echo ""
echo "Checking for a health monitor service to restart..."
ssh "$SAT1" "systemctl --user list-units --all 2>/dev/null | grep -i 'health\|monitor\|satellite' \
    || systemctl list-units --all 2>/dev/null | grep -i 'health\|monitor\|satellite' \
    || echo '(no matching systemd service found)'"

echo ""
echo "Checking crontab for health monitor..."
ssh "$SAT1" "crontab -l 2>/dev/null | grep -i 'health\|monitor\|satellite_health' \
    || echo '(no matching cron job)'"

echo ""
echo "Looking for running health monitor process..."
ssh "$SAT1" "pgrep -a -f satellite_health_monitor 2>/dev/null || echo '(not currently running as a process)'"

# --- Step 7: Confirm LVA service is OK ---
echo ""
echo "LVA service status:"
ssh "$SAT1" "systemctl --user status lva --no-pager 2>/dev/null \
    || systemctl status lva --no-pager 2>/dev/null"

echo ""
echo "==================================================================="
echo "Done. If a health monitor process was found, restart it:"
echo "  Kill old: ssh $SAT1 'pkill -f satellite_health_monitor.py'"
echo "  Restart:  ssh $SAT1 'nohup python3 /home/lva/satellite_health_monitor.py &'"
echo ""
echo "Watch for errors to stop:"
echo "  ssh $SAT1 'journalctl --user -u lva -f'"
echo "==================================================================="
