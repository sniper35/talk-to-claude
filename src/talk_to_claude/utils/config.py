"""Configuration management for Talk to Claude."""

import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# API keys configuration file
API_KEYS_FILE = Path.home() / ".claude_voice_api.json"


class Config:
    """Configuration manager that loads from YAML and environment variables."""

    DEFAULT_CONFIG = {
        "transcription": {
            "service": "deepgram",
            "api_key": None,  # Must be set via DEEPGRAM_API_KEY env var
            "model": "nova-2-general",
            "language": "en-US",
            "interim_results": True,
        },
        "audio": {
            "sample_rate": 16000,
            "channels": 1,
            "chunk_duration_ms": 100,
        },
        "feedback": {
            "show_live_transcript": True,
            "overlay_position": "top-right",
        },
        "commands": {
            "end_voice_phrase": "end voice",
            "additional_end_phrases": ["end audio", "submit", "send it", "done"],
            "window_activation_patterns": [
                "activate {position} window",
                "go to {position} pane",
                "switch to {position}",
            ],
        },
        "daemon": {
            "pid_file": "~/.talk-to-claude/daemon.pid",
            "log_file": "~/.talk-to-claude/daemon.log",
            "socket_path": "~/.talk-to-claude/daemon.sock",
        },
    }

    def __init__(self, config_path: str | Path | None = None):
        """Initialize configuration.

        Args:
            config_path: Path to YAML config file. If None, uses default locations.
        """
        load_dotenv()
        self._config = self._load_config(config_path)
        self._resolve_env_vars()
        self._expand_paths()

    def _load_config(self, config_path: str | Path | None) -> dict[str, Any]:
        """Load configuration from file or use defaults."""
        config = self.DEFAULT_CONFIG.copy()

        if config_path is None:
            # Try default locations
            locations = [
                Path.cwd() / "config" / "config.yaml",
                Path.home() / ".talk-to-claude" / "config.yaml",
            ]
            for loc in locations:
                if loc.exists():
                    config_path = loc
                    break

        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                user_config = yaml.safe_load(f) or {}
            config = self._deep_merge(config, user_config)

        return config

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _load_api_keys(self) -> dict[str, str]:
        """Load API keys from ~/.claude_voice_api.json.

        Returns:
            Dictionary mapping service names to API keys
        """
        if API_KEYS_FILE.exists():
            try:
                with open(API_KEYS_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _resolve_env_vars(self) -> None:
        """Resolve API keys from JSON file or environment variables.

        Priority:
        1. ~/.claude_voice_api.json
        2. Environment variables (DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, OPENAI_API_KEY)
        """
        if self._config["transcription"]["api_key"]:
            # Already set in config
            return

        # Load API keys from JSON file
        api_keys = self._load_api_keys()
        service = self._config["transcription"].get("service", "deepgram")

        # Try JSON file first, then environment variable
        api_key = api_keys.get(service)
        if not api_key:
            env_var = f"{service.upper()}_API_KEY"
            api_key = os.getenv(env_var)

        self._config["transcription"]["api_key"] = api_key

    def _expand_paths(self) -> None:
        """Expand ~ in path configurations."""
        daemon_config = self._config["daemon"]
        for key in ["pid_file", "log_file", "socket_path"]:
            if daemon_config.get(key):
                daemon_config[key] = str(Path(daemon_config[key]).expanduser())

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation.

        Args:
            key: Configuration key in dot notation (e.g., "transcription.api_key")
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def __getitem__(self, key: str) -> Any:
        """Get a top-level configuration section."""
        return self._config[key]

    @property
    def transcription(self) -> dict[str, Any]:
        """Get transcription configuration."""
        return self._config["transcription"]

    @property
    def audio(self) -> dict[str, Any]:
        """Get audio configuration."""
        return self._config["audio"]

    @property
    def feedback(self) -> dict[str, Any]:
        """Get feedback configuration."""
        return self._config["feedback"]

    @property
    def commands(self) -> dict[str, Any]:
        """Get commands configuration."""
        return self._config["commands"]

    @property
    def daemon(self) -> dict[str, Any]:
        """Get daemon configuration."""
        return self._config["daemon"]

    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        for key in ["pid_file", "log_file", "socket_path"]:
            path = Path(self.daemon[key])
            path.parent.mkdir(parents=True, exist_ok=True)
