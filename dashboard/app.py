#!/usr/bin/env python3
"""Corp Mission Control Dashboard — serves real-time fleet status to all machines."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
PROGRESS_FILE = Path(__file__).parent.parent / "progress.json"
LOG_DIR = Path(__file__).parent.parent / "logs"

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Corp Mission Control</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace; padding: 20px; }
        h1 { color: #00ff88; text-align: center; margin-bottom: 20px; font-size: 1.8em; }
        .subtitle { color: #666; text-align: center; margin-bottom: 30px; font-size: 0.9em; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; }
        .card h2 { color: #00aaff; margin-bottom: 15px; font-size: 1.2em; }
        .card.zbook { border-color: #00ff88; }
        .card.lenovo { border-color: #ffaa00; }
        .card.chromebook { border-color: #aa88ff; }
        .status { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-left: 8px; }
        .status.online { background: #00ff8833; color: #00ff88; }
        .status.offline { background: #ff444433; color: #ff4444; }
        .status.unknown { background: #ffaa0033; color: #ffaa00; }
        .status.running { background: #00ff8833; color: #00ff88; }
        .status.pending { background: #ffaa0033; color: #ffaa00; }
        .role { color: #888; font-size: 0.85em; margin-bottom: 10px; }
        .services { margin: 10px 0; }
        .service-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #222; }
        .tasks { margin-top: 15px; }
        .tasks h3 { color: #ccc; font-size: 0.9em; margin-bottom: 8px; }
        .task { padding: 3px 0; font-size: 0.85em; }
        .task.done { color: #00ff88; }
        .task.done::before { content: "✓ "; }
        .task.progress { color: #ffaa00; }
        .task.progress::before { content: "⟳ "; }
        .task.todo { color: #666; }
        .task.todo::before { content: "○ "; }
        .footer { text-align: center; color: #444; margin-top: 30px; font-size: 0.8em; }
        .telegram-section { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .telegram-section h2 { color: #29b6f6; margin-bottom: 10px; }
        .log-entry { padding: 4px 0; font-size: 0.85em; border-bottom: 1px solid #1a1a1a; }
        .log-entry .time { color: #666; }
        .log-entry .msg { color: #e0e0e0; }
    </style>
</head>
<body>
    <h1>⬡ CORP MISSION CONTROL</h1>
    <div class="subtitle">Fleet Status — Auto-refreshes every 30s — Last update: {{ last_updated }}</div>

    <div class="grid">
        {% for name, machine in fleet.items() %}
        <div class="card {{ name }}">
            <h2>{{ name | upper }}
                <span class="status {{ machine.status }}">{{ machine.status }}</span>
            </h2>
            <div class="role">Role: {{ machine.role | replace('_', ' ') | title }}</div>
            {% if machine.ip and machine.ip != 'unknown' %}
            <div class="role">IP: {{ machine.ip }}{% if machine.mac %} | MAC: {{ machine.mac }}{% endif %}</div>
            {% endif %}
            {% if machine.gpu %}
            <div class="role">GPU: {{ machine.gpu }}</div>
            {% endif %}

            {% if machine.services %}
            <div class="services">
                {% for svc, status in machine.services.items() %}
                <div class="service-row">
                    <span>{{ svc }}</span>
                    <span class="status {{ status }}">{{ status }}</span>
                </div>
                {% endfor %}
            </div>
            {% endif %}

            {% if machine.ollama_models %}
            <div class="role">Models: {{ machine.ollama_models | join(', ') }}</div>
            {% endif %}

            {% if machine.tasks %}
            <div class="tasks">
                {% if machine.tasks.completed %}
                <h3>Completed</h3>
                {% for t in machine.tasks.completed %}
                <div class="task done">{{ t }}</div>
                {% endfor %}
                {% endif %}
                {% if machine.tasks.in_progress %}
                <h3>In Progress</h3>
                {% for t in machine.tasks.in_progress %}
                <div class="task progress">{{ t }}</div>
                {% endfor %}
                {% endif %}
                {% if machine.tasks.pending %}
                <h3>Pending</h3>
                {% for t in machine.tasks.pending %}
                <div class="task todo">{{ t }}</div>
                {% endfor %}
                {% endif %}
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    {% if logs %}
    <div class="telegram-section">
        <h2>📡 Recent Escalation Logs</h2>
        {% for log in logs %}
        <div class="log-entry">
            <span class="time">{{ log.time }}</span> —
            <span class="msg">{{ log.message }}</span>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div style="text-align:center;margin-bottom:20px;">
        <a href="http://localhost:5001" target="_blank" style="color:#00aaff;text-decoration:none;padding:8px 16px;border:1px solid #00aaff;border-radius:4px;font-size:0.85em;margin:0 8px;">Dispatch</a>
        <a href="http://localhost:5002" target="_blank" style="color:#ffaa00;text-decoration:none;padding:8px 16px;border:1px solid #ffaa00;border-radius:4px;font-size:0.85em;margin:0 8px;">Tenant Comms</a>
        <a href="http://localhost:5003" target="_blank" style="color:#aa88ff;text-decoration:none;padding:8px 16px;border:1px solid #aa88ff;border-radius:4px;font-size:0.85em;margin:0 8px;">Properties</a>
        <a href="http://localhost:5004" target="_blank" style="color:#ff88aa;text-decoration:none;padding:8px 16px;border:1px solid #ff88aa;border-radius:4px;font-size:0.85em;margin:0 8px;">Crews</a>
    </div>
    <div class="footer">Corp Fleet v1.0 — ZBook · Lenovo · Chromebook</div>
</body>
</html>
"""


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"fleet": {}, "last_updated": "unknown"}


def load_logs(limit=20):
    log_file = LOG_DIR / "escalation.log"
    if not log_file.exists():
        return []
    lines = log_file.read_text().strip().split("\n")[-limit:]
    logs = []
    for line in lines:
        if " | " in line:
            time_part, msg = line.split(" | ", 1)
            logs.append({"time": time_part, "message": msg})
    return logs


@app.route("/")
def dashboard():
    data = load_progress()
    logs = load_logs()
    return render_template_string(
        DASHBOARD_HTML,
        fleet=data.get("fleet", {}),
        last_updated=data.get("last_updated", "unknown"),
        logs=logs,
    )


@app.route("/api/status")
def api_status():
    return jsonify(load_progress())


@app.route("/api/heartbeat/<machine>", methods=["POST"])
def heartbeat(machine):
    data = load_progress()
    if machine in data.get("fleet", {}):
        data["fleet"][machine]["status"] = "online"
        data["fleet"][machine]["last_heartbeat"] = datetime.now().isoformat()
        data["last_updated"] = datetime.now().isoformat()
        with open(PROGRESS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return jsonify({"ok": True})
    return jsonify({"error": "unknown machine"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
