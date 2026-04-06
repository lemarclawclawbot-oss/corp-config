#!/usr/bin/env python3
"""
Property Management Dashboard — Track tenants, units, rent, maintenance, leases.
Port 5003. Data stored in JSON (upgrade to SQLite later if needed).
"""

import json
import uuid
from datetime import datetime, date
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
UNITS_FILE = DATA_DIR / "units.json"
TENANTS_FILE = DATA_DIR / "tenants.json"
MAINTENANCE_FILE = DATA_DIR / "maintenance.json"
PAYMENTS_FILE = DATA_DIR / "payments.json"


# --- Data Layer ---

def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return []


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def get_units():
    return load_json(UNITS_FILE)


def get_tenants():
    return load_json(TENANTS_FILE)


def get_maintenance():
    return load_json(MAINTENANCE_FILE)


def get_payments():
    return load_json(PAYMENTS_FILE)


# --- Dashboard HTML ---

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Property Management — Corp</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace; }
        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
        h1 { color: #00ff88; text-align: center; margin-bottom: 5px; }
        .subtitle { color: #666; text-align: center; margin-bottom: 25px; font-size: 0.85em; }

        .nav { display: flex; gap: 8px; margin-bottom: 20px; justify-content: center; flex-wrap: wrap; }
        .nav a { color: #00aaff; text-decoration: none; padding: 8px 16px; border: 1px solid #333;
                 border-radius: 4px; font-size: 0.85em; }
        .nav a:hover { border-color: #00aaff; }

        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .stat-card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; text-align: center; }
        .stat-card .number { font-size: 2.5em; font-weight: bold; color: #00ff88; }
        .stat-card .label { color: #888; font-size: 0.85em; margin-top: 5px; }
        .stat-card.warning .number { color: #ffaa00; }
        .stat-card.danger .number { color: #ff4444; }

        .section { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .section h2 { color: #00aaff; margin-bottom: 15px; font-size: 1.1em; display: flex; justify-content: space-between; align-items: center; }
        .section h2 button { background: #00ff88; color: #000; border: none; padding: 6px 14px;
                              border-radius: 4px; cursor: pointer; font-size: 0.8em; font-weight: bold; font-family: inherit; }

        table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
        th { text-align: left; color: #888; padding: 8px; border-bottom: 1px solid #333; font-size: 0.8em; text-transform: uppercase; }
        td { padding: 8px; border-bottom: 1px solid #1a1a2a; }
        tr:hover { background: #111; }

        .badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; }
        .badge.occupied { background: #00ff8833; color: #00ff88; }
        .badge.vacant { background: #ffaa0033; color: #ffaa00; }
        .badge.paid { background: #00ff8833; color: #00ff88; }
        .badge.late { background: #ff444433; color: #ff4444; }
        .badge.pending { background: #ffaa0033; color: #ffaa00; }
        .badge.open { background: #ff444433; color: #ff4444; }
        .badge.in_progress { background: #ffaa0033; color: #ffaa00; }
        .badge.resolved { background: #00ff8833; color: #00ff88; }
        .badge.active { background: #00ff8833; color: #00ff88; }
        .badge.expiring { background: #ffaa0033; color: #ffaa00; }
        .badge.expired { background: #ff444433; color: #ff4444; }
        .badge.emergency { background: #ff444433; color: #ff4444; }
        .badge.normal { background: #00aaff33; color: #00aaff; }
        .badge.low { background: #88888833; color: #888; }

        .actions button { background: #333; color: #aaa; border: 1px solid #444; padding: 4px 10px;
                          border-radius: 3px; cursor: pointer; font-size: 0.8em; font-family: inherit; margin-right: 4px; }
        .actions button:hover { background: #444; color: #fff; }
        .actions button.danger:hover { background: #ff4444; }

        /* Modal */
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                         background: rgba(0,0,0,0.8); z-index: 100; justify-content: center; align-items: center; }
        .modal-overlay.visible { display: flex; }
        .modal { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 25px;
                 width: 90%; max-width: 500px; max-height: 90vh; overflow-y: auto; }
        .modal h3 { color: #00aaff; margin-bottom: 15px; }
        .modal label { display: block; color: #aaa; margin-bottom: 5px; font-size: 0.85em; margin-top: 12px; }
        .modal input, .modal select, .modal textarea { width: 100%; padding: 8px; background: #111;
                 border: 1px solid #333; border-radius: 4px; color: #e0e0e0; font-family: inherit; }
        .modal textarea { min-height: 80px; resize: vertical; }
        .modal .btn-row { display: flex; gap: 10px; margin-top: 20px; }
        .modal .btn-row button { flex: 1; padding: 10px; border: none; border-radius: 4px; cursor: pointer;
                                  font-weight: bold; font-family: inherit; }
        .modal .btn-save { background: #00ff88; color: #000; }
        .modal .btn-cancel { background: #333; color: #aaa; }

        .footer { text-align: center; color: #444; margin-top: 20px; font-size: 0.8em; }
    </style>
</head>
<body>
<div class="container">
    <h1>PROPERTY MANAGEMENT</h1>
    <div class="subtitle">Corp Fleet — Unit & Tenant Dashboard</div>

    <div class="nav">
        <a href="http://localhost:5000" target="_blank">Mission Control</a>
        <a href="http://localhost:5001" target="_blank">Dispatch</a>
        <a href="http://localhost:5002" target="_blank">Tenant Comms</a>
    </div>

    <!-- Stats -->
    <div class="stats" id="stats"></div>

    <!-- Units -->
    <div class="section">
        <h2>Units <button onclick="openModal('unit')">+ Add Unit</button></h2>
        <table>
            <thead><tr><th>Unit</th><th>Address</th><th>Type</th><th>Rent</th><th>Status</th><th>Tenant</th><th>Actions</th></tr></thead>
            <tbody id="units-table"></tbody>
        </table>
    </div>

    <!-- Tenants -->
    <div class="section">
        <h2>Tenants <button onclick="openModal('tenant')">+ Add Tenant</button></h2>
        <table>
            <thead><tr><th>Name</th><th>Unit</th><th>Phone</th><th>Email</th><th>Lease End</th><th>Rent Status</th><th>Actions</th></tr></thead>
            <tbody id="tenants-table"></tbody>
        </table>
    </div>

    <!-- Maintenance -->
    <div class="section">
        <h2>Maintenance Requests <button onclick="openModal('maintenance')">+ New Request</button></h2>
        <table>
            <thead><tr><th>Date</th><th>Unit</th><th>Issue</th><th>Priority</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody id="maintenance-table"></tbody>
        </table>
    </div>

    <!-- Payments -->
    <div class="section">
        <h2>Recent Payments <button onclick="openModal('payment')">+ Record Payment</button></h2>
        <table>
            <thead><tr><th>Date</th><th>Tenant</th><th>Amount</th><th>Type</th><th>Note</th></tr></thead>
            <tbody id="payments-table"></tbody>
        </table>
    </div>

    <div class="footer">Corp Property Management v1.0</div>
</div>

<!-- Modals -->
<div class="modal-overlay" id="modal-overlay" onclick="if(event.target===this)closeModal()">
    <div class="modal" id="modal-content"></div>
</div>

<script>
const MODALS = {
    unit: {
        title: 'Add Unit',
        fields: [
            {name: 'name', label: 'Unit Name/Number', type: 'text', placeholder: 'e.g. Unit 4B'},
            {name: 'address', label: 'Address', type: 'text', placeholder: '123 Main St'},
            {name: 'type', label: 'Type', type: 'select', options: ['1BR', '2BR', '3BR', 'Studio', 'House', 'Other']},
            {name: 'rent', label: 'Monthly Rent ($)', type: 'number', placeholder: '1200'},
            {name: 'status', label: 'Status', type: 'select', options: ['vacant', 'occupied']},
            {name: 'notes', label: 'Notes', type: 'textarea', placeholder: 'Any notes...'},
        ]
    },
    tenant: {
        title: 'Add Tenant',
        fields: [
            {name: 'name', label: 'Full Name', type: 'text', placeholder: 'John Smith'},
            {name: 'unit', label: 'Unit', type: 'text', placeholder: 'Unit 4B'},
            {name: 'phone', label: 'Phone', type: 'text', placeholder: '555-0123'},
            {name: 'email', label: 'Email', type: 'text', placeholder: 'john@email.com'},
            {name: 'lease_start', label: 'Lease Start', type: 'date'},
            {name: 'lease_end', label: 'Lease End', type: 'date'},
            {name: 'rent_amount', label: 'Monthly Rent ($)', type: 'number', placeholder: '1200'},
            {name: 'rent_status', label: 'Rent Status', type: 'select', options: ['paid', 'pending', 'late']},
            {name: 'notes', label: 'Notes', type: 'textarea', placeholder: 'Any notes...'},
        ]
    },
    maintenance: {
        title: 'New Maintenance Request',
        fields: [
            {name: 'unit', label: 'Unit', type: 'text', placeholder: 'Unit 4B'},
            {name: 'issue', label: 'Issue', type: 'textarea', placeholder: 'Describe the issue...'},
            {name: 'priority', label: 'Priority', type: 'select', options: ['low', 'normal', 'emergency']},
            {name: 'status', label: 'Status', type: 'select', options: ['open', 'in_progress', 'resolved']},
            {name: 'notes', label: 'Notes', type: 'textarea', placeholder: 'Additional details...'},
        ]
    },
    payment: {
        title: 'Record Payment',
        fields: [
            {name: 'tenant_name', label: 'Tenant Name', type: 'text', placeholder: 'John Smith'},
            {name: 'amount', label: 'Amount ($)', type: 'number', placeholder: '1200'},
            {name: 'type', label: 'Type', type: 'select', options: ['rent', 'deposit', 'late_fee', 'other']},
            {name: 'note', label: 'Note', type: 'text', placeholder: 'April 2026 rent'},
        ]
    }
};

function openModal(type, editId) {
    const cfg = MODALS[type];
    let html = `<h3>${editId ? 'Edit' : cfg.title}</h3><form id="modal-form" data-type="${type}" data-edit="${editId||''}">`;
    cfg.fields.forEach(f => {
        html += `<label>${f.label}</label>`;
        if (f.type === 'select') {
            html += `<select name="${f.name}">${f.options.map(o => `<option value="${o}">${o}</option>`).join('')}</select>`;
        } else if (f.type === 'textarea') {
            html += `<textarea name="${f.name}" placeholder="${f.placeholder||''}"></textarea>`;
        } else {
            html += `<input type="${f.type}" name="${f.name}" placeholder="${f.placeholder||''}">`;
        }
    });
    html += `<div class="btn-row"><button type="button" class="btn-cancel" onclick="closeModal()">Cancel</button>
             <button type="submit" class="btn-save">Save</button></div></form>`;
    document.getElementById('modal-content').innerHTML = html;
    document.getElementById('modal-overlay').classList.add('visible');
    document.getElementById('modal-form').onsubmit = (e) => { e.preventDefault(); submitForm(type, editId); };
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('visible');
}

function submitForm(type, editId) {
    const form = document.getElementById('modal-form');
    const data = {};
    new FormData(form).forEach((v, k) => data[k] = v);
    const url = editId ? `/api/${type}/${editId}` : `/api/${type}`;
    const method = editId ? 'PUT' : 'POST';
    fetch(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)})
        .then(r => r.json()).then(() => { closeModal(); loadAll(); });
}

function deleteItem(type, id) {
    if (!confirm('Delete this item?')) return;
    fetch(`/api/${type}/${id}`, {method: 'DELETE'}).then(() => loadAll());
}

function updateStatus(type, id, status) {
    fetch(`/api/${type}/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'},
           body: JSON.stringify({status})}).then(() => loadAll());
}

function loadAll() {
    // Stats
    fetch('/api/stats').then(r => r.json()).then(s => {
        document.getElementById('stats').innerHTML = `
            <div class="stat-card"><div class="number">${s.total_units}</div><div class="label">Total Units</div></div>
            <div class="stat-card"><div class="number">${s.occupied}</div><div class="label">Occupied</div></div>
            <div class="stat-card ${s.vacant > 0 ? 'warning' : ''}"><div class="number">${s.vacant}</div><div class="label">Vacant</div></div>
            <div class="stat-card ${s.late_rent > 0 ? 'danger' : ''}"><div class="number">${s.late_rent}</div><div class="label">Late Rent</div></div>
            <div class="stat-card ${s.open_maintenance > 0 ? 'warning' : ''}"><div class="number">${s.open_maintenance}</div><div class="label">Open Maintenance</div></div>
            <div class="stat-card"><div class="number">$${s.monthly_revenue.toLocaleString()}</div><div class="label">Monthly Revenue</div></div>`;
    });

    // Units
    fetch('/api/units').then(r => r.json()).then(items => {
        document.getElementById('units-table').innerHTML = items.map(u => `<tr>
            <td><strong>${u.name}</strong></td><td>${u.address||''}</td><td>${u.type||''}</td>
            <td>$${u.rent||0}</td><td><span class="badge ${u.status}">${u.status}</span></td>
            <td>${u.tenant_name||'—'}</td>
            <td class="actions"><button onclick="openModal('unit','${u.id}')">Edit</button><button class="danger" onclick="deleteItem('unit','${u.id}')">Del</button></td>
        </tr>`).join('');
    });

    // Tenants
    fetch('/api/tenants').then(r => r.json()).then(items => {
        document.getElementById('tenants-table').innerHTML = items.map(t => {
            let leaseClass = 'active';
            if (t.lease_end) {
                const end = new Date(t.lease_end);
                const now = new Date();
                const days = (end - now) / 86400000;
                if (days < 0) leaseClass = 'expired';
                else if (days < 60) leaseClass = 'expiring';
            }
            return `<tr>
                <td><strong>${t.name}</strong></td><td>${t.unit||''}</td><td>${t.phone||''}</td>
                <td>${t.email||''}</td>
                <td><span class="badge ${leaseClass}">${t.lease_end||'—'}</span></td>
                <td><span class="badge ${t.rent_status||'pending'}">${t.rent_status||'pending'}</span></td>
                <td class="actions"><button onclick="openModal('tenant','${t.id}')">Edit</button><button class="danger" onclick="deleteItem('tenant','${t.id}')">Del</button></td>
            </tr>`;
        }).join('');
    });

    // Maintenance
    fetch('/api/maintenance').then(r => r.json()).then(items => {
        document.getElementById('maintenance-table').innerHTML = items.map(m => `<tr>
            <td>${(m.created||'').substring(0,10)}</td><td>${m.unit||''}</td>
            <td>${m.issue||''}</td>
            <td><span class="badge ${m.priority||'normal'}">${m.priority||'normal'}</span></td>
            <td><span class="badge ${m.status}">${m.status}</span></td>
            <td class="actions">
                ${m.status==='open'?`<button onclick="updateStatus('maintenance','${m.id}','in_progress')">Start</button>`:''}
                ${m.status==='in_progress'?`<button onclick="updateStatus('maintenance','${m.id}','resolved')">Resolve</button>`:''}
                <button class="danger" onclick="deleteItem('maintenance','${m.id}')">Del</button>
            </td>
        </tr>`).join('');
    });

    // Payments
    fetch('/api/payments').then(r => r.json()).then(items => {
        document.getElementById('payments-table').innerHTML = items.slice(0, 20).map(p => `<tr>
            <td>${(p.created||'').substring(0,10)}</td><td>${p.tenant_name||''}</td>
            <td>$${p.amount||0}</td><td>${p.type||''}</td><td>${p.note||''}</td>
        </tr>`).join('');
    });
}

loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>
"""


# --- API Routes ---

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/stats")
def api_stats():
    units = get_units()
    tenants = get_tenants()
    maintenance = get_maintenance()
    occupied = sum(1 for u in units if u.get("status") == "occupied")
    vacant = sum(1 for u in units if u.get("status") == "vacant")
    late_rent = sum(1 for t in tenants if t.get("rent_status") == "late")
    open_maint = sum(1 for m in maintenance if m.get("status") in ("open", "in_progress"))
    revenue = sum(float(t.get("rent_amount", 0)) for t in tenants if t.get("rent_status") == "paid")
    return jsonify({
        "total_units": len(units),
        "occupied": occupied,
        "vacant": vacant,
        "late_rent": late_rent,
        "open_maintenance": open_maint,
        "monthly_revenue": revenue,
    })


# --- CRUD for each entity ---

def crud_routes(entity_name, file_path):
    """Generate standard CRUD routes for an entity."""

    def list_items():
        return jsonify(load_json(file_path))

    def create_item():
        items = load_json(file_path)
        data = request.json
        data["id"] = str(uuid.uuid4())[:8]
        data["created"] = datetime.now().isoformat()
        items.append(data)
        save_json(file_path, items)
        # Link tenant to unit if applicable
        if entity_name == "tenant" and data.get("unit"):
            units = get_units()
            for u in units:
                if u["name"] == data["unit"]:
                    u["status"] = "occupied"
                    u["tenant_name"] = data.get("name", "")
                    save_json(UNITS_FILE, units)
                    break
        return jsonify({"ok": True, "id": data["id"]})

    def update_item(item_id):
        items = load_json(file_path)
        data = request.json
        for item in items:
            if item["id"] == item_id:
                item.update(data)
                break
        save_json(file_path, items)
        return jsonify({"ok": True})

    def delete_item(item_id):
        items = load_json(file_path)
        items = [i for i in items if i["id"] != item_id]
        save_json(file_path, items)
        return jsonify({"ok": True})

    app.add_url_rule(f"/api/{entity_name}s", f"list_{entity_name}", list_items)
    app.add_url_rule(f"/api/{entity_name}", f"create_{entity_name}", create_item, methods=["POST"])
    app.add_url_rule(f"/api/{entity_name}/<item_id>", f"update_{entity_name}", update_item, methods=["PUT"])
    app.add_url_rule(f"/api/{entity_name}/<item_id>", f"delete_{entity_name}", delete_item, methods=["DELETE"])


crud_routes("unit", UNITS_FILE)
crud_routes("tenant", TENANTS_FILE)
crud_routes("maintenance", MAINTENANCE_FILE)
crud_routes("payment", PAYMENTS_FILE)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
