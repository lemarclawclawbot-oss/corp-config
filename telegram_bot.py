#!/usr/bin/env python3
"""
Corp Fleet — Two-Way Telegram Bot
Receives commands from Lemar via Telegram and routes them to fleet machines
via dispatch, or handles them directly. Also sends notifications.

Commands:
  /status          — Fleet status overview
  /dispatch <msg>  — Send task to ZBook (default)
  /zbook <msg>     — Send task to ZBook
  /lenovo <msg>    — Send task to Lenovo
  /chromebook <msg>— Send task to Chromebook
  /ollama          — Show Ollama model status
  /services        — Show running services
  /logs [n]        — Show last n dispatch logs (default 5)
  /help            — Show available commands
  <any text>       — Treated as dispatch to ZBook

Port: None (polling mode, no webhook needed)
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TG-BOT] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8646506736:AAEGoeGBhaq_BcTvwT8gLTbHRkyCT8kZQBE")
AUTHORIZED_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "8712086846"))

CORP_DIR = Path(__file__).parent
PROGRESS_FILE = CORP_DIR / "progress.json"
DISPATCH_LOG = CORP_DIR / "logs" / "dispatch.log"


def is_authorized(update: Update) -> bool:
    return update.effective_chat.id == AUTHORIZED_CHAT_ID


def unauthorized_reply():
    return "Unauthorized. This bot only responds to its owner."


# --- Helpers ---

def load_progress():
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except Exception:
        return {}


def run_local_cmd(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() or result.stderr.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "(command timed out)"
    except Exception as e:
        return f"(error: {e})"


def run_on_machine(machine, cmd, timeout=30):
    """Run a command on a fleet machine. Local for zbook, SSH for others."""
    machines = {
        "zbook": {"host": "localhost", "user": "lemai", "ssh": False},
        "lenovo": {"host": "100.66.197.79", "user": "lem-ai", "ssh": True},
        "chromebook": {"host": "100.82.232.25", "user": "lemarclawclawbot", "ssh": True},
    }
    m = machines.get(machine)
    if not m:
        return f"Unknown machine: {machine}"
    if not m["ssh"]:
        return run_local_cmd(cmd, timeout)
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 {m['user']}@{m['host']} '{cmd}'"
    return run_local_cmd(ssh_cmd, timeout)


# --- Command Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return
    await update.message.reply_text(
        "Corp Fleet Bot active.\n\n"
        "Commands:\n"
        "/status - Fleet overview\n"
        "/dispatch <task> - Send to ZBook\n"
        "/zbook <task> - Send to ZBook\n"
        "/lenovo <task> - Send to Lenovo\n"
        "/ollama - Model status\n"
        "/services - Running services\n"
        "/logs [n] - Recent dispatch logs\n"
        "/help - This message\n\n"
        "Or just type anything to dispatch to ZBook."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return

    data = load_progress()
    fleet = data.get("fleet", {})
    lines = ["FLEET STATUS\n"]

    for name, info in fleet.items():
        status = info.get("status", "unknown")
        icon = {"online": "🟢", "offline": "🔴"}.get(status, "🟡")
        role = info.get("role", "").replace("_", " ").title()
        lines.append(f"{icon} {name.upper()} — {role}")
        services = info.get("services", {})
        if services:
            svc_str = ", ".join(f"{k}:{v}" for k, v in services.items())
            lines.append(f"   Services: {svc_str}")
        hb = info.get("last_heartbeat", "")
        if hb:
            lines.append(f"   Last heartbeat: {hb[:19]}")
        lines.append("")

    await update.message.reply_text("\n".join(lines))


async def cmd_ollama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return

    output = run_local_cmd("ollama list 2>/dev/null")
    await update.message.reply_text(f"Ollama Models (ZBook):\n\n{output}")


async def cmd_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return

    checks = {
        "Ollama": "systemctl is-active ollama 2>/dev/null",
        "Dashboard (:5000)": "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/ 2>/dev/null",
        "Dispatch (:5001)": "curl -s -o /dev/null -w '%{http_code}' http://localhost:5001/login 2>/dev/null",
        "Tenant Comms (:5002)": "curl -s -o /dev/null -w '%{http_code}' http://localhost:5002/ 2>/dev/null",
    }

    lines = ["ZBook Services:\n"]
    for name, cmd in checks.items():
        result = run_local_cmd(cmd)
        status = "✅" if result in ("active", "200") else f"❌ ({result})"
        lines.append(f"{status} {name}")

    # Check Lenovo
    lenovo_ping = run_local_cmd("ping -c1 -W2 100.66.197.79 2>/dev/null && echo reachable || echo unreachable")
    lines.append(f"\n{'✅' if 'reachable' in lenovo_ping else '❌'} Lenovo (Tailscale)")

    chromebook_ping = run_local_cmd("ping -c1 -W2 100.82.232.25 2>/dev/null && echo reachable || echo unreachable")
    lines.append(f"{'✅' if 'reachable' in chromebook_ping else '❌'} Chromebook (Tailscale)")

    await update.message.reply_text("\n".join(lines))


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return

    n = 5
    if context.args:
        try:
            n = int(context.args[0])
        except ValueError:
            pass
    n = min(n, 20)

    if DISPATCH_LOG.exists():
        lines = DISPATCH_LOG.read_text().strip().split("\n")[-n:]
        await update.message.reply_text(f"Last {n} dispatch logs:\n\n" + "\n".join(lines))
    else:
        await update.message.reply_text("No dispatch logs yet.")


async def dispatch_to_machine(update: Update, context: ContextTypes.DEFAULT_TYPE, machine: str):
    """Run a command on a machine via shell and return output."""
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return

    if not context.args:
        await update.message.reply_text(f"Usage: /{machine} <command or task description>")
        return

    cmd = " ".join(context.args)
    await update.message.reply_text(f"Dispatching to {machine.upper()}...\n> {cmd}")

    # For simple shell commands, run directly
    output = run_on_machine(machine, cmd, timeout=60)

    # Truncate long output for Telegram (4096 char limit)
    if len(output) > 3800:
        output = output[:3800] + "\n\n... (truncated)"

    await update.message.reply_text(f"{machine.upper()} result:\n\n{output}")

    # Log it
    DISPATCH_LOG.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DISPATCH_LOG, "a") as f:
        f.write(f"{ts} | {machine} | [telegram] {cmd[:80]} | done\n")


async def cmd_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dispatch_to_machine(update, context, "zbook")


async def cmd_zbook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dispatch_to_machine(update, context, "zbook")


async def cmd_lenovo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dispatch_to_machine(update, context, "lenovo")


async def cmd_chromebook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dispatch_to_machine(update, context, "chromebook")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any plain text message gets dispatched to ZBook."""
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_reply())
        return

    cmd = update.message.text.strip()
    if not cmd:
        return

    await update.message.reply_text(f"Dispatching to ZBOOK...\n> {cmd}")
    output = run_on_machine("zbook", cmd, timeout=60)

    if len(output) > 3800:
        output = output[:3800] + "\n\n... (truncated)"

    await update.message.reply_text(f"ZBOOK result:\n\n{output}")

    DISPATCH_LOG.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DISPATCH_LOG, "a") as f:
        f.write(f"{ts} | zbook | [telegram] {cmd[:80]} | done\n")


# --- Outbound notification helper (for other scripts to import) ---

def send_notification(message, chat_id=None):
    """Send a one-way notification. Can be called from other scripts."""
    import requests
    cid = chat_id or AUTHORIZED_CHAT_ID
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": cid, "text": message}, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def main():
    logger.info("Starting Corp Fleet Telegram Bot (two-way)...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ollama", cmd_ollama))
    app.add_handler(CommandHandler("services", cmd_services))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("dispatch", cmd_dispatch))
    app.add_handler(CommandHandler("zbook", cmd_zbook))
    app.add_handler(CommandHandler("lenovo", cmd_lenovo))
    app.add_handler(CommandHandler("chromebook", cmd_chromebook))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info(f"Bot authorized for chat_id: {AUTHORIZED_CHAT_ID}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
