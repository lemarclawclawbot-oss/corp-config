#!/usr/bin/env python3
"""
Corp Fleet — Discord Notification Module
Used by observer.py and any script that needs to post to Discord.

Channels:
  zbook      → #zbook-logs
  lenovo     → #lenovo-logs
  chromebook → #chromebook-logs
  fleet      → #fleet-status
  escalations→ #escalations
  directives → #directives (ZBook lead agent only)
"""

import json
import datetime
from urllib.request import Request, urlopen

WEBHOOKS = {
    "zbook":       "https://discord.com/api/webhooks/1490218149650501723/dj-dF9bBnEvcv4rDMKO6frfabkq689TAgPIx2tLLI168OTcOH3mA_nWwxcT9o9EoJdQQ",
    "lenovo":      "https://discord.com/api/webhooks/1490218837239664751/bVAkTtPwLkxjRhNJ5b27luVvugisZE09tQqxhtFSj4bSLZioK01RPRH2lveL30HD6c17",
    "chromebook":  "https://discord.com/api/webhooks/1490219237690577060/djq2puhrEEtYTGyncXMCrKCiqcdM3JLwh1vKNAkbDZL0KdkR4H3hOS1fV2UN760FAykz",
    "fleet":       "https://discord.com/api/webhooks/1490219510131593328/yCoZMI9Q23p_8anGQj3dogNSl7hew2fVQxvU52-1oLZ979tdhkSSsb2UaDeiyr3t0NhT",
    "escalations": "https://discord.com/api/webhooks/1490219875896000607/eEUpBlFALJDJeFGN1PowutbNVXWuG_v_bV0tUJWxzQOaaDZRadbBOplypRijgCCTiMND",
}


def _ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def post(channel, message, username=None):
    """Post a message to a Discord channel via webhook."""
    url = WEBHOOKS.get(channel)
    if not url:
        return None
    payload = json.dumps({
        "content": message,
        "username": username or f"{channel}-observer",
    }).encode()
    try:
        req = Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "User-Agent": "CorpFleet/1.0",
        })
        resp = urlopen(req, timeout=10)
        return resp.status
    except Exception:
        return None


def heartbeat(machine):
    """Post heartbeat to machine channel + fleet-status."""
    msg = f"\U0001f49f `[{_ts()}]` **{machine.upper()}** is alive"
    post(machine, msg, f"{machine}-observer")
    post("fleet", msg, f"{machine}-observer")


def task_done(machine, task_name, result="success"):
    """Post task completion to machine channel + fleet-status."""
    emoji = "\u2705" if result == "success" else "\u274c"
    msg = f"{emoji} `[{_ts()}]` **{machine.upper()}** — `{task_name}` → {result}"
    post(machine, msg, f"{machine}-observer")
    post("fleet", msg, f"{machine}-observer")


def alert(machine, message):
    """Post alert to machine channel + escalations."""
    msg = f"\U0001f6a8 `[{_ts()}]` **{machine.upper()}** ALERT: {message}"
    post(machine, msg, f"{machine}-observer")
    post("escalations", msg, f"{machine}-observer")


def directive(message):
    """Post directive from ZBook lead agent to #directives."""
    msg = f"\u2b50 `[{_ts()}]` **ZBOOK LEAD** directive: {message}"
    post("directives", msg, "zbook-lead")
    post("fleet", msg, "zbook-lead")


if __name__ == "__main__":
    import sys
    machine = sys.argv[1] if len(sys.argv) > 1 else "zbook"
    action = sys.argv[2] if len(sys.argv) > 2 else "heartbeat"
    message = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""

    if action == "heartbeat":
        heartbeat(machine)
        print(f"Heartbeat sent for {machine}")
    elif action == "alert":
        alert(machine, message or "Test alert")
        print(f"Alert sent for {machine}")
    elif action == "directive":
        directive(message or "Test directive")
        print(f"Directive sent")
    elif action == "task":
        task_done(machine, message or "Test task")
        print(f"Task done sent for {machine}")
