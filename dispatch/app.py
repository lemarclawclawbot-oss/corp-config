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
        "user": "lemai",
        "label": "Lenovo (Router/Relay)",
        "color": "#ffaa00",
        "ssh": True,
    },
    "chromebook": {
        "host": "100.82.232.25",
        "user": "lemai",
        "label": "Chromebook (Dashboard)",
        "color": "#aa88ff",
        "ssh": True,
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
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif; height: 100vh; display: flex; flex-direction: column; }

        .header { background: #111; border-bottom: 1px solid #333; padding: 15px 20px; display: flex; align-items: center; gap: 15px; }
        .header h1 { color: #00ff88; font-size: 1.3em; font-family: 'Courier New', monospace; }
        .header .status { font-size: 0.8em; color: #666; flex: 1; }
        .header .logout { background: none; border: 1px solid #555; color: #888; padding: 6px 14px;
                          border-radius: 6px; cursor: pointer; font-size: 0.8em; }
        .header .logout:hover { border-color: #ff4444; color: #ff4444; }

        .main { flex: 1; display: flex; overflow: hidden; }

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

        .input-area { padding: 15px 20px; background: #111; border-top: 1px solid #333; }
        .input-row { display: flex; gap: 10px; align-items: flex-end; }
        .input-row textarea { flex: 1; background: #1a1a1a; border: 1px solid #333; border-radius: 8px; color: #e0e0e0; padding: 12px; font-size: 0.95em; font-family: inherit; resize: none; min-height: 50px; max-height: 150px; }
        .input-row textarea:focus { outline: none; border-color: #00ff88; }
        .input-row button { background: #00ff88; color: #000; border: none; border-radius: 8px; padding: 12px 24px; font-weight: bold; cursor: pointer; font-size: 0.95em; white-space: nowrap; }
        .input-row button:hover { background: #00cc66; }
        .input-row button:disabled { background: #333; color: #666; cursor: not-allowed; }
        .target-label { font-size: 0.8em; color: #888; margin-bottom: 5px; }

        .typing { color: #888; font-style: italic; padding: 5px 0; }

        /* Mobile: show machine selector as horizontal bar */
        @media (max-width: 768px) {
            .sidebar { width: 100%; flex-shrink: 0; height: auto; max-height: 120px; border-right: none;
                       border-bottom: 1px solid #333; display: flex; flex-wrap: wrap; gap: 6px;
                       padding: 10px; overflow-x: auto; }
            .sidebar h3 { display: none; }
            .sidebar .history-section { display: none; }
            .machine-btn { width: auto; flex: 1; min-width: 100px; padding: 8px; font-size: 0.8em; }
            .main { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>&#x2B21; CORP DISPATCH</h1>
        <div class="status">Fleet Command — Natural Language Task Dispatch</div>
        <button class="logout" onclick="if(confirm('Log out?')){document.cookie='dispatch_token=;max-age=0';location.href='/login'}">Logout</button>
    </div>

    <div class="main">
        <div class="sidebar">
            <h3>Machines</h3>
            {% for name, m in machines.items() %}
            <button class="machine-btn {% if name == 'zbook' %}selected{% endif %}"
                    style="--color: {{ m.color }}"
                    onclick="selectMachine('{{ name }}', this)">
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
                <div class="target-label">Dispatching to: <strong id="target-name">ZBOOK</strong></div>
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

        function selectMachine(name, btn) {
            selectedMachine = name;
            document.getElementById('target-name').textContent = name.toUpperCase();
            document.querySelectorAll('.machine-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
        }

        function addMessage(role, content, machine) {
            const div = document.createElement('div');
            div.className = `message ${role}`;
            const meta = role === 'user' ? `YOU → ${machine.toUpperCase()}` : `${machine.toUpperCase()} AGENT`;
            div.innerHTML = `<div class="meta">${meta}</div><div class="bubble">${content}</div>`;
            document.getElementById('messages').appendChild(div);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
            return div;
        }

        function dispatch() {
            const prompt = document.getElementById('prompt').value.trim();
            if (!prompt) return;

            document.getElementById('prompt').value = '';
            document.getElementById('send-btn').disabled = true;

            addMessage('user', prompt, selectedMachine);

            const agentDiv = addMessage('agent', '<div class="typing">Working...</div>', selectedMachine);
            const bubble = agentDiv.querySelector('.bubble');

            fetch('/api/dispatch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({machine: selectedMachine, prompt: prompt})
            })
            .then(response => {
                if (response.status === 401) { location.href = '/login'; return; }
                return response.json();
            })
            .then(data => {
                if (!data) return;
                if (data.task_id) {
                    pollTask(data.task_id, bubble, selectedMachine);
                } else {
                    bubble.innerHTML = `<span style="color:#ff4444">Error: ${data.error}</span>`;
                    document.getElementById('send-btn').disabled = false;
                }
            })
            .catch(err => {
                bubble.innerHTML = `<span style="color:#ff4444">Connection error: ${err}</span>`;
                document.getElementById('send-btn').disabled = false;
            });
        }

        function pollTask(taskId, bubble, machine) {
            fetch(`/api/task/${taskId}`)
            .then(r => { if (r.status === 401) { location.href = '/login'; return; } return r.json(); })
            .then(data => {
                if (!data) return;
                if (data.status === 'running') {
                    let output = data.output || 'Working...';
                    bubble.innerHTML = `<div class="typing">Running...</div><pre><code>${escapeHtml(output)}</code></pre>`;
                    setTimeout(() => pollTask(taskId, bubble, machine), 1500);
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
                    bubble.innerHTML = `<pre><code>${escapeHtml(output)}</code></pre>
                        <div style="margin-top:8px;font-size:0.8em;color:${statusColor}">
                        ${data.status === 'completed' ? '&#x2705;' : '&#x274C;'} ${data.status}
                        </div>`;
                    document.getElementById('send-btn').disabled = false;
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
                    document.getElementById('send-btn').disabled = false;
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


def run_task(task_id, machine, prompt):
    """Run a claude command on target machine."""
    task = tasks[task_id]

    try:
        m = MACHINES[machine]

        if m.get("ssh") and m["host"]:
            cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                f"{m['user']}@{m['host']}",
                f"claude --print '{prompt}'"
            ]
        else:
            cmd = ["claude", "--print", prompt]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output = []
        for line in proc.stdout:
            output.append(line)
            task["output"] = "".join(output)

        proc.wait(timeout=300)

        task["status"] = "completed" if proc.returncode == 0 else "failed"
        task["output"] = "".join(output)
        log_dispatch(machine, prompt, task["status"])

    except subprocess.TimeoutExpired:
        proc.kill()
        task["status"] = "failed"
        task["output"] = task.get("output", "") + "\n\n[TIMEOUT after 5 minutes]"
        log_dispatch(machine, prompt, "timeout")
    except Exception as e:
        task["status"] = "failed"
        task["output"] = str(e)
        log_dispatch(machine, prompt, f"error: {e}")


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
    return render_template_string(DISPATCH_HTML, machines=MACHINES)


@app.route("/api/dispatch", methods=["POST"])
@check_auth
def api_dispatch():
    data = request.json
    machine = data.get("machine", "zbook")
    prompt = data.get("prompt", "")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    if machine not in MACHINES:
        return jsonify({"error": f"Unknown machine: {machine}"}), 400

    dangerous = ["sudo ", "rm -rf", "mkfs", "dd if=", "chmod 777", "> /dev/", "shutdown", "reboot",
                 "systemctl stop", "systemctl disable", "kill -9", "pkill", "format"]
    needs_escalation = any(d in prompt.lower() for d in dangerous)

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {
        "id": task_id,
        "machine": machine,
        "prompt_text": prompt,
        "status": "escalation" if needs_escalation else "running",
        "message": f"This request may need elevated permissions: '{prompt}'" if needs_escalation else "",
        "output": "",
        "created": datetime.now().isoformat(),
    }

    if not needs_escalation:
        thread = threading.Thread(target=run_task, args=(task_id, machine, prompt))
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
        thread = threading.Thread(target=run_task, args=(task_id, task["machine"], task["prompt_text"]))
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
