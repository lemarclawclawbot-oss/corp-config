#!/usr/bin/env python3
"""
Corp Fleet Dispatch — Natural language task dispatch to fleet machines.
Like Claude's Mac dispatch, but runs in a browser for any device.

You type a request in plain English, pick a machine, and it runs
`claude --print` on that machine via SSH. Results stream back.
Sudo/dangerous commands get flagged for approval.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

app = Flask(__name__)

CORP_DIR = Path(__file__).parent.parent
DISPATCH_LOG = CORP_DIR / "logs" / "dispatch.log"

# Machine registry — update IPs as needed
MACHINES = {
    "zbook": {
        "host": "localhost",
        "user": "lemai",
        "label": "ZBook (Heavy Lifter)",
        "color": "#00ff88",
        "ssh": False,  # local, no SSH needed
    },
    "lenovo": {
        "host": "",  # fill in Lenovo IP
        "user": "lemai",
        "label": "Lenovo (Router/Relay)",
        "color": "#ffaa00",
        "ssh": True,
    },
    "chromebook": {
        "host": "",  # fill in Chromebook IP
        "user": "lemai",
        "label": "Chromebook (Dashboard)",
        "color": "#aa88ff",
        "ssh": True,
    },
}

# Active tasks
tasks = {}

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
        .header .status { font-size: 0.8em; color: #666; }

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

        @media (max-width: 768px) {
            .sidebar { display: none; }
            .main { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>&#x2B21; CORP DISPATCH</h1>
        <div class="status">Fleet Command — Natural Language Task Dispatch</div>
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
                        &bull; "Show me what Ollama models are installed"<br>
                        &bull; "Update all packages"<br><br>
                        I'll translate your request into commands, run them, and show you the results.
                        If anything needs sudo, I'll ask you first.
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
            .then(response => response.json())
            .then(data => {
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
            .then(r => r.json())
            .then(data => {
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

    # Post to Discord
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
            # Remote via SSH
            cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                f"{m['user']}@{m['host']}",
                f"claude --print '{prompt}'"
            ]
        else:
            # Local
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


@app.route("/")
def index():
    return render_template_string(DISPATCH_HTML, machines=MACHINES)


@app.route("/api/dispatch", methods=["POST"])
def api_dispatch():
    data = request.json
    machine = data.get("machine", "zbook")
    prompt = data.get("prompt", "")

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    if machine not in MACHINES:
        return jsonify({"error": f"Unknown machine: {machine}"}), 400

    # Check for sudo/dangerous patterns — escalate
    dangerous = ["sudo ", "rm -rf", "mkfs", "dd if=", "chmod 777", "> /dev/", "shutdown", "reboot", "systemctl stop"]
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
def api_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@app.route("/api/escalation/<task_id>", methods=["POST"])
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
def api_machines():
    return jsonify(MACHINES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
