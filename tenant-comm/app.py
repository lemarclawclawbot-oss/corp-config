#!/usr/bin/env python3
"""
Tenant Communication App — Web UI for AI-powered tenant messaging.
Port 5002. Integrates with CrewAI + Hermes3 for message generation.
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

from crew import draft_message, handle_complaint, lease_reminder, maintenance_update

app = Flask(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "message_history.json"

# In-memory job queue for async crew runs
jobs = {}  # {job_id: {"status": "running"|"done"|"error", "result": str, "type": str, ...}}


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def add_to_history(entry):
    history = load_history()
    history.insert(0, entry)
    if len(history) > 200:
        history = history[:200]
    save_history(history)


def run_job(job_id, func, kwargs):
    try:
        result = func(**kwargs)
        jobs[job_id]["result"] = result
        jobs[job_id]["status"] = "done"
        add_to_history({
            "id": job_id,
            "type": jobs[job_id]["type"],
            "tenant": kwargs.get("tenant_name", "Unknown"),
            "subject": kwargs.get("subject", kwargs.get("reminder_type", kwargs.get("issue", ""))),
            "result": result,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["result"] = str(e)


APP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Tenant Comms — Corp</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace; }
        .container { max-width: 900px; margin: 0 auto; padding: 20px; }
        h1 { color: #00ff88; text-align: center; margin-bottom: 5px; }
        .subtitle { color: #666; text-align: center; margin-bottom: 30px; font-size: 0.85em; }

        .tabs { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; }
        .tab { padding: 10px 18px; background: #1a1a1a; border: 1px solid #333; border-radius: 6px 6px 0 0;
               cursor: pointer; color: #888; font-size: 0.9em; }
        .tab.active { background: #1a1a2a; border-color: #00aaff; color: #00aaff; }

        .panel { display: none; background: #1a1a1a; border: 1px solid #333; border-radius: 0 8px 8px 8px; padding: 25px; }
        .panel.active { display: block; }

        label { display: block; color: #aaa; margin-bottom: 5px; font-size: 0.85em; margin-top: 15px; }
        input, textarea, select { width: 100%; padding: 10px; background: #111; border: 1px solid #333;
                                   border-radius: 4px; color: #e0e0e0; font-family: inherit; font-size: 0.9em; }
        textarea { min-height: 100px; resize: vertical; }
        input:focus, textarea:focus, select:focus { outline: none; border-color: #00aaff; }

        .btn { display: inline-block; padding: 12px 24px; background: #00aaff; color: #000; border: none;
               border-radius: 4px; cursor: pointer; font-weight: bold; font-family: inherit; margin-top: 20px; }
        .btn:hover { background: #0088dd; }
        .btn:disabled { background: #333; color: #666; cursor: not-allowed; }

        .result-box { background: #0a0a0a; border: 1px solid #333; border-radius: 4px; padding: 15px;
                      margin-top: 20px; white-space: pre-wrap; font-size: 0.85em; line-height: 1.6;
                      max-height: 500px; overflow-y: auto; display: none; }
        .result-box.visible { display: block; }
        .result-box .label { color: #00ff88; font-weight: bold; margin-bottom: 10px; display: block; }

        .spinner { display: none; margin-top: 15px; color: #ffaa00; }
        .spinner.visible { display: block; }
        .spinner::before { content: ""; display: inline-block; width: 14px; height: 14px;
                           border: 2px solid #ffaa00; border-top-color: transparent;
                           border-radius: 50%; animation: spin 0.8s linear infinite;
                           vertical-align: middle; margin-right: 8px; }
        @keyframes spin { to { transform: rotate(360deg); } }

        .history { margin-top: 30px; }
        .history h2 { color: #00aaff; margin-bottom: 15px; }
        .history-item { background: #111; border: 1px solid #222; border-radius: 4px; padding: 12px;
                        margin-bottom: 8px; cursor: pointer; }
        .history-item:hover { border-color: #00aaff; }
        .history-item .meta { color: #666; font-size: 0.8em; }
        .history-item .tenant { color: #00ff88; }
        .history-item .type-badge { display: inline-block; padding: 2px 8px; border-radius: 3px;
                                     font-size: 0.75em; margin-left: 8px; }
        .type-badge.general { background: #00aaff33; color: #00aaff; }
        .type-badge.complaint { background: #ff444433; color: #ff4444; }
        .type-badge.lease { background: #ffaa0033; color: #ffaa00; }
        .type-badge.maintenance { background: #aa88ff33; color: #aa88ff; }

        .copy-btn { background: #333; color: #aaa; border: 1px solid #444; padding: 5px 12px;
                    border-radius: 3px; cursor: pointer; font-size: 0.8em; float: right; }
        .copy-btn:hover { background: #444; color: #fff; }
    </style>
</head>
<body>
<div class="container">
    <h1>TENANT COMMS</h1>
    <div class="subtitle">AI-Powered Property Management Communications</div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('general')">General Message</div>
        <div class="tab" onclick="switchTab('complaint')">Complaint</div>
        <div class="tab" onclick="switchTab('lease')">Lease Notice</div>
        <div class="tab" onclick="switchTab('maintenance')">Maintenance</div>
    </div>

    <!-- General Message -->
    <div class="panel active" id="panel-general">
        <label>Tenant Name</label>
        <input id="gen-tenant" placeholder="e.g. John Smith">
        <label>Subject</label>
        <input id="gen-subject" placeholder="e.g. Welcome to the property">
        <label>Context / Details</label>
        <textarea id="gen-context" placeholder="Any relevant details for the AI to use..."></textarea>
        <button class="btn" onclick="submitGeneral()">Generate Message</button>
        <div class="spinner" id="spin-general">Generating with Hermes3...</div>
        <div class="result-box" id="result-general"><span class="label">Generated Message</span><button class="copy-btn" onclick="copyResult('general')">Copy</button><div id="text-general"></div></div>
    </div>

    <!-- Complaint -->
    <div class="panel" id="panel-complaint">
        <label>Tenant Name</label>
        <input id="comp-tenant" placeholder="e.g. Jane Doe">
        <label>Complaint</label>
        <textarea id="comp-complaint" placeholder="Describe the tenant's complaint..."></textarea>
        <label>Property Info (optional)</label>
        <input id="comp-property" placeholder="e.g. Unit 4B, 123 Main St">
        <button class="btn" onclick="submitComplaint()">Handle Complaint</button>
        <div class="spinner" id="spin-complaint">Analyzing complaint...</div>
        <div class="result-box" id="result-complaint"><span class="label">Response + Action Plan</span><button class="copy-btn" onclick="copyResult('complaint')">Copy</button><div id="text-complaint"></div></div>
    </div>

    <!-- Lease Notice -->
    <div class="panel" id="panel-lease">
        <label>Tenant Name</label>
        <input id="lease-tenant" placeholder="e.g. Bob Wilson">
        <label>Notice Type</label>
        <select id="lease-type">
            <option value="rent reminder">Rent Reminder</option>
            <option value="late payment notice">Late Payment Notice</option>
            <option value="lease renewal">Lease Renewal</option>
            <option value="lease violation">Lease Violation</option>
            <option value="move-in instructions">Move-In Instructions</option>
            <option value="move-out instructions">Move-Out Instructions</option>
            <option value="rent increase notice">Rent Increase Notice</option>
        </select>
        <label>Details</label>
        <textarea id="lease-details" placeholder="Relevant details: amounts, dates, specifics..."></textarea>
        <button class="btn" onclick="submitLease()">Generate Notice</button>
        <div class="spinner" id="spin-lease">Drafting notice...</div>
        <div class="result-box" id="result-lease"><span class="label">Generated Notice</span><button class="copy-btn" onclick="copyResult('lease')">Copy</button><div id="text-lease"></div></div>
    </div>

    <!-- Maintenance -->
    <div class="panel" id="panel-maintenance">
        <label>Tenant Name</label>
        <input id="maint-tenant" placeholder="e.g. Alice Brown">
        <label>Issue</label>
        <input id="maint-issue" placeholder="e.g. Leaking kitchen faucet">
        <label>Status</label>
        <select id="maint-status">
            <option value="received">Received — Acknowledging</option>
            <option value="scheduled">Scheduled — Repair Date Set</option>
            <option value="in_progress">In Progress — Work Underway</option>
            <option value="completed">Completed — Follow Up</option>
            <option value="delayed">Delayed — Update Tenant</option>
        </select>
        <label>Details</label>
        <textarea id="maint-details" placeholder="Scheduled date, technician info, access needs..."></textarea>
        <button class="btn" onclick="submitMaintenance()">Send Update</button>
        <div class="spinner" id="spin-maintenance">Coordinating update...</div>
        <div class="result-box" id="result-maintenance"><span class="label">Maintenance Update</span><button class="copy-btn" onclick="copyResult('maintenance')">Copy</button><div id="text-maintenance"></div></div>
    </div>

    <div class="history" id="history-section"></div>
</div>

<script>
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('panel-' + name).classList.add('active');
}

function showSpinner(type) {
    document.getElementById('spin-' + type).classList.add('visible');
    document.getElementById('result-' + type).classList.remove('visible');
}

function showResult(type, text) {
    document.getElementById('spin-' + type).classList.remove('visible');
    document.getElementById('text-' + type).textContent = text;
    document.getElementById('result-' + type).classList.add('visible');
}

function copyResult(type) {
    const text = document.getElementById('text-' + type).textContent;
    navigator.clipboard.writeText(text);
}

function pollJob(jobId, type) {
    fetch('/api/job/' + jobId)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'done') {
                showResult(type, data.result);
                loadHistory();
            } else if (data.status === 'error') {
                showResult(type, 'ERROR: ' + data.result);
            } else {
                setTimeout(() => pollJob(jobId, type), 2000);
            }
        });
}

function submitGeneral() {
    showSpinner('general');
    fetch('/api/generate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: 'general',
            tenant_name: document.getElementById('gen-tenant').value,
            subject: document.getElementById('gen-subject').value,
            context: document.getElementById('gen-context').value
        })
    }).then(r => r.json()).then(d => pollJob(d.job_id, 'general'));
}

function submitComplaint() {
    showSpinner('complaint');
    fetch('/api/generate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: 'complaint',
            tenant_name: document.getElementById('comp-tenant').value,
            complaint: document.getElementById('comp-complaint').value,
            property_info: document.getElementById('comp-property').value
        })
    }).then(r => r.json()).then(d => pollJob(d.job_id, 'complaint'));
}

function submitLease() {
    showSpinner('lease');
    fetch('/api/generate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: 'lease',
            tenant_name: document.getElementById('lease-tenant').value,
            reminder_type: document.getElementById('lease-type').value,
            details: document.getElementById('lease-details').value
        })
    }).then(r => r.json()).then(d => pollJob(d.job_id, 'lease'));
}

function submitMaintenance() {
    showSpinner('maintenance');
    fetch('/api/generate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: 'maintenance',
            tenant_name: document.getElementById('maint-tenant').value,
            issue: document.getElementById('maint-issue').value,
            status: document.getElementById('maint-status').value,
            details: document.getElementById('maint-details').value
        })
    }).then(r => r.json()).then(d => pollJob(d.job_id, 'maintenance'));
}

function loadHistory() {
    fetch('/api/history').then(r => r.json()).then(items => {
        const section = document.getElementById('history-section');
        if (!items.length) { section.innerHTML = ''; return; }
        let html = '<h2>Recent Messages</h2>';
        items.slice(0, 20).forEach(item => {
            const date = new Date(item.timestamp).toLocaleString();
            html += `<div class="history-item" onclick="this.querySelector('.expand').style.display=this.querySelector('.expand').style.display==='block'?'none':'block'">
                <span class="tenant">${item.tenant}</span>
                <span class="type-badge ${item.type}">${item.type}</span>
                <span class="meta"> — ${item.subject} — ${date}</span>
                <div class="expand" style="display:none;margin-top:10px;white-space:pre-wrap;color:#aaa;font-size:0.85em;border-top:1px solid #333;padding-top:10px;">${item.result}</div>
            </div>`;
        });
        section.innerHTML = html;
    });
}

loadHistory();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(APP_HTML)


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.json
    job_id = str(uuid.uuid4())[:8]
    msg_type = data.get("type", "general")

    if msg_type == "general":
        func = draft_message
        kwargs = {
            "tenant_name": data.get("tenant_name", "Tenant"),
            "subject": data.get("subject", ""),
            "context": data.get("context", ""),
        }
    elif msg_type == "complaint":
        func = handle_complaint
        kwargs = {
            "tenant_name": data.get("tenant_name", "Tenant"),
            "complaint": data.get("complaint", ""),
            "property_info": data.get("property_info", ""),
        }
    elif msg_type == "lease":
        func = lease_reminder
        kwargs = {
            "tenant_name": data.get("tenant_name", "Tenant"),
            "reminder_type": data.get("reminder_type", "reminder"),
            "details": data.get("details", ""),
        }
    elif msg_type == "maintenance":
        func = maintenance_update
        kwargs = {
            "tenant_name": data.get("tenant_name", "Tenant"),
            "issue": data.get("issue", ""),
            "status": data.get("status", "received"),
            "details": data.get("details", ""),
        }
    else:
        return jsonify({"error": "Unknown type"}), 400

    jobs[job_id] = {"status": "running", "result": None, "type": msg_type}
    thread = threading.Thread(target=run_job, args=(job_id, func, kwargs), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


@app.route("/api/history")
def get_history():
    return jsonify(load_history())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
