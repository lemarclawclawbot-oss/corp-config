#!/bin/bash
# Run this on Lenovo (lem-ai) or Chromebook to route model-switch to ZBook Ollama
# ZBook Tailscale IP: 100.123.233.45

ZBOOK_OLLAMA="http://100.123.233.45:11434/v1"

# Create/update model-switch on remote machine
mkdir -p ~/.local/bin

cat > ~/.local/bin/model-switch << 'SCRIPT'
#!/bin/bash
SETTINGS_FILE="$HOME/.claude/settings.json"
ZBOOK="http://100.123.233.45:11434/v1"

show_models() {
    echo "Models routed through ZBook (100.123.233.45):"
    echo "  glm4    - GLM4 9B on ZBook GPU"
    echo "  qwen    - Qwen2.5-Coder 7B on ZBook GPU"
    echo "  hermes  - Hermes3 on ZBook GPU"
    echo "  opus    - Claude Opus 4.6 (Anthropic API)"
    echo "  sonnet  - Claude Sonnet 4.6 (Anthropic API)"
}

[ -z "$1" ] && { show_models; exit 0; }

switch() {
    python3 - "$1" "$2" "$3" <<'PYEOF'
import json, sys, os
model, url, key = sys.argv[1], sys.argv[2], sys.argv[3]
f = os.path.expanduser('~/.claude/settings.json')
cfg = {}
try:
    cfg = json.load(open(f))
except: pass
cfg['model'] = model
if url:
    cfg['env'] = {'ANTHROPIC_BASE_URL': url, 'ANTHROPIC_API_KEY': key}
else:
    cfg.pop('env', None)
json.dump(cfg, open(f,'w'), indent=2)
print(f"Switched to {model}. Restart claude.")
PYEOF
}

case "$1" in
    glm4)   switch "glm4:latest"           "$ZBOOK" "ollama" ;;
    qwen)   switch "qwen2.5-coder:7b"     "$ZBOOK" "ollama" ;;
    hermes) switch "hermes3:latest"        "$ZBOOK" "ollama" ;;
    opus)   switch "claude-opus-4-6"       "" "" ;;
    sonnet) switch "claude-sonnet-4-6"     "" "" ;;
    *) echo "Unknown: $1"; show_models; exit 1 ;;
esac
SCRIPT

chmod +x ~/.local/bin/model-switch
echo "PATH check:"
echo $PATH | tr ':' '\n' | grep local

# Add to PATH if needed
if ! echo "$PATH" | grep -q ".local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    echo "Added ~/.local/bin to PATH in .bashrc"
fi

echo ""
echo "Done. Test with: curl http://100.123.233.45:11434/api/tags"
echo "Then: model-switch glm4 && claude"
