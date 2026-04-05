#!/usr/bin/env python3
"""
Fleet Observer — runs on all machines.
Monitors fleet health, sends heartbeats, triggers Wake-on-LAN, logs escalations.

Usage:
    python3 observer.py              # auto-detects which machine this is
    python3 observer.py --role zbook # force a role
"""

import argparse
import json
import logging
import os
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# Discord integration
sys.path.insert(0, str(Path(__file__).parent))
import discord_notify as discord

CORP_DIR = Path(__file__).parent
PROGRESS_FILE = CORP_DIR / "progress.json"
LOG_DIR = CORP_DIR / "logs"
LOG_FILE = LOG_DIR / "escalation.log"

# Fleet config
# Use Tailscale IP so all machines can reach ZBook regardless of subnet
ZBOOK_IP = "100.123.233.45"
ZBOOK_MAC = "38:ca:84:c7:56:2c"
DASHBOARD_PORT = 5000
OLLAMA_PORT = 11434
CHECK_INTERVAL = 60  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
log = logging.getLogger("observer")


def detect_role():
    """Auto-detect which machine we're on."""
    hostname = socket.gethostname().lower()
    if "zbook" in hostname or "hp" in hostname:
        return "zbook"
    elif "lenovo" in hostname:
        return "lenovo"
    else:
        # Check if we have a GPU (ZBook indicator)
        try:
            subprocess.run(["nvidia-smi"], capture_output=True, check=True)
            return "zbook"
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        # Check if Ollama is running locally (Lenovo indicator)
        try:
            urlopen(f"http://localhost:{OLLAMA_PORT}/api/tags", timeout=2)
            return "lenovo"
        except Exception:
            return "chromebook"


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"fleet": {}, "last_updated": "unknown", "telegram": {}}


def save_progress(data):
    data["last_updated"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_host_up(ip, port, timeout=3):
    """Check if a host:port is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def send_wol(mac_address):
    """Send Wake-on-LAN magic packet."""
    mac_bytes = bytes.fromhex(mac_address.replace(":", "").replace("-", ""))
    magic = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(magic, ("255.255.255.255", 9))
    sock.close()
    log.info(f"WoL magic packet sent to {mac_address}")


def send_heartbeat(dashboard_ip, machine_name):
    """Send heartbeat to dashboard."""
    try:
        url = f"http://{dashboard_ip}:{DASHBOARD_PORT}/api/heartbeat/{machine_name}"
        req = Request(url, method="POST", data=b"")
        urlopen(req, timeout=5)
    except Exception:
        pass  # Dashboard might not be up yet


def send_telegram(message, bot_token, chat_id):
    """Send Telegram escalation message."""
    if not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": f"🚨 Corp Alert: {message}"}).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
        log.info(f"Telegram sent: {message}")
    except Exception as e:
        log.warning(f"Telegram failed: {e}")


def check_ollama(ip="localhost"):
    """Check if Ollama is responding."""
    return is_host_up(ip, OLLAMA_PORT)


def check_dashboard(ip=ZBOOK_IP):
    """Check if dashboard is responding."""
    return is_host_up(ip, DASHBOARD_PORT)


def run_zbook():
    """ZBook observer — monitors local services, updates progress."""
    log.info("Observer started: ZBook (heavy lifter)")
    while True:
        try:
            data = load_progress()
            zbook = data.get("fleet", {}).get("zbook", {})

            # Check local services
            ollama_up = check_ollama("localhost")
            dashboard_up = check_dashboard("localhost")

            zbook["status"] = "online"
            zbook["services"]["ollama"] = "running" if ollama_up else "offline"
            zbook["services"]["dashboard"] = "running" if dashboard_up else "offline"
            zbook["services"]["observer"] = "running"
            zbook["last_heartbeat"] = datetime.now().isoformat()

            data["fleet"]["zbook"] = zbook
            save_progress(data)

            if not ollama_up:
                log.warning("Ollama is down — attempting restart")
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                discord.alert("zbook", "Ollama went down — auto-restarting")

            # Discord heartbeat
            discord.heartbeat("zbook")

            log.info(f"ZBook OK | Ollama: {'up' if ollama_up else 'DOWN'} | Dashboard: {'up' if dashboard_up else 'DOWN'}")
        except Exception as e:
            log.error(f"Observer error: {e}")

        time.sleep(CHECK_INTERVAL)


def run_lenovo():
    """Lenovo observer — monitors fleet, wakes ZBook if needed."""
    log.info("Observer started: Lenovo (router/relay)")
    zbook_was_down = False

    while True:
        try:
            data = load_progress()
            lenovo = data.get("fleet", {}).get("lenovo", {})

            # Update own status
            lenovo["status"] = "online"
            lenovo["services"]["observer"] = "running"
            lenovo["last_heartbeat"] = datetime.now().isoformat()

            # Check ZBook
            zbook_up = is_host_up(ZBOOK_IP, OLLAMA_PORT)

            if not zbook_up:
                if not zbook_was_down:
                    log.warning(f"ZBook appears offline — sending WoL to {ZBOOK_MAC}")
                    send_wol(ZBOOK_MAC)
                    telegram = data.get("telegram", {})
                    send_telegram(
                        f"ZBook is offline. WoL sent to {ZBOOK_MAC}.",
                        telegram.get("bot_token", ""),
                        telegram.get("chat_id", ""),
                    )
                    discord.alert("lenovo", f"ZBook offline — WoL sent to {ZBOOK_MAC}")
                zbook_was_down = True
                data["fleet"]["zbook"]["status"] = "offline"
            else:
                if zbook_was_down:
                    log.info("ZBook is back online")
                    discord.task_done("lenovo", "ZBook wake-up confirmed")
                zbook_was_down = False
                send_heartbeat(ZBOOK_IP, "lenovo")

            # Discord heartbeat
            discord.heartbeat("lenovo")

            data["fleet"]["lenovo"] = lenovo
            save_progress(data)

            log.info(f"Lenovo OK | ZBook: {'up' if zbook_up else 'DOWN'}")
        except Exception as e:
            log.error(f"Observer error: {e}")

        time.sleep(CHECK_INTERVAL)


def run_chromebook():
    """Chromebook observer — read-only monitoring, heartbeat only."""
    log.info("Observer started: Chromebook (dashboard viewer)")
    while True:
        try:
            data = load_progress()
            cb = data.get("fleet", {}).get("chromebook", {})

            cb["status"] = "online"
            cb["services"]["observer"] = "running"
            cb["last_heartbeat"] = datetime.now().isoformat()

            # Check ZBook dashboard
            dashboard_up = check_dashboard(ZBOOK_IP)
            cb["services"]["browser_dashboard"] = "connected" if dashboard_up else "disconnected"

            data["fleet"]["chromebook"] = cb
            save_progress(data)

            send_heartbeat(ZBOOK_IP, "chromebook")
            discord.heartbeat("chromebook")

            log.info(f"Chromebook OK | Dashboard: {'up' if dashboard_up else 'DOWN'}")
        except Exception as e:
            log.error(f"Observer error: {e}")

        time.sleep(CHECK_INTERVAL)


def main():
    LOG_DIR.mkdir(exist_ok=True)

    parser = argparse.ArgumentParser(description="Corp Fleet Observer")
    parser.add_argument("--role", choices=["zbook", "lenovo", "chromebook"], help="Force machine role")
    args = parser.parse_args()

    role = args.role or detect_role()

    runners = {
        "zbook": run_zbook,
        "lenovo": run_lenovo,
        "chromebook": run_chromebook,
    }
    runners[role]()


if __name__ == "__main__":
    main()
