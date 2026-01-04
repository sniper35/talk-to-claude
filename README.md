# Talk to Claude

Voice-to-text interface for Claude Code terminals in iTerm2. Control multiple Claude Code sessions with your voice.

## Features

- **Voice Input**: Speak naturally and have your words transcribed and sent to Claude Code
- **Multi-Pane Support**: Switch between multiple iTerm2 panes using voice commands ("activate left upper window")
- **Live Transcript Overlay**: See real-time transcription in a draggable, resizable overlay
- **Multiple Transcription Services**: Choose from Deepgram, OpenAI, or ElevenLabs
- **Claude Code Integration**: Works seamlessly with Claude Code's `/start-audio` and `/stop-audio` commands

## Requirements

- macOS
- Python 3.10+
- iTerm2 with Python API enabled
- Microphone access
- API key for one of: Deepgram, OpenAI, or ElevenLabs

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/sniper35/talk-to-claude.git
   cd talk-to-claude
   ```

2. **Create virtual environment and install**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. **Enable iTerm2 Python API**:
   - Open iTerm2 Preferences
   - Go to General > Magic
   - Check "Enable Python API"

4. **Grant microphone permissions**:
   - System Preferences > Privacy & Security > Microphone
   - Enable for Terminal/iTerm2

## Configuration

1. **Set up API keys** in `~/.claude_voice_api.json`:
   ```json
   {
     "deepgram": "your-deepgram-api-key",
     "elevenlabs": "your-elevenlabs-api-key",
     "openai": "your-openai-api-key"
   }
   ```
   Only the key for your selected service is required.

2. **Copy and customize config** (optional):
   ```bash
   cp config/config.yaml.example config/config.yaml
   ```

   Key configuration options:
   - `transcription.service`: Choose `deepgram`, `openai`, or `elevenlabs`
   - `feedback.overlay.position`: Overlay position (`top-right`, `top-left`, etc.)
   - `commands.end_voice_phrase`: Phrase to submit input (default: "end voice")

## Usage

### With Claude Code (Recommended)

In Claude Code, use the built-in slash commands:

```
/start-audio   # Start voice input
/stop-audio    # Stop voice input
```

### Standalone

```bash
# Start the daemon
talk-to-claude start

# Check status
talk-to-claude status

# Stop the daemon
talk-to-claude stop
```

## Voice Commands

| Command | Action |
|---------|--------|
| "activate left upper window" | Focus top-left pane |
| "activate right lower window" | Focus bottom-right pane |
| "go to top right pane" | Alternative pane switching |
| "switch to bottom left" | Another alternative |
| "end voice" | Submit current input to Claude |

### Position Keywords

- **Horizontal**: left, right, center
- **Vertical**: top/upper, bottom/lower, middle

## Overlay Controls

- **Drag**: Move the overlay anywhere on screen
- **Resize**: Drag edges/corners to resize
- **Opacity**: Scroll wheel to adjust transparency
- **Position**: Saved automatically between sessions

## Troubleshooting

### "No active sessions" message
- Ensure Claude Code is running in iTerm2
- Check that iTerm2 Python API is enabled

### Microphone not working
- Verify microphone permissions in System Preferences
- Check that the correct input device is selected

### Transcription errors
- Verify your API key is correct in `~/.claude_voice_api.json`
- Check your internet connection
- Review logs at `~/.talk-to-claude/daemon.log`

## Project Structure

```
talk-to-claude/
├── src/talk_to_claude/
│   ├── audio/           # Audio capture and VAD
│   ├── iterm/           # iTerm2 integration
│   ├── transcription/   # Speech-to-text services
│   ├── ui/              # Overlay window
│   └── utils/           # Config and logging
├── config/              # Configuration files
└── .claude/commands/    # Claude Code slash commands
```

## License

MIT
