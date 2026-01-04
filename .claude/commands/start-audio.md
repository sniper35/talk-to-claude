---
description: Start voice input mode for Claude Code
allowed-tools: Bash(python:*), Bash(pip:*), Bash(talk-to-claude:*), Bash(pgrep:*), Bash(cat:*)
---

# Start Voice Input

Start the voice-to-text daemon for hands-free Claude Code interaction.

## Prerequisites

Make sure you have:

1. **API Keys configured** in `~/.claude_voice_api.json`:
   ```json
   {
     "deepgram": "your-deepgram-api-key",
     "elevenlabs": "your-elevenlabs-api-key",
     "openai": "your-openai-api-key"
   }
   ```
   (Only need the key for your selected service in config.yaml)

2. Enabled iTerm2 Python API: iTerm2 Preferences > General > Magic > Enable Python API

3. Granted microphone permissions to Terminal/iTerm2

## Start Daemon

```bash
cd $HOME/Documents/OSS/talk-to-claude && source .venv/bin/activate && python -m talk_to_claude.main start
```

## Voice Commands

Once started, you can use these voice commands:

- **"activate left upper window"** - Focus the top-left Claude Code pane
- **"activate right lower window"** - Focus the bottom-right Claude Code pane
- **"go to top right pane"** - Alternative phrasing for pane switching
- **"end voice"** - Submit your current voice input to Claude

## Notes

- The daemon will show a live transcript overlay in the top-right corner
- If you have only one Claude Code window, voice input goes directly there
- If you have multiple panes, use position commands to switch between them
- Overlay can be dragged, resized, and transparency adjusted with scroll wheel
