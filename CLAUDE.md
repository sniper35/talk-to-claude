# Claude Code Project Guidelines

## Project Overview

Talk to Claude is a voice-to-text interface for Claude Code terminals in iTerm2. It captures audio, transcribes speech using cloud APIs, and sends text to Claude Code sessions.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Audio Capture  │────▶│  Transcription   │────▶│  Command Parser │
│  (sounddevice)  │     │  (Deepgram/      │     │  (detects voice │
│                 │     │   OpenAI/11Labs) │     │   commands)     │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
┌─────────────────┐     ┌──────────────────┐              │
│  Overlay UI     │◀────│  iTerm2          │◀─────────────┘
│  (Cocoa/AppKit) │     │  Controller      │
└─────────────────┘     └──────────────────┘
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `audio/capture.py` | Microphone capture using sounddevice |
| `audio/vad.py` | Voice activity detection |
| `transcription/` | Speech-to-text providers (Deepgram, OpenAI, ElevenLabs) |
| `transcription/command_parser.py` | Parses voice commands (window activation, end voice) |
| `iterm/controller.py` | iTerm2 Python API integration |
| `iterm/session_manager.py` | Manages Claude Code sessions across panes |
| `iterm/position_detector.py` | Detects pane positions (left/right/top/bottom) |
| `ui/overlay.py` | Live transcript overlay window |
| `utils/config.py` | Configuration loading from YAML |
| `main.py` | Daemon lifecycle management |

## Configuration

- **API keys**: `~/.claude_voice_api.json` (JSON with service keys)
- **Settings**: `config/config.yaml` (copied from `config.yaml.example`)
- **Daemon files**: `~/.talk-to-claude/` (PID, logs, socket)

## Development

### Running locally

```bash
source .venv/bin/activate
python -m talk_to_claude.main start
```

### Adding a new transcription service

1. Create `src/talk_to_claude/transcription/newservice_client.py`
2. Implement `BaseTranscriber` interface from `transcription/base.py`
3. Register in `transcription/factory.py`
4. Add config section in `config/config.yaml.example`

### Testing

```bash
pip install -e ".[dev]"
pytest
```

## Code Style

- Use async/await for I/O operations
- Type hints for function signatures
- Logging via `utils.logger.get_logger()`

## Voice Command Parsing

Commands are parsed in `transcription/command_parser.py`:

- **Window commands**: "activate {position} window", "go to {position} pane"
- **End voice**: "end voice" (configurable)
- **Positions**: left, right, top, bottom, upper, lower, center, middle

## iTerm2 Integration

Uses `iterm2` Python library to:
- Connect to iTerm2 via its scripting API
- Enumerate windows, tabs, and sessions
- Detect session positions within split panes
- Send keystrokes to specific sessions
