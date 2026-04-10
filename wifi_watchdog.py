#!/usr/bin/env python3
"""
WiFi Watchdog for Raspberry Pi satellites.
Detects brcmfmac driver hangs where wlan0 is UP but not passing traffic.
Reloads the WiFi module rather than rebooting the whole Pi.

On ethernet-only satellites (no wlan0), this script exits immediately.
"""
import os
import subprocess
import time
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/home/lva/wifi_watchdog.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

PING_TARGET = "10.0.0.1"       # Router — always reachable if WiFi works
PING_COUNT = 3
CHECK_INTERVAL = 60             # seconds between checks
FAIL_THRESHOLD = 3              # consecutive failures before action
INTERFACE = "wlan0"


def ping_ok() -> bool:
    result = subprocess.run(
        ["ping", "-c", str(PING_COUNT), "-W", "2", "-q", PING_TARGET],
        capture_output=True
    )
    return result.returncode == 0


def reload_wifi():
    """Reload the brcmfmac module to recover from a driver hang."""
    log.warning("WiFi unresponsive — reloading brcmfmac module")
    subprocess.run(["sudo", "modprobe", "-r", "brcmfmac"], capture_output=True)
    time.sleep(2)
    subprocess.run(["sudo", "modprobe", "brcmfmac"], capture_output=True)
    time.sleep(5)
    subprocess.run(["sudo", "systemctl", "restart", "NetworkManager"], capture_output=True)
    time.sleep(10)
    # Ensure power save stays off after reload
    subprocess.run(["sudo", "/sbin/iw", "dev", INTERFACE, "set", "power_save", "off"],
                   capture_output=True)
    log.info("WiFi module reloaded, power save disabled")


def main():
    # Exit cleanly on ethernet-only devices — no wlan0, no WiFi to watch.
    if not os.path.exists(f"/sys/class/net/{INTERFACE}"):
        log.info(
            f"Interface {INTERFACE} not present — this device uses ethernet. "
            "WiFi watchdog is not needed. Exiting."
        )
        return

    log.info(f"WiFi watchdog started — checking {PING_TARGET} every {CHECK_INTERVAL}s")
    failures = 0

    while True:
        if ping_ok():
            if failures > 0:
                log.info(f"WiFi recovered after {failures} failures")
            failures = 0
        else:
            failures += 1
            log.warning(f"Ping failed ({failures}/{FAIL_THRESHOLD})")
            if failures >= FAIL_THRESHOLD:
                reload_wifi()
                failures = 0

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
