#!/usr/bin/env python3
"""
CrewAI Mission Control — Launch and manage AI crews from the browser.
Port 5004. All crews run on local Ollama models (free).
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

from agents import CREW_REGISTRY, run_crew

app = Flask(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "crew_history.json"

jobs = {}


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str))


def run_job(job_id, crew_key, data, model):
    try:
        result = run_crew(crew_key, data, model)
        jobs[job_id]["result"] = result
        jobs[job_id]["status"] = "done"
        history = load_history()
        history.insert(0, {
            "id": job_id,
            "crew": crew_key,
            "crew_name": CREW_REGISTRY.get(crew_key, {}).get("name", crew_key),
            "model": model,
            "data": data,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        })
        if len(history) > 100:
            history = history[:100]
        save_history(history)
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["result"] = str(e)


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>CrewAI Missions — Corp</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace; }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        h1 { color: #00ff88; text-align: center; margin-bottom: 5px; }
        .subtitle { color: #666; text-align: center; margin-bottom: 25px; font-size: 0.85em; }

        .nav { display: flex; gap: 8px; margin-bottom: 25px; justify-content: center; flex-wrap: wrap; }
        .nav a { color: #00aaff; text-decoration: none; padding: 8px 16px; border: 1px solid #333;
                 border-radius: 4px; font-size: 0.85em; }
        .nav a:hover { border-color: #00aaff; }

        .crew-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .crew-card { background: #1a1a1a; border: 2px solid #333; border-radius: 8px; padding: 20px; cursor: pointer; transition: all 0.2s; }
        .crew-card:hover { border-color: #00aaff; transform: translateY(-2px); }
        .crew-card.selected { border-color: #00ff88; background: #1a2a1a; }
        .crew-card h3 { color: #00ff88; margin-bottom: 5px; font-size: 1em; }
        .crew-card p { color: #888; font-size: 0.8em; }
        .crew-card .agents { color: #00aaff; font-size: 0.75em; margin-top: 8px; }

        .launch-panel { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 25px; margin-bottom: 25px; display: none; }
        .launch-panel.visible { display: block; }
        .launch-panel h2 { color: #00aaff; margin-bottom: 15px; }

        label { display: block; color: #aaa; margin-bottom: 5px; font-size: 0.85em; margin-top: 12px; }
        input, textarea, select { width: 100%; padding: 10px; background: #111; border: 1px solid #333;
                                   border-radius: 4px; color: #e0e0e0; font-family: inherit; font-size: 0.9em; }
        textarea { min-height: 100px; resize: vertical; }
        select { cursor: pointer; }

        .model-row { display: flex; gap: 10px; align-items: center; margin-top: 15px; }
        .model-row label { margin: 0; white-space: nowrap; }
        .model-row select { flex: 1; }

        .btn { display: inline-block; padding: 12px 24px; background: #00ff88; color: #000; border: none;
               border-radius: 4px; cursor: pointer; font-weight: bold; font-family: inherit; margin-top: 20px; font-size: 1em; }
        .btn:hover { background: #00cc66; }
        .btn:disabled { background: #333; color: #666; cursor: not-allowed; }

        .result-box { background: #0a0a0a; border: 1px solid #333; border-radius: 4px; padding: 20px;
                      margin-top: 20px; white-space: pre-wrap; font-size: 0.85em; line-height: 1.6;
                      max-height: 600px; overflow-y: auto; display: none; }
        .result-box.visible { display: block; }
        .result-box .header { display: flex; justify-content: space-between; margin-bottom: 10px; }
        .result-box .header span { color: #00ff88; font-weight: bold; }
        .result-box .copy-btn { background: #333; color: #aaa; border: 1px solid #444; padding: 4px 12px;
                                 border-radius: 3px; cursor: pointer; font-size: 0.85em; }

        .spinner { display: none; margin-top: 15px; color: #ffaa00; font-size: 0.9em; }
        .spinner.visible { display: block; }
        .spinner::before { content: ""; display: inline-block; width: 14px; height: 14px;
                           border: 2px solid #ffaa00; border-top-color: transparent;
                           border-radius: 50%; animation: spin 0.8s linear infinite;
                           vertical-align: middle; margin-right: 8px; }
        @keyframes spin { to { transform: rotate(360deg); } }

        .history { margin-top: 20px; }
        .history h2 { color: #00aaff; margin-bottom: 15px; }
        .history-item { background: #111; border: 1px solid #222; border-radius: 4px; padding: 12px;
                        margin-bottom: 8px; cursor: pointer; }
        .history-item:hover { border-color: #00aaff; }
        .history-item .meta { color: #666; font-size: 0.8em; }
        .history-item .crew-name { color: #00ff88; font-weight: bold; }
        .history-expand { display: none; margin-top: 10px; white-space: pre-wrap; color: #aaa;
                          font-size: 0.85em; border-top: 1px solid #333; padding-top: 10px; max-height: 300px; overflow-y: auto; }

        .free-badge { display: inline-block; background: #00ff8833; color: #00ff88; padding: 2px 8px;
                       border-radius: 3px; font-size: 0.7em; margin-left: 8px; }
    </style>
</head>
<body>
<div class="container">
    <h1>CREWAI MISSIONS</h1>
    <div class="subtitle">Multi-Agent AI Crews — All Local, All Free <span class="free-badge">GPU-POWERED</span></div>

    <div class="nav">
        <a href="http://localhost:5000" target="_blank">Mission Control</a>
        <a href="http://localhost:5001" target="_blank">Dispatch</a>
        <a href="http://localhost:5002" target="_blank">Tenant Comms</a>
        <a href="http://localhost:5003" target="_blank">Properties</a>
    </div>

    <div class="crew-grid" id="crew-grid"></div>

    <div class="launch-panel" id="launch-panel">
        <h2 id="launch-title">Launch Crew</h2>
        <div id="launch-fields"></div>
        <div class="model-row">
            <label>Model:</label>
            <select id="model-select">
                <option value="hermes">Hermes3 (8B — best for general tasks)</option>
                <option value="glm4">GLM4 (9B — good reasoning)</option>
                <option value="qwen">Qwen2.5-Coder (7B — best for technical)</option>
            </select>
        </div>
        <button class="btn" id="launch-btn" onclick="launchCrew()">Launch Crew</button>
        <div class="spinner" id="spinner">Crew is working... (this may take 1-3 minutes per agent)</div>
        <div class="result-box" id="result-box">
            <div class="header"><span>Crew Result</span><button class="copy-btn" onclick="copyResult()">Copy</button></div>
            <div id="result-text"></div>
        </div>
    </div>

    <div class="history" id="history-section"></div>
</div>

<script>
let selectedCrew = null;
let crews = {};

function loadCrews() {
    fetch('/api/crews').then(r => r.json()).then(data => {
        crews = data;
        const grid = document.getElementById('crew-grid');
        grid.innerHTML = Object.entries(data).map(([key, c]) => `
            <div class="crew-card" id="card-${key}" onclick="selectCrew('${key}')">
                <h3>${c.name}</h3>
                <p>${c.description}</p>
            </div>
        `).join('');
    });
}

function selectCrew(key) {
    selectedCrew = key;
    const crew = crews[key];
    document.querySelectorAll('.crew-card').forEach(c => c.classList.remove('selected'));
    document.getElementById('card-' + key).classList.add('selected');

    document.getElementById('launch-title').textContent = 'Launch: ' + crew.name;
    const fieldsDiv = document.getElementById('launch-fields');
    fieldsDiv.innerHTML = crew.fields.map(f => {
        let input;
        if (f.type === 'select') {
            input = `<select name="${f.name}">${f.options.map(o => `<option value="${o}">${o}</option>`).join('')}</select>`;
        } else if (f.type === 'textarea') {
            input = `<textarea name="${f.name}" placeholder="${f.placeholder||''}" rows="4"></textarea>`;
        } else {
            input = `<input type="${f.type||'text'}" name="${f.name}" placeholder="${f.placeholder||''}">`;
        }
        return `<label>${f.label}</label>${input}`;
    }).join('');

    document.getElementById('launch-panel').classList.add('visible');
    document.getElementById('result-box').classList.remove('visible');
    document.getElementById('spinner').classList.remove('visible');
}

function launchCrew() {
    if (!selectedCrew) return;
    const data = {};
    document.getElementById('launch-fields').querySelectorAll('input, textarea, select').forEach(el => {
        data[el.name] = el.value;
    });
    const model = document.getElementById('model-select').value;

    document.getElementById('launch-btn').disabled = true;
    document.getElementById('spinner').classList.add('visible');
    document.getElementById('result-box').classList.remove('visible');

    fetch('/api/launch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({crew: selectedCrew, data: data, model: model})
    }).then(r => r.json()).then(d => pollJob(d.job_id));
}

function pollJob(jobId) {
    fetch('/api/job/' + jobId).then(r => r.json()).then(data => {
        if (data.status === 'done') {
            document.getElementById('spinner').classList.remove('visible');
            document.getElementById('launch-btn').disabled = false;
            document.getElementById('result-text').textContent = data.result;
            document.getElementById('result-box').classList.add('visible');
            loadHistory();
        } else if (data.status === 'error') {
            document.getElementById('spinner').classList.remove('visible');
            document.getElementById('launch-btn').disabled = false;
            document.getElementById('result-text').textContent = 'ERROR: ' + data.result;
            document.getElementById('result-box').classList.add('visible');
        } else {
            setTimeout(() => pollJob(jobId), 3000);
        }
    });
}

function copyResult() {
    navigator.clipboard.writeText(document.getElementById('result-text').textContent);
}

function loadHistory() {
    fetch('/api/history').then(r => r.json()).then(items => {
        const section = document.getElementById('history-section');
        if (!items.length) { section.innerHTML = ''; return; }
        let html = '<h2>Recent Missions</h2>';
        items.slice(0, 15).forEach(item => {
            const date = new Date(item.timestamp).toLocaleString();
            html += `<div class="history-item" onclick="this.querySelector('.history-expand').style.display=this.querySelector('.history-expand').style.display==='block'?'none':'block'">
                <span class="crew-name">${item.crew_name}</span>
                <span class="meta"> — ${item.model} — ${date}</span>
                <div class="history-expand">${(item.result||'').replace(/</g,'&lt;')}</div>
            </div>`;
        });
        section.innerHTML = html;
    });
}

loadCrews();
loadHistory();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/crews")
def api_crews():
    result = {}
    for key, entry in CREW_REGISTRY.items():
        result[key] = {
            "name": entry["name"],
            "description": entry["description"],
            "fields": entry["fields"],
        }
    return jsonify(result)


@app.route("/api/launch", methods=["POST"])
def api_launch():
    data = request.json
    crew_key = data.get("crew")
    crew_data = data.get("data", {})
    model = data.get("model", "hermes")

    if crew_key not in CREW_REGISTRY:
        return jsonify({"error": f"Unknown crew: {crew_key}"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "running", "result": None}
    thread = threading.Thread(target=run_job, args=(job_id, crew_key, crew_data, model), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


@app.route("/api/history")
def api_history():
    return jsonify(load_history())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=False)
