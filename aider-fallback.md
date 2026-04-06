# Aider Fallback — When Claude Code Session Expires

## Quick Start
```bash
# In project directory
aider --model claude-opus-4-6

# Or use local Ollama model (free, no session limits)
aider --model ollama/qwen2.5-coder:7b --openai-api-base http://localhost:11434/v1
```

## Key Aider Commands (in chat)
- `/add <file>` — add file to context
- `/run <cmd>` — run shell command
- `/git diff` — see changes
- `/help` — all commands

## Why Aider is the Backup
- Same Anthropic API key, no separate login
- Works in terminal like Claude Code
- Handles git commits automatically
- When claude session limit hits: `Ctrl+C` → `aider`

## Using Local Models (No API Cost)
```bash
aider --model ollama/glm4:latest --openai-api-base http://localhost:11434/v1
```
