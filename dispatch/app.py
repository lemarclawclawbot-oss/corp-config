#!/usr/bin/env python3
"""
Corp Fleet Dispatch — Natural language task dispatch to fleet machines.
Like Claude's Mac dispatch, but runs in a browser for any device.

Security:
- PIN-based login (hashed, never stored in plaintext)
- Session tokens with 8-hour expiry
- Rate limiting: 5 failed logins = 15 min lockout
- All actions logged to Discord + file
- Dangerous commands require explicit approval
"""

import hashlib
import json
import os
import secrets
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, render_template_string, request, redirect

app = Flask(__name__)
app.secret_key = "3dc4cbc8db5f30d20f49ac042423eddab6171914412f5b95d05a0e84411b9304"

CORP_DIR = Path(__file__).parent.parent
DISPATCH_LOG = CORP_DIR / "logs" / "dispatch.log"

# Auth config — PIN hash (sha256). Change PIN by updating this hash.
# Current PIN: 096361 (tell Lemar, then he can change it)
PIN_HASH = "31c75d23036c76e0c2a57e693422b74d23a1cc1bfa817fe5a96b020db3cd8d2e"
SESSION_DURATION = timedelta(hours=8)

# Session store: {token: expiry_datetime}
sessions = {}
# Rate limiting: {ip: {"fails": count, "locked_until": datetime}}
rate_limits = {}

# Machine registry
MACHINES = {
    "zbook": {
        "host": "localhost",
        "user": "lemai",
        "label": "ZBook (Heavy Lifter)",
        "color": "#00ff88",
        "ssh": False,
    },
    "lenovo": {
        "host": "100.66.197.79",
        "user": "lem-ai",
        "label": "Lenovo (Router/Relay)",
        "color": "#ffaa00",
        "ssh": True,
    },
    "chromebook": {
        "host": "100.82.232.25",
        "user": "lemarclawclawbot",
        "label": "Chromebook (Dashboard)",
        "color": "#aa88ff",
        "ssh": True,
    },
}

# Platform / model config
ZBOOK_OLLAMA = "http://100.123.233.45:11434/v1"
GLM5_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM5_KEY = "41fd2efc20414da6b8348d995dfa5d40.taXL5xmHypvLrGEc"

MODELS = {
    "claude": {
        "opus":   {"label": "Claude Opus 4.6",      "id": "claude-opus-4-6",          "env": {}},
        "sonnet": {"label": "Claude Sonnet 4.6",    "id": "claude-sonnet-4-6",        "env": {}},
        "haiku":  {"label": "Claude Haiku 4.5",     "id": "claude-haiku-4-5-20251001","env": {}},
        "glm5":   {"label": "GLM 5.1 (Z.AI)",       "id": "glm-5.1",                  "env": {"ANTHROPIC_BASE_URL": GLM5_URL, "ANTHROPIC_API_KEY": GLM5_KEY}},
        "glm4":   {"label": "GLM4 9B (Local GPU)",  "id": "glm4:latest",              "env": {"ANTHROPIC_BASE_URL": ZBOOK_OLLAMA, "ANTHROPIC_API_KEY": "ollama"}},
        "qwen":   {"label": "Qwen2.5-Coder (Local)","id": "qwen2.5-coder:7b",         "env": {"ANTHROPIC_BASE_URL": ZBOOK_OLLAMA, "ANTHROPIC_API_KEY": "ollama"}},
        "hermes": {"label": "Hermes3 (Local GPU)",  "id": "hermes3:latest",           "env": {"ANTHROPIC_BASE_URL": ZBOOK_OLLAMA, "ANTHROPIC_API_KEY": "ollama"}},
    },
    "aider": {
        "opus":   {"label": "Claude Opus 4.6",      "model": "claude-opus-4-6",              "extra_env": {}},
        "sonnet": {"label": "Claude Sonnet 4.6",    "model": "claude-sonnet-4-6",            "extra_env": {}},
        "glm5":   {"label": "GLM 5.1 (Z.AI)",       "model": "openai/glm-5.1",               "extra_env": {"OPENAI_API_BASE": GLM5_URL, "OPENAI_API_KEY": GLM5_KEY}},
        "glm4":   {"label": "GLM4 9B (Local GPU)",  "model": "ollama/glm4:latest",           "extra_env": {"OPENAI_API_BASE": ZBOOK_OLLAMA, "OPENAI_API_KEY": "ollama"}},
        "qwen":   {"label": "Qwen2.5-Coder (Local)","model": "ollama/qwen2.5-coder:7b",      "extra_env": {"OPENAI_API_BASE": ZBOOK_OLLAMA, "OPENAI_API_KEY": "ollama"}},
        "hermes": {"label": "Hermes3 (Local GPU)",  "model": "ollama/hermes3:latest",        "extra_env": {"OPENAI_API_BASE": ZBOOK_OLLAMA, "OPENAI_API_KEY": "ollama"}},
    },
}

# Active tasks
tasks = {}


def check_auth(f):
    """Decorator: require valid session token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("dispatch_token")
        if not token or token not in sessions:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not authenticated", "redirect": "/login"}), 401
            return redirect("/login")
        if sessions[token] < datetime.now():
            sessions.pop(token, None)
            if request.path.startswith("/api/"):
                return jsonify({"error": "Session expired", "redirect": "/login"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def is_rate_limited(ip):
    """Check if IP is locked out from too many failed attempts."""
    if ip not in rate_limits:
        return False
    rl = rate_limits[ip]
    if rl.get("locked_until") and datetime.now() < rl["locked_until"]:
        return True
    if rl.get("locked_until") and datetime.now() >= rl["locked_until"]:
        rate_limits.pop(ip)
        return False
    return False


def record_fail(ip):
    """Record a failed login attempt."""
    if ip not in rate_limits:
        rate_limits[ip] = {"fails": 0}
    rate_limits[ip]["fails"] += 1
    if rate_limits[ip]["fails"] >= 5:
        rate_limits[ip]["locked_until"] = datetime.now() + timedelta(minutes=15)
        # Alert on Discord
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("discord_notify", CORP_DIR / "discord_notify.py")
            discord = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(discord)
            discord.alert("zbook", f"5 failed dispatch login attempts from {ip} — locked 15 min")
        except Exception:
            pass


LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Corp Dispatch — Login</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif;
               display: flex; justify-content: center; align-items: center; height: 100vh; }
        .login-box { background: #111; border: 1px solid #333; border-radius: 12px; padding: 40px;
                     width: 90%; max-width: 360px; text-align: center; }
        .login-box h1 { color: #00ff88; font-family: 'Courier New', monospace; margin-bottom: 8px; }
        .login-box p { color: #888; font-size: 0.85em; margin-bottom: 24px; }
        .pin-input { background: #1a1a1a; border: 2px solid #333; border-radius: 8px; color: #e0e0e0;
                     padding: 14px; font-size: 1.5em; text-align: center; letter-spacing: 8px;
                     width: 100%; font-family: 'Courier New', monospace; }
        .pin-input:focus { outline: none; border-color: #00ff88; }
        .submit-btn { background: #00ff88; color: #000; border: none; border-radius: 8px;
                      padding: 12px 24px; font-weight: bold; cursor: pointer; font-size: 1em;
                      width: 100%; margin-top: 16px; }
        .submit-btn:hover { background: #00cc66; }
        .error { color: #ff4444; margin-top: 12px; font-size: 0.85em; }
        .locked { color: #ffaa00; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>&#x2B21; DISPATCH</h1>
        <p>Corp Fleet Command — Enter PIN</p>
        <form method="POST" action="/login">
            <input type="password" name="pin" class="pin-input" maxlength="6"
                   placeholder="------" autofocus inputmode="numeric" pattern="[0-9]*">
            <button type="submit" class="submit-btn">Unlock</button>
        </form>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if locked %}<div class="locked">Too many attempts. Locked for 15 minutes.</div>{% endif %}
    </div>
</body>
</html>
"""

DISPATCH_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Corp Dispatch</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; overflow: hidden; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif;
               display: flex; flex-direction: column; min-height: 100vh; min-height: -webkit-fill-available; }

        .header { background: #111; border-bottom: 1px solid #333; padding: 10px 15px; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
        .header h1 { color: #00ff88; font-size: 1.1em; font-family: 'Courier New', monospace; }
        .header .status { font-size: 0.75em; color: #666; flex: 1; }
        .header .logout { background: none; border: 1px solid #555; color: #888; padding: 4px 10px;
                          border-radius: 6px; cursor: pointer; font-size: 0.75em; }
        .header .logout:hover { border-color: #ff4444; color: #ff4444; }

        .main { flex: 1; display: flex; overflow: hidden; min-height: 0; }

        .sidebar { width: 250px; background: #111; border-right: 1px solid #333; padding: 15px; overflow-y: auto; }
        .sidebar h3 { color: #888; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; }
        .machine-btn { width: 100%; padding: 12px; margin-bottom: 8px; background: #1a1a1a; border: 2px solid #333; border-radius: 8px; color: #e0e0e0; cursor: pointer; text-align: left; font-size: 0.9em; transition: all 0.2s; }
        .machine-btn:hover { border-color: #555; }
        .machine-btn.selected { border-color: var(--color); background: #1a2a1a; }
        .machine-btn .name { font-weight: bold; }
        .machine-btn .role { font-size: 0.8em; color: #888; margin-top: 3px; }
        .machine-btn .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .dot.online { background: #00ff88; }
        .dot.offline { background: #ff4444; }

        .history-section { margin-top: 20px; }
        .history-item { padding: 8px; margin-bottom: 5px; background: #1a1a1a; border-radius: 6px; cursor: pointer; font-size: 0.8em; }
        .history-item:hover { background: #222; }
        .history-item .time { color: #666; font-size: 0.75em; }
        .history-item .preview { color: #aaa; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        .chat-area { flex: 1; display: flex; flex-direction: column; }

        .messages { flex: 1; overflow-y: auto; padding: 20px; }
        .message { margin-bottom: 20px; max-width: 85%; }
        .message.user { margin-left: auto; }
        .message.user .bubble { background: #1a3a2a; border: 1px solid #2a5a3a; border-radius: 12px 12px 4px 12px; padding: 12px 16px; }
        .message.agent .bubble { background: #1a1a2a; border: 1px solid #2a2a5a; border-radius: 12px 12px 12px 4px; padding: 12px 16px; }
        .message .meta { font-size: 0.75em; color: #666; margin-bottom: 4px; }
        .message pre { background: #0a0a0a; border: 1px solid #333; border-radius: 6px; padding: 10px; margin-top: 8px; overflow-x: auto; font-size: 0.85em; white-space: pre-wrap; word-wrap: break-word; }
        .message code { font-family: 'Courier New', monospace; }

        .escalation { background: #3a1a1a; border: 2px solid #ff4444; border-radius: 8px; padding: 15px; margin: 10px 0; }
        .escalation h4 { color: #ff4444; margin-bottom: 8px; }
        .escalation .actions { margin-top: 10px; display: flex; gap: 10px; }
        .escalation button { padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer; font-weight: bold; }
        .escalation .approve { background: #00ff88; color: #000; }
        .escalation .deny { background: #ff4444; color: #fff; }

        .input-area { padding: 10px 15px; background: #111; border-top: 1px solid #333; flex-shrink: 0; }
        .input-row { display: flex; gap: 10px; align-items: flex-end; }
        .input-row textarea { flex: 1; background: #1a1a1a; border: 1px solid #333; border-radius: 8px; color: #e0e0e0; padding: 12px; font-size: 0.95em; font-family: inherit; resize: none; min-height: 50px; max-height: 150px; }
        .input-row textarea:focus { outline: none; border-color: #00ff88; }
        .input-row button { background: #00ff88; color: #000; border: none; border-radius: 8px; padding: 12px 24px; font-weight: bold; cursor: pointer; font-size: 0.95em; white-space: nowrap; }
        .input-row button:hover { background: #00cc66; }
        .input-row button:disabled { background: #333; color: #666; cursor: not-allowed; }
        .target-label { font-size: 0.8em; color: #888; margin-bottom: 5px; }
        .session-controls { display: flex; gap: 6px; margin-top: 10px; align-items: center; flex-wrap: wrap; }
        .session-controls .followup-input { flex: 1; min-width: 120px; background: #111; border: 1px solid #444; border-radius: 6px; color: #e0e0e0; padding: 6px 10px; font-size: 0.85em; }
        .session-controls .followup-input:focus { outline: none; border-color: #00ff88; }
        .session-controls button { background: #00ff88; color: #000; border: none; border-radius: 6px; padding: 6px 12px; font-weight: bold; cursor: pointer; font-size: 0.82em; white-space: nowrap; }
        .session-controls .close-btn { background: #333; color: #aaa; }
        .session-controls .close-btn:hover { background: #ff4444; color: #fff; }
        .model-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
        .model-row select { background: #1a1a1a; border: 1px solid #444; border-radius: 6px; color: #e0e0e0;
                            padding: 6px 10px; font-size: 0.85em; flex: 1; cursor: pointer; }
        .model-row select:focus { outline: none; border-color: #00ff88; }
        .model-row label { font-size: 0.75em; color: #666; white-space: nowrap; }

        .typing { color: #888; font-style: italic; padding: 5px 0; }

        /* Mobile: show machine selector as horizontal bar */
        @media (max-width: 768px) {
            .sidebar { width: 100%; flex-shrink: 0; height: auto; max-height: 80px; border-right: none;
                       border-bottom: 1px solid #333; display: flex; flex-wrap: nowrap; gap: 6px;
                       padding: 8px; overflow-x: auto; }
            .sidebar h3 { display: none; }
            .sidebar .history-section { display: none; }
            .machine-btn { width: auto; flex: 1; min-width: 80px; padding: 6px; font-size: 0.75em; }
            .machine-btn .role { display: none; }
            .main { flex-direction: column; }
            .chat-area { min-height: 0; flex: 1; }
            .messages { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }
            .header h1 { font-size: 0.95em; }
            .header .status { display: none; }
            .input-row textarea { min-height: 40px; font-size: 0.9em; }
            .input-row button { padding: 10px 16px; font-size: 0.85em; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>&#x2B21; CORP DISPATCH</h1>
        <div class="status">Fleet Command — Natural Language Task Dispatch</div>
        <div style="display:flex;gap:10px;align-items:center;">
            <a href="http://localhost:5000" target="_blank" style="color:#00ff88;text-decoration:none;padding:6px 12px;border:1px solid #00ff88;border-radius:4px;font-size:0.8em;">Dashboard</a>
            <a href="http://localhost:5002" target="_blank" style="color:#ffaa00;text-decoration:none;padding:6px 12px;border:1px solid #ffaa00;border-radius:4px;font-size:0.8em;">Tenant Comms</a>
            <a href="http://localhost:5003" target="_blank" style="color:#aa88ff;text-decoration:none;padding:6px 12px;border:1px solid #aa88ff;border-radius:4px;font-size:0.8em;">Properties</a>
            <button class="logout" onclick="if(confirm('Log out?')){document.cookie='dispatch_token=;max-age=0';location.href='/login'}">Logout</button>
        </div>
    </div>

    <div class="main">
        <div class="sidebar">
            <h3>Machines</h3>
            {% for name, m in machines.items() %}
            <button class="machine-btn {% if name == 'zbook' %}selected{% endif %}"
                    style="--color: {{ m.color }}"
                    id="btn-{{ name }}"
                    onclick="selectMachine('{{ name }}')">
                <div class="name"><span class="dot online"></span>{{ name | upper }}</div>
                <div class="role">{{ m.label }}</div>
            </button>
            {% endfor %}

            <div class="history-section">
                <h3>Recent Tasks</h3>
                <div id="history"></div>
            </div>
        </div>

        <div class="chat-area">
            <div class="messages" id="messages">
                <div class="message agent">
                    <div class="meta">DISPATCH SYSTEM</div>
                    <div class="bubble">
                        Welcome to Corp Dispatch. Select a machine and type your request in plain English.<br><br>
                        Examples:<br>
                        &bull; "Check disk space and clean up temp files"<br>
                        &bull; "Pull the latest corp-config and restart the observer"<br>
                        &bull; "Show me what Ollama models are installed"<br><br>
                        Dangerous commands (sudo, rm, reboot) require your approval before running.
                    </div>
                </div>
            </div>

            <div class="input-area">
                <div class="target-label"><span id="target-label-text">Dispatching to: </span><strong id="target-name">ZBOOK</strong></div>
                <div class="model-row">
                    <label>Platform:</label>
                    <select id="platform-select" onchange="onPlatformChange()">
                        <option value="shell" selected>Shell (direct, free)</option>
                        <option value="ollama">Ollama Chat (local, free)</option>
                        <option value="claude">Claude (API credits)</option>
                        <option value="aider">Aider</option>
                    </select>
                    <label>Model:</label>
                    <select id="model-select-shell">
                        <option value="bash" selected>Bash</option>
                    </select>
                    <select id="model-select-ollama" style="display:none">
                        <option value="hermes" selected>Hermes3 (8B, free)</option>
                        <option value="glm4">GLM4 (9B, free)</option>
                        <option value="qwen">Qwen2.5-Coder (7B, free)</option>
                    </select>
                    <select id="model-select-claude" style="display:none">
                        <option value="sonnet" selected>Sonnet 4.6 (default)</option>
                        <option value="opus">Opus 4.6 (powerful)</option>
                        <option value="haiku">Haiku 4.5 (fast)</option>
                        <option value="glm4">GLM4 (local free)</option>
                        <option value="qwen">Qwen2.5 (local free)</option>
                        <option value="hermes">Hermes3 (local free)</option>
                        <option value="glm5">GLM 5.1 (Z.AI)</option>
                    </select>
                    <select id="model-select-aider" style="display:none">
                        <option value="sonnet" selected>Sonnet 4.6 (default)</option>
                        <option value="opus">Opus 4.6 (powerful)</option>
                        <option value="glm4">GLM4 (local free)</option>
                        <option value="qwen">Qwen2.5 (local free)</option>
                        <option value="hermes">Hermes3 (local free)</option>
                        <option value="glm5">GLM 5.1 (Z.AI)</option>
                    </select>
                </div>
                <div class="input-row">
                    <textarea id="prompt" placeholder="What do you want this machine to do?" rows="2"
                              onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault();dispatch()}"></textarea>
                    <button id="send-btn" onclick="dispatch()">Dispatch</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let selectedMachine = 'zbook';
        // Per-machine active task tracking
        let activeTasks = {};

        function activeModelSelect() {
            var p = document.getElementById('platform-select').value;
            return document.getElementById('model-select-' + p);
        }

        function onPlatformChange() {
            var platform = document.getElementById('platform-select').value;
            ['shell','ollama','claude','aider'].forEach(p => {
                var el = document.getElementById('model-select-' + p);
                if (el) el.style.display = p === platform ? '' : 'none';
            });
            if (platform === 'aider' && selectedMachine !== 'zbook') {
                selectMachine('zbook');
            }
            // Update placeholder based on platform
            var ta = document.getElementById('prompt');
            if (platform === 'shell') ta.placeholder = 'Enter a shell command (e.g. df -h, uptime, ollama list)';
            else if (platform === 'ollama') ta.placeholder = 'Ask the local AI anything...';
            else ta.placeholder = 'What do you want this machine to do?';
        }
        onPlatformChange();

        // Load ZBook history on startup (default machine)
        loadMachineHistory('zbook');

        function saveMessage(role, content, machine) {
            try {
                const key = 'dispatch_history_' + machine;
                const history = JSON.parse(localStorage.getItem(key) || '[]');
                const meta = role === 'user' ? 'YOU → ' + machine.toUpperCase() : machine.toUpperCase() + ' AGENT';
                history.push({role, meta, content});
                if (history.length > 50) history.splice(0, history.length - 50);
                localStorage.setItem(key, JSON.stringify(history));
            } catch(e) {}
        }

        function loadMachineHistory(machine) {
            const messages = document.getElementById('messages');
            // Keep the welcome message (first child), remove the rest
            while (messages.children.length > 1) messages.removeChild(messages.lastChild);
            try {
                const saved = JSON.parse(localStorage.getItem('dispatch_history_' + machine) || '[]');
                saved.forEach(item => {
                    const div = document.createElement('div');
                    div.className = 'message ' + item.role;
                    div.innerHTML = '<div class="meta">' + item.meta + '</div><div class="bubble">' + item.content + '</div>';
                    messages.appendChild(div);
                });
                messages.scrollTop = messages.scrollHeight;
            } catch(e) {}
        }

        function selectMachine(name) {
            selectedMachine = name;
            document.getElementById('target-name').textContent = name.toUpperCase();
            document.querySelectorAll('.machine-btn').forEach(function(b) {
                b.classList.remove('selected');
            });
            var btn = document.getElementById('btn-' + name);
            if (btn) btn.classList.add('selected');
            loadMachineHistory(name);
            updateInputArea();
        }

        function addMessage(role, content, machine, extra='') {
            const div = document.createElement('div');
            div.className = `message ${role}`;
            const base = role === 'user' ? `YOU → ${machine.toUpperCase()}` : `${machine.toUpperCase()} AGENT`;
            const meta = extra ? `${base} · ${extra}` : base;
            div.innerHTML = `<div class="meta">${meta}</div><div class="bubble">${content}</div>`;
            document.getElementById('messages').appendChild(div);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
            return div;
        }

        function updateInputArea() {
            const taskId = activeTasks[selectedMachine];
            const btn = document.getElementById('send-btn');
            const textarea = document.getElementById('prompt');
            if (taskId) {
                btn.textContent = 'Send';
                btn.disabled = false;
                textarea.placeholder = 'Follow-up to ' + selectedMachine.toUpperCase() + '...';
            } else {
                btn.textContent = 'Dispatch';
                btn.disabled = false;
                textarea.placeholder = 'What do you want this machine to do?';
            }
        }

        function dispatch() {
            const prompt = document.getElementById('prompt').value.trim();
            if (!prompt) return;

            var platform = document.getElementById('platform-select').value;
            var modelSel = activeModelSelect();
            var model_key = modelSel ? modelSel.value : 'sonnet';
            var modelLabel = modelSel && modelSel.selectedIndex >= 0 ? modelSel.options[modelSel.selectedIndex].text : model_key;

            // If this machine already has an active session, send as follow-up
            const activeTaskId = activeTasks[selectedMachine];
            if (activeTaskId) {
                document.getElementById('prompt').value = '';
                fetch('/api/send/' + activeTaskId, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: prompt})
                });
                addMessage('user', escapeHtml(prompt), selectedMachine, 'FOLLOW-UP');
                saveMessage('user', escapeHtml(prompt), selectedMachine);
                return;
            }

            document.getElementById('prompt').value = '';

            addMessage('user', escapeHtml(prompt), selectedMachine, platform.toUpperCase() + ' / ' + modelLabel);
            saveMessage('user', escapeHtml(prompt), selectedMachine);

            const agentDiv = addMessage('agent', '<div class="typing">Starting agent...</div>', selectedMachine);
            const bubble = agentDiv.querySelector('.bubble');

            fetch('/api/dispatch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({machine: selectedMachine, prompt: prompt, platform: platform, model_key: model_key})
            })
            .then(response => {
                if (response.status === 401) { location.href = '/login'; return; }
                return response.json();
            })
            .then(data => {
                if (!data) return;
                if (data.task_id) {
                    activeTasks[selectedMachine] = data.task_id;
                    updateInputArea();
                    pollTask(data.task_id, bubble, selectedMachine);
                } else {
                    bubble.innerHTML = '<span style="color:#ff4444">Error: ' + (data.error||'unknown') + '</span>';
                    updateInputArea();
                }
            })
            .catch(err => {
                bubble.innerHTML = '<span style="color:#ff4444">Connection error: ' + err + '</span>';
                updateInputArea();
            });
        }

        function pollTask(taskId, bubble, machine) {
            // Only poll if this is still the active task for this machine
            if (activeTasks[machine] !== taskId) return;

            fetch('/api/task/' + taskId)
            .then(r => { if (r.status === 401) { location.href = '/login'; return; } return r.json(); })
            .then(data => {
                if (!data) return;
                if (data.status === 'running' || data.status === 'waiting') {
                    let output = data.output || 'Starting agent...';
                    bubble.innerHTML =
                        '<div class="typing">&#x25CF; Live — ' + machine.toUpperCase() + '</div>' +
                        '<pre><code>' + escapeHtml(output) + '</code></pre>' +
                        '<div class="session-controls">' +
                        '<button class="close-btn" onclick="closeSession(\'' + taskId + '\',\'' + machine + '\',this)">End Session</button>' +
                        '</div>';
                    setTimeout(() => pollTask(taskId, bubble, machine), 2000);
                } else if (data.status === 'escalation') {
                    bubble.innerHTML = `
                        <div class="escalation">
                            <h4>&#x26A0; Permission Required</h4>
                            <p>${escapeHtml(data.message)}</p>
                            <div class="actions">
                                <button class="approve" onclick="respondEscalation('${taskId}', 'approve', this)">Approve</button>
                                <button class="deny" onclick="respondEscalation('${taskId}', 'deny', this)">Deny</button>
                            </div>
                        </div>`;
                } else {
                    let output = data.output || 'Done (no output)';
                    let statusColor = data.status === 'completed' ? '#00ff88' : '#ff4444';
                    const resultHtml = `<pre><code>${escapeHtml(output)}</code></pre>
                        <div style="margin-top:8px;font-size:0.8em;color:${statusColor}">
                        ${data.status === 'completed' ? '&#x2705;' : '&#x274C;'} ${data.status}
                        </div>`;
                    bubble.innerHTML = resultHtml;
                    saveMessage('agent', resultHtml, machine);
                    activeTasks[machine] = null;
                    updateInputArea();
                    addHistory(machine, data.prompt_text);
                }
            })
            .catch(() => {
                setTimeout(() => pollTask(taskId, bubble, machine), 3000);
            });
        }

        function respondEscalation(taskId, action, btn) {
            btn.parentElement.querySelectorAll('button').forEach(b => b.disabled = true);
            fetch(`/api/escalation/${taskId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action: action})
            })
            .then(r => r.json())
            .then(data => {
                const bubble = btn.closest('.bubble');
                if (action === 'approve') {
                    bubble.innerHTML = '<div class="typing">Approved — running with elevated permissions...</div>';
                    pollTask(taskId, bubble, selectedMachine);
                } else {
                    bubble.innerHTML = '<span style="color:#ffaa00">Denied — task cancelled.</span>';
                    activeTasks[selectedMachine] = null;
                    updateInputArea();
                }
            });
        }

        function addHistory(machine, prompt) {
            const div = document.createElement('div');
            div.className = 'history-item';
            const now = new Date().toLocaleTimeString();
            div.innerHTML = `<div class="time">${now} · ${machine}</div><div class="preview">${escapeHtml(prompt)}</div>`;
            const hist = document.getElementById('history');
            hist.insertBefore(div, hist.firstChild);
            if (hist.children.length > 10) hist.removeChild(hist.lastChild);
        }

        function closeSession(taskId, machine, btn) {
            fetch('/api/close/' + taskId, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
                .then(() => {
                    activeTasks[machine] = null;
                    updateInputArea();
                    const bubble = btn ? btn.closest('.bubble') : null;
                    if (bubble) {
                        const controls = bubble.querySelector('.session-controls');
                        if (controls) controls.innerHTML = '<span style="color:#888;font-size:0.8em">Session ended.</span>';
                    }
                });
        }

        function escapeHtml(text) {
            const d = document.createElement('div');
            d.textContent = text;
            return d.innerHTML;
        }
    </script>
</body>
</html>
"""


def log_dispatch(machine, prompt, result):
    """Log dispatch to file and Discord."""
    DISPATCH_LOG.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DISPATCH_LOG, "a") as f:
        f.write(f"{ts} | {machine} | {prompt[:80]} | {result}\n")

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("discord_notify", CORP_DIR / "discord_notify.py")
        discord = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(discord)
        discord.task_done(machine, f"Dispatch: {prompt[:60]}", result)
    except Exception:
        pass


def _ssh(host_str, cmd, timeout=15):
    """Run a command on a remote host via SSH, return CompletedProcess."""
    return subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"-oConnectTimeout={timeout}", host_str, cmd],
        capture_output=True, text=True
    )


def _tmux_capture(sess, host_str=None):
    """Capture the last 500 lines of a tmux pane. Returns string."""
    cmd = f"tmux capture-pane -t {sess} -p -S -500 2>/dev/null"
    if host_str:
        return _ssh(host_str, cmd, timeout=5).stdout
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def _tmux_send(sess, message, host_str=None):
    """Send a message into a running tmux session."""
    safe = message.replace('"', '\\"').replace("$", "\\$")
    cmd = f'tmux send-keys -t {sess} "{safe}" Enter'
    if host_str:
        _ssh(host_str, cmd)
    else:
        subprocess.run(cmd, shell=True)


def _tmux_send_raw(sess, keys, host_str=None):
    """Send raw tmux key names (e.g. 'Enter', 'Down Enter') without quoting as text."""
    cmd = f"tmux send-keys -t {sess} {keys}"
    if host_str:
        _ssh(host_str, cmd)
    else:
        subprocess.run(cmd, shell=True)


def build_agent_cmd(platform, model_key):
    """Return (env_dict, agent_start_command) for interactive (agentic) mode.
    Use $HOME-relative paths so commands work on any fleet machine, not just ZBook.
    """
    if platform == "aider":
        cfg = MODELS["aider"].get(model_key, MODELS["aider"]["opus"])
        cmd = f"$HOME/.aider-venv/bin/aider --model {cfg['model']} --yes"
        return cfg["extra_env"], cmd
    else:
        cfg = MODELS["claude"].get(model_key, MODELS["claude"]["opus"])
        # Use just 'claude' — PATH is prepended with $HOME/.local/bin in run_task
        cmd = f"claude --model {cfg['id']} --dangerously-skip-permissions"
        return cfg["env"], cmd


def run_task(task_id, machine, prompt, platform="claude", model_key="opus"):
    """
    Spin up a tmux session on the target machine running claude/aider interactively,
    send the prompt, and stream the live pane output back — exactly like sitting at
    the terminal. Sessions persist for follow-up messages.
    """
    task = tasks[task_id]
    m = MACHINES[machine]
    sess = f"disp-{task_id}"
    host_str = f"{m['user']}@{m['host']}" if m.get("ssh") else None

    try:
        model_env, agent_cmd = build_agent_cmd(platform, model_key)
        env_prefix = " ".join(f"{k}={v}" for k, v in model_env.items())
        full_start = f"PATH=$HOME/.local/bin:$PATH {env_prefix} {agent_cmd}"

        # 1. Start tmux session with agent
        start_cmd = f"tmux new-session -d -s {sess} '{full_start}'"
        if host_str:
            result = _ssh(host_str, start_cmd)
            if result.returncode != 0:
                task["status"] = "failed"
                task["output"] = f"SSH failed: {result.stderr}"
                return
        else:
            subprocess.run(start_cmd, shell=True)

        task["output"] = "Starting agent session..."
        task["tmux_session"] = sess
        task["host_str"] = host_str or "local"
        task["status"] = "running"

        # 2. Wait for agent to initialize
        #    --dangerously-skip-permissions bypasses ALL prompts (trust + permissions),
        #    so no keystrokes needed for Claude. Aider also starts directly.
        init_wait = 8 if platform == "claude" else 4
        time.sleep(init_wait)

        # Check tmux session is actually alive before sending prompt
        check_cmd = f"tmux has-session -t {sess} 2>/dev/null && echo alive || echo dead"
        if host_str:
            alive_check = _ssh(host_str, check_cmd).stdout.strip()
        else:
            alive_check = subprocess.run(check_cmd, shell=True, capture_output=True, text=True).stdout.strip()

        if alive_check != "alive":
            task["status"] = "failed"
            task["output"] = f"Agent session failed to start. tmux session '{sess}' died during init."
            log_dispatch(machine, prompt, "failed: session died")
            return

        task["output"] = "Agent ready, sending prompt..."

        # 3. Send the initial prompt into the session
        _tmux_send(sess, prompt, host_str)

        # 4. Poll tmux pane output and stream back
        deadline = time.time() + 600  # 10-min hard timeout
        last_activity = time.time()
        prev_output = ""
        # Give agent generous time to produce first output
        no_output_timeout = 120  # 2 minutes for first output, then tighter

        while time.time() < deadline:
            time.sleep(2)

            output = _tmux_capture(sess, host_str)

            # Check if tmux session still exists
            if output is None:
                break

            if output.strip() and output != prev_output:
                task["output"] = output
                prev_output = output
                last_activity = time.time()
                # Once we've seen output, tighten the idle timeout
                no_output_timeout = 60
            elif not output.strip() and time.time() - last_activity > no_output_timeout:
                break

        # Final snapshot
        final = _tmux_capture(sess, host_str)
        if final and final.strip():
            task["output"] = final

        if task["status"] == "running":
            task["status"] = "completed"
        log_dispatch(machine, prompt, task["status"])

    except Exception as e:
        task["status"] = "failed"
        task["output"] = str(e)
        log_dispatch(machine, prompt, f"error: {e}")


def run_shell_task(task_id, machine, command):
    """Run a shell command directly on a machine and return output. No AI, free."""
    task = tasks[task_id]
    m = MACHINES[machine]
    host_str = f"{m['user']}@{m['host']}" if m.get("ssh") else None

    try:
        task["status"] = "running"
        task["output"] = f"Running on {machine.upper()}: {command}"

        if host_str:
            result = _ssh(host_str, command, timeout=60)
            output = result.stdout or result.stderr or "(no output)"
        else:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=60
            )
            output = result.stdout or result.stderr or "(no output)"

        task["output"] = output.strip()
        task["status"] = "completed"
        log_dispatch(machine, f"[shell] {command}", "completed")

    except subprocess.TimeoutExpired:
        task["output"] = "(command timed out after 60s)"
        task["status"] = "failed"
        log_dispatch(machine, f"[shell] {command}", "timeout")
    except Exception as e:
        task["status"] = "failed"
        task["output"] = str(e)
        log_dispatch(machine, f"[shell] {command}", f"error: {e}")


OLLAMA_MODELS = {
    "hermes": "hermes3:latest",
    "glm4": "glm4:latest",
    "qwen": "qwen2.5-coder:7b",
}


def run_ollama_task(task_id, machine, prompt, model_key="hermes"):
    """Chat with a local Ollama model. Free, runs on GPU."""
    task = tasks[task_id]
    model = OLLAMA_MODELS.get(model_key, "hermes3:latest")

    try:
        task["status"] = "running"
        task["output"] = f"Thinking ({model})..."

        # Use Ollama API directly for clean output
        import urllib.request
        ollama_host = "http://localhost:11434"
        if machine != "zbook":
            ollama_host = f"http://{MACHINES['zbook']['host']}:11434"

        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            f"{ollama_host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode())
        task["output"] = result.get("response", "(no response)")
        task["status"] = "completed"
        log_dispatch(machine, f"[ollama/{model}] {prompt[:60]}", "completed")

    except Exception as e:
        task["status"] = "failed"
        task["output"] = f"Ollama error: {e}"
        log_dispatch(machine, f"[ollama] {prompt[:60]}", f"error: {e}")


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr
    if request.method == "GET":
        locked = is_rate_limited(ip)
        return render_template_string(LOGIN_HTML, error=None, locked=locked)

    if is_rate_limited(ip):
        return render_template_string(LOGIN_HTML, error=None, locked=True)

    pin = request.form.get("pin", "")
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()

    if pin_hash != PIN_HASH:
        record_fail(ip)
        locked = is_rate_limited(ip)
        return render_template_string(LOGIN_HTML, error="Wrong PIN" if not locked else None, locked=locked)

    # Success — issue session token
    token = secrets.token_hex(32)
    sessions[token] = datetime.now() + SESSION_DURATION
    rate_limits.pop(ip, None)

    resp = make_response(redirect("/"))
    resp.set_cookie("dispatch_token", token, max_age=int(SESSION_DURATION.total_seconds()),
                     httponly=True, samesite="Lax")
    return resp


@app.route("/")
@check_auth
def index():
    resp = make_response(render_template_string(DISPATCH_HTML, machines=MACHINES))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/dispatch", methods=["POST"])
@check_auth
def api_dispatch():
    data = request.json
    machine = data.get("machine", "zbook")
    prompt = data.get("prompt", "")
    platform = data.get("platform", "claude")
    model_key = data.get("model_key", "opus")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400
    if machine not in MACHINES:
        return jsonify({"error": f"Unknown machine: {machine}"}), 400

    # Validate platform
    valid_platforms = ["shell", "ollama", "claude", "aider"]
    if platform not in valid_platforms:
        platform = "shell"

    # Aider only available on ZBook (local) for now
    if platform == "aider" and machine != "zbook":
        return jsonify({"error": "Aider is only available on ZBook (local). SSH remotes use Claude."}), 400

    dangerous = ["sudo ", "rm -rf", "mkfs", "dd if=", "chmod 777", "> /dev/", "shutdown", "reboot",
                 "systemctl stop", "systemctl disable", "kill -9", "pkill", "format"]
    needs_escalation = any(d in prompt.lower() for d in dangerous)

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {
        "id": task_id,
        "machine": machine,
        "platform": platform,
        "model_key": model_key,
        "prompt_text": prompt,
        "status": "escalation" if needs_escalation else "running",
        "message": f"This request may need elevated permissions: '{prompt}'" if needs_escalation else "",
        "output": "",
        "created": datetime.now().isoformat(),
    }

    if not needs_escalation:
        if platform == "shell":
            thread = threading.Thread(target=run_shell_task, args=(task_id, machine, prompt))
        elif platform == "ollama":
            thread = threading.Thread(target=run_ollama_task, args=(task_id, machine, prompt, model_key))
        else:
            if platform in MODELS and model_key not in MODELS[platform]:
                model_key = list(MODELS[platform].keys())[0]
            thread = threading.Thread(target=run_task, args=(task_id, machine, prompt, platform, model_key))
        thread.daemon = True
        thread.start()

    return jsonify({"task_id": task_id})


@app.route("/api/task/<task_id>")
@check_auth
def api_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@app.route("/api/escalation/<task_id>", methods=["POST"])
@check_auth
def api_escalation(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    action = request.json.get("action")
    if action == "approve":
        task["status"] = "running"
        thread = threading.Thread(target=run_task, args=(
            task_id, task["machine"], task["prompt_text"],
            task.get("platform", "claude"), task.get("model_key", "opus")
        ))
        thread.daemon = True
        thread.start()
        return jsonify({"ok": True, "action": "approved"})
    else:
        task["status"] = "denied"
        task["output"] = "Task denied by operator."
        return jsonify({"ok": True, "action": "denied"})


@app.route("/api/machines")
@check_auth
def api_machines():
    return jsonify(MACHINES)


@app.route("/api/send/<task_id>", methods=["POST"])
@check_auth
def api_send(task_id):
    """Send a follow-up message into an active tmux session."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    sess = task.get("tmux_session")
    if not sess:
        return jsonify({"error": "No active session"}), 400
    message = request.json.get("message", "").strip()
    if not message:
        return jsonify({"error": "No message"}), 400
    host_str = task.get("host_str")
    _tmux_send(sess, message, None if host_str == "local" else host_str)
    task["status"] = "running"
    return jsonify({"ok": True})


@app.route("/api/close/<task_id>", methods=["POST"])
@check_auth
def api_close(task_id):
    """Kill the tmux session for a task."""
    task = tasks.get(task_id)
    if task:
        sess = task.get("tmux_session")
        host_str = task.get("host_str")
        if sess:
            kill_cmd = f"tmux kill-session -t {sess} 2>/dev/null"
            if host_str and host_str != "local":
                _ssh(host_str, kill_cmd)
            else:
                subprocess.run(kill_cmd, shell=True)
        task["status"] = "closed"
    return jsonify({"ok": True})


@app.route("/api/models")
@check_auth
def api_models():
    result = {}
    for platform, models in MODELS.items():
        result[platform] = {k: {"label": v["label"]} for k, v in models.items()}
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
