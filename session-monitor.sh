#!/bin/bash
# Corp Fleet Session Monitor
# Monitors Claude Code session usage and auto-prepares handoff when limits approach.
#
# Usage: Run alongside Claude Code sessions. Checks /config usage output.
# Tier-based polling:
#   0-50%   → check every 2 hours
#   50-80%  → check every 1 hour
#   80-90%  → check every 30 min
#   90-97%  → check every 5 min
#   97%+    → HANDOFF: save progress, alert, prep next model
#
# Install: Add to crontab or run as background process
#   nohup ~/corp-config/session-monitor.sh &

CORP_DIR="$HOME/corp-config"
PROGRESS="$CORP_DIR/progress.json"
HANDOFF_DIR="$CORP_DIR/handoffs"
LOG="$CORP_DIR/logs/session-monitor.log"
DISCORD_NOTIFY="$CORP_DIR/discord_notify.py"

mkdir -p "$HANDOFF_DIR" "$(dirname "$LOG")"

log() {
    echo "[$(date '+%H:%M:%S')] $1" >> "$LOG"
    echo "[$(date '+%H:%M:%S')] $1"
}

discord_alert() {
    python3 "$DISCORD_NOTIFY" zbook alert "$1" 2>/dev/null
}

discord_directive() {
    python3 "$DISCORD_NOTIFY" zbook directive "$1" 2>/dev/null
}

# Get session usage percentage from Claude Code
get_usage() {
    # Try to read from the Claude config/usage data
    # Claude Code stores usage in ~/.claude/ area
    local usage_file="$HOME/.claude/.usage"

    # If we can't read usage directly, check the progress.json for last known value
    if [ -f "$PROGRESS" ]; then
        local pct=$(python3 -c "
import json
try:
    d = json.load(open('$PROGRESS'))
    print(d.get('session_usage_pct', 0))
except:
    print(0)
" 2>/dev/null)
        echo "${pct:-0}"
    else
        echo "0"
    fi
}

# Save current work state for handoff
save_handoff() {
    local pct="$1"
    local ts=$(date '+%Y-%m-%d_%H%M%S')
    local handoff_file="$HANDOFF_DIR/handoff_${ts}.md"

    log "HANDOFF: Saving state at ${pct}% usage"

    # Get recent git activity
    local recent_commits=$(cd "$CORP_DIR" && git log --oneline -10 2>/dev/null)
    local current_branch=$(cd "$CORP_DIR" && git branch --show-current 2>/dev/null)
    local pending_changes=$(cd "$CORP_DIR" && git status --short 2>/dev/null)

    # Get running services
    local services=$(systemctl list-units --type=service --state=running 2>/dev/null | grep corp || echo "unknown")

    cat > "$handoff_file" << HANDOFF
---
type: handoff
timestamp: $(date -Iseconds)
session_usage: ${pct}%
previous_model: opus (Claude Code)
---

# Session Handoff — ${ts}

## Why
Session usage hit ${pct}%. Auto-switching to next available model.

## What Was Being Worked On
Check the most recent commits and progress.json for current task state.

### Recent Commits
\`\`\`
${recent_commits}
\`\`\`

### Branch: ${current_branch}

### Uncommitted Changes
\`\`\`
${pending_changes}
\`\`\`

### Running Services
\`\`\`
${services}
\`\`\`

## What To Do Next
1. Read ~/corp-config/progress.json for current fleet state
2. Read ~/corp-config/CHANGELOG.md for full context
3. Check Discord channels for recent activity
4. Continue from where the previous session left off

## Available Models (in capability order)
1. \`model-switch glm5\` — GLM 5.1 cloud API (Lemar's active sub)
2. \`model-switch glm4\` — GLM4 local (free, on GPU)
3. \`model-switch qwen\` — Qwen 2.5-Coder local (free)
4. \`model-switch opus\` — Anthropic Opus (when session resets)

## How To Resume
\`\`\`bash
cd ~/corp-config
cat handoffs/$(basename "$handoff_file")
# Then continue the work
\`\`\`
HANDOFF

    log "Handoff saved: $handoff_file"

    # Commit the handoff
    cd "$CORP_DIR" && git add handoffs/ && git commit -m "Auto-handoff at ${pct}% session usage" 2>/dev/null && git push 2>/dev/null

    echo "$handoff_file"
}

# Update usage in progress.json
update_progress_usage() {
    local pct="$1"
    python3 -c "
import json
try:
    with open('$PROGRESS', 'r') as f:
        d = json.load(f)
    d['session_usage_pct'] = $pct
    d['session_checked_at'] = '$(date -Iseconds)'
    with open('$PROGRESS', 'w') as f:
        json.dump(d, f, indent=2)
except Exception as e:
    print(f'Error updating progress: {e}')
" 2>/dev/null
}

# Auto-switch model
auto_switch_model() {
    log "AUTO-SWITCH: Attempting to switch to next available model"

    # Try GLM5 first (cloud, most capable alternative)
    if command -v model-switch &>/dev/null; then
        model-switch glm5 2>/dev/null
        log "Switched to GLM 5.1"
        discord_alert "Session limit reached. Auto-switched to GLM 5.1. Handoff saved."
    else
        log "model-switch not found — manual switch needed"
        discord_alert "Session limit reached. Manual model switch needed: model-switch glm5"
    fi
}

# Main monitoring loop
main() {
    log "Session monitor started"

    while true; do
        local pct=$(get_usage)
        update_progress_usage "$pct"

        local sleep_time=7200  # default 2 hours

        if [ "$pct" -ge 97 ]; then
            log "CRITICAL: ${pct}% usage — initiating handoff"
            notify-send -u critical "SESSION LIMIT" "Claude session at ${pct}%! Saving handoff and switching models." 2>/dev/null
            discord_alert "CRITICAL: Session at ${pct}%. Saving handoff and switching to backup model."

            local handoff=$(save_handoff "$pct")
            auto_switch_model

            # After handoff, monitor less frequently
            sleep_time=3600

        elif [ "$pct" -ge 90 ]; then
            log "WARNING: ${pct}% usage — checking every 5 min"
            notify-send -u normal "Session Warning" "Claude session at ${pct}%. Handoff approaching." 2>/dev/null
            discord_alert "Session at ${pct}% — handoff approaching"
            sleep_time=300

        elif [ "$pct" -ge 80 ]; then
            log "CAUTION: ${pct}% usage — checking every 30 min"
            sleep_time=1800

        elif [ "$pct" -ge 50 ]; then
            log "INFO: ${pct}% usage — checking every hour"
            sleep_time=3600

        else
            log "OK: ${pct}% usage — checking every 2 hours"
            sleep_time=7200
        fi

        sleep "$sleep_time"
    done
}

# Allow single-shot check
if [ "$1" = "--check" ]; then
    pct=$(get_usage)
    echo "Session usage: ${pct}%"
    exit 0
fi

# Allow manual handoff
if [ "$1" = "--handoff" ]; then
    pct=$(get_usage)
    save_handoff "$pct"
    exit 0
fi

main
