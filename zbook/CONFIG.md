# ZBook Claude Code Configuration

## How model-switch works

The `model-switch` script modifies `~/.claude/settings.json` to point Claude Code at different model providers. For local models, it sets `ANTHROPIC_BASE_URL` to Ollama's OpenAI-compatible endpoint. For cloud models, it uses the native Anthropic API or Zhipu AI's API.

## Current settings.json (after model-switch glm4)

```json
{
  "model": "glm4:latest",
  "voiceEnabled": true,
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:11434/v1",
    "ANTHROPIC_API_KEY": "ollama"
  }
}
```

## For Anthropic Claude (default — model-switch opus)

```json
{
  "model": "opus",
  "voiceEnabled": true,
  "env": {}
}
```

## Key concept

- `ANTHROPIC_BASE_URL` tells Claude Code where to send API requests
- For local Ollama: `http://localhost:11434/v1`
- For remote ZBook Ollama (from Chromebook): `http://192.168.1.142:11434/v1`
- For Zhipu GLM5 cloud: `https://open.bigmodel.cn/api/paas/v4`
- For native Claude: remove `ANTHROPIC_BASE_URL` entirely (uses default Anthropic endpoint)
- `ANTHROPIC_API_KEY` is `ollama` for local models (Ollama doesn't check it but Claude Code requires one)

## Chromebook-specific: using ZBook as proxy

Since Chromebook can't run Ollama locally, point at ZBook's IP:

```json
{
  "model": "glm4:latest",
  "env": {
    "ANTHROPIC_BASE_URL": "http://192.168.1.142:11434/v1",
    "ANTHROPIC_API_KEY": "ollama"
  }
}
```

## model-switch script

Copy `/home/lemai/corp-config/model-switch` to `~/.local/bin/model-switch` and `chmod +x` it. For Chromebook, change `localhost` references to `192.168.1.142` (ZBook IP).

## Available models on ZBook Ollama

| Model | Ollama Name | Size |
|-------|-------------|------|
| GLM4 | glm4:latest | 5.5 GB |
| Qwen2.5-Coder 7B | qwen2.5-coder:7b | 4.7 GB |
| Hermes3 | hermes3:latest | 4.7 GB |
