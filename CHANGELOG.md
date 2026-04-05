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
