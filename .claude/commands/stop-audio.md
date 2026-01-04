---
description: Stop voice input mode for Claude Code
allowed-tools: Bash(python:*), Bash(talk-to-claude:*), Bash(kill:*), Bash(pgrep:*), Bash(cat:*)
---

# Stop Voice Input

Stop the voice-to-text daemon.

## Stop Daemon

```bash
cd $HOME/Documents/OSS/talk-to-claude && source .venv/bin/activate && python -m talk_to_claude.main stop
```

## Alternative: Force Stop

If the daemon doesn't respond to normal stop:

```bash
pkill -f "talk_to_claude.main"
```

## Cleanup

The daemon automatically removes its PID file when stopped. If you need to manually clean up:

```bash
rm -f ~/.talk-to-claude/daemon.pid
```
