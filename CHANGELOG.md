# Corp Fleet Config — Changelog

## 2026-04-04 — AI Toolkit Setup (ZBook)

### What Lemar Requested
- Install CrewAI for multi-agent orchestration
- Install Zhipu AI GLM (both local GLM4 and cloud GLM 5.1)
- Install Qwen2.5-Coder for free local coding/debugging
- Create a simple way to switch between models using the Claude Code interface (not separate tools)
- Increase screen timeout and lock delay on ZBook
- Set up ZBook as Ollama proxy so Chromebook can use local models when Claude Code hits session limits

### What Was Done to Complete It
1. **Installed CrewAI 1.13.0** — `pip install crewai`
2. **Installed ZhipuAI SDK 2.1.5** — for GLM 5.1 cloud API (Z.AI token-based)
3. **Pulled local Ollama models** — `glm4:latest`, `qwen2.5-coder:7b` (free, no account needed)
4. **Created `model-switch` script** — one command to swap Claude Code's backend model
5. **Installed Aider, then removed it** — redundant since `model-switch` keeps everything inside Claude Code's interface
6. **Screen timeout** — set to 30 min idle, 30 min lock delay via gsettings
7. **ZBook Ollama proxy** — available at `http://192.168.1.142:11434/v1`

### Status
- [x] CrewAI installed
- [x] GLM4 local — working
- [x] GLM 5.1 cloud — configured (Z.AI key set)
- [x] Qwen2.5-Coder local — working
- [x] model-switch script — working
- [x] Screen timeout increased
- [x] Aider removed (not needed)
- [x] Chromebook proxy config — documented in zbook/CONFIG.md
- [x] gh CLI + GitHub repo — pushed to lemarclawclawbot-oss/corp-config
- [x] Auto-sync cron — corp-sync.sh pulls repo every 30 min

---

## Instructions for Other Machines (Lenovo, Chromebook)

### ALL MACHINES: Install model-switch
1. Copy `model-switch` to `~/.local/bin/model-switch`
2. Run `chmod +x ~/.local/bin/model-switch`
3. Usage: `model-switch <model>` then `claude`

### Available models
| Command              | Model          | Cost        |
|----------------------|----------------|-------------|
| model-switch opus    | Claude Opus    | Paid        |
| model-switch sonnet  | Claude Sonnet  | Paid        |
| model-switch haiku   | Claude Haiku   | Paid        |
| model-switch glm4    | GLM4 Local     | Free        |
| model-switch glm5    | GLM 5.1 Cloud  | Z.AI Tokens |
| model-switch qwen    | Qwen2.5-Coder  | Free        |
| model-switch hermes  | Hermes3        | Free        |

### Chromebook: Using ZBook as Ollama Proxy
When Claude Code hits session limits, switch to a free local model hosted on ZBook:
1. Make sure ZBook is on and Ollama is running
2. Edit your `model-switch` script: change `localhost:11434` to `192.168.1.142:11434`
3. Run `model-switch glm4` then `claude`
4. All inference runs on ZBook's GPU — Chromebook just sends requests

### Lenovo: Already Has model-switch
- Verify your `model-switch` matches this version
- Update Ollama models: `ollama pull glm4 && ollama pull qwen2.5-coder:7b`
- If using ZBook as proxy instead of local Ollama, point to `192.168.1.142:11434`

### ALL MACHINES: Set Up Auto-Sync
1. Clone this repo: `git clone https://github.com/lemarclawclawbot-oss/corp-config.git ~/corp-config`
2. Copy `corp-sync.sh` to `~/.local/bin/corp-sync.sh` and `chmod +x` it
3. Add to crontab (`crontab -e`):
   ```
   */30 * * * * /home/$USER/.local/bin/corp-sync.sh
   ```
4. This auto-pulls the repo every 30 minutes so you always have the latest config

### Update Your Memory Files
Each machine should update its `ai_toolkit.md` memory to reflect the model-switch system and available models. Remove any references to Aider — it has been replaced by model-switch.

---

## 2026-04-04 — Mission Control & Fleet Infrastructure (ZBook)

### What Lemar Requested
- Enable Wake-on-LAN so Lenovo and Chromebook can wake ZBook instantly
- Create a real-time mission-control dashboard all three machines can access
- Build observer scripts for fleet health monitoring
- Set up Telegram escalation alerts
- All machines must have identical access to progress.json, dashboard, and logs
- Conflict resolution across all prior instructions

### What Was Done to Complete It
1. **Created `progress.json`** — shared fleet state file with all machine roles, tasks, services
2. **Created `dashboard/app.py`** — Flask web dashboard at http://192.168.1.142:5000, auto-refreshes every 30s, shows all machines, tasks, services, escalation logs
3. **Created `observer.py`** — runs on all machines, auto-detects role, monitors fleet health, sends heartbeats, triggers WoL, restarts Ollama if down
4. **Created `setup-wol.sh`** — enables Wake-on-LAN via ethtool + systemd persistence
5. **Created `setup-services.sh`** — installs systemd services for observer + dashboard, auto-detects machine role

### Status
- [x] progress.json — created
- [x] Dashboard app — created
- [x] Observer script — created
- [x] WoL setup script — created
- [x] Service setup script — created
- [ ] PENDING: Run `sudo bash setup-wol.sh` on ZBook (needs BIOS WoL enabled too)
- [ ] PENDING: Run `sudo bash setup-services.sh` on all machines
- [ ] PENDING: Telegram bot token + chat ID (Lemar to provide)

### Conflicts Found & Resolved
1. **Aider vs model-switch** — Aider was installed then removed. model-switch replaces it entirely.
2. **GLM API vs local** — GLM4 runs free locally, GLM5.1 uses cloud API. Both are kept.
3. **Sync interval** — Lenovo should sync every 5 min (relay role), ZBook every 30 min (source of truth), Chromebook every 30 min.

---

## Instructions for ALL Machines — Mission Control Setup

### Step 1: Pull the repo
```bash
git clone https://github.com/lemarclawclawbot-oss/corp-config.git ~/corp-config
# or if already cloned:
cd ~/corp-config && git pull
```

### Step 2: Install services
```bash
cd ~/corp-config
sudo bash setup-services.sh
```
This auto-detects your machine role and starts the observer. ZBook also gets the dashboard.

### Step 3: Access the dashboard
From ANY machine's browser:
```
http://192.168.1.142:5000
```

### Step 4: ZBook only — Wake-on-LAN
```bash
sudo bash setup-wol.sh
```
Then enable WoL in BIOS: Reboot → F10 → Advanced → Built-in Device Options → Enable "Wake on LAN"

### Step 5: Lenovo only — WoL sender
```bash
sudo apt install wakeonlan
# To wake ZBook:
wakeonlan 38:ca:84:c7:56:2c
# Or the observer does it automatically when ZBook goes offline
```

### Step 6: Lenovo — tighten sync interval
```bash
crontab -e
# Change to 5 min:
*/5 * * * * /home/$USER/.local/bin/corp-sync.sh
```

### Step 7: Telegram (optional, all machines)
1. Create a bot via @BotFather on Telegram
2. Get the bot token and your chat ID
3. Edit `progress.json` → set `telegram.bot_token` and `telegram.chat_id`
4. Observer will auto-send alerts when ZBook goes offline
