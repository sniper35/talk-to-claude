"""Command parser for voice commands."""

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from ..utils.logger import get_logger


class CommandType(Enum):
    """Types of parsed commands."""

    WINDOW_COMMAND = auto()  # Activate a specific window/pane
    END_VOICE = auto()  # End voice input and submit
    CLEAR_RESTART = auto()  # Clear input and restart listening
    TEXT = auto()  # Regular text to inject


class HorizontalPosition(Enum):
    """Horizontal position in split layout."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VerticalPosition(Enum):
    """Vertical position in split layout."""

    UPPER = "upper"
    MIDDLE = "middle"
    LOWER = "lower"


@dataclass
class WindowPosition:
    """Position of a window/pane in the split layout."""

    horizontal: HorizontalPosition
    vertical: VerticalPosition

    def __str__(self) -> str:
        return f"{self.vertical.value}-{self.horizontal.value}"


@dataclass
class ParseResult:
    """Result of parsing a voice command."""

    type: CommandType
    position: Optional[WindowPosition] = None
    text: Optional[str] = None


class CommandParser:
    """Parses voice input to identify commands vs regular text."""

    # Position word mappings
    HORIZONTAL_WORDS = {
        "left": HorizontalPosition.LEFT,
        "right": HorizontalPosition.RIGHT,
        "center": HorizontalPosition.CENTER,
        "middle": HorizontalPosition.CENTER,
    }

    VERTICAL_WORDS = {
        "upper": VerticalPosition.UPPER,
        "top": VerticalPosition.UPPER,
        "lower": VerticalPosition.LOWER,
        "bottom": VerticalPosition.LOWER,
        "middle": VerticalPosition.MIDDLE,
        "center": VerticalPosition.MIDDLE,
    }

    # Window command patterns
    WINDOW_PATTERNS = [
        r"(?:activate|go to|switch to)\s+(?:the\s+)?(.+?)\s*(?:window|pane)?$",
    ]

    def __init__(
        self,
        end_voice_phrase: str = "end voice",
        additional_end_phrases: list[str] | None = None,
        clear_restart_phrases: list[str] | None = None,
    ):
        """Initialize command parser.

        Args:
            end_voice_phrase: Primary phrase to end voice input
            additional_end_phrases: Additional phrases that end voice input
            clear_restart_phrases: Phrases that clear input and restart listening
        """
        self.end_voice_phrases = [end_voice_phrase.lower()]
        if additional_end_phrases:
            self.end_voice_phrases.extend(p.lower() for p in additional_end_phrases)

        self.clear_restart_phrases = clear_restart_phrases or ["clear and restart", "start over", "never mind"]
        self.clear_restart_phrases = [p.lower() for p in self.clear_restart_phrases]

        self._logger = get_logger("transcription.parser")
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.WINDOW_PATTERNS]

    def parse(self, text: str) -> ParseResult:
        """Parse transcribed text for commands.

        Args:
            text: Transcribed text to parse

        Returns:
            ParseResult with command type and relevant data
        """
        text = text.strip()
        text_lower = text.lower()

        # Check for clear and restart command first
        for phrase in self.clear_restart_phrases:
            if phrase in text_lower:
                self._logger.debug(f"Detected clear/restart command: {text}")
                return ParseResult(type=CommandType.CLEAR_RESTART)

        # Check for end voice command
        for phrase in self.end_voice_phrases:
            if phrase in text_lower:
                self._logger.debug(f"Detected end voice command: {text}")
                # Extract any text before the end phrase
                idx = text_lower.find(phrase)
                prefix_text = text[:idx].strip()
                return ParseResult(
                    type=CommandType.END_VOICE,
                    text=prefix_text if prefix_text else None,
                )

        # Check for window activation command
        position = self._parse_window_command(text)
        if position:
            self._logger.debug(f"Detected window command: {position}")
            return ParseResult(type=CommandType.WINDOW_COMMAND, position=position)

        # Default: regular text
        return ParseResult(type=CommandType.TEXT, text=text)

    def _parse_window_command(self, text: str) -> WindowPosition | None:
        """Parse text for window activation command.

        Args:
            text: Text to parse

        Returns:
            WindowPosition if command found, None otherwise
        """
        for pattern in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                position_text = match.group(1).lower()
                return self._parse_position(position_text)

        return None

    def _parse_position(self, position_text: str) -> WindowPosition | None:
        """Parse position text into WindowPosition.

        Args:
            position_text: Text describing position (e.g., "left upper", "top right")

        Returns:
            WindowPosition if valid, None otherwise
        """
        words = position_text.split()

        horizontal: HorizontalPosition | None = None
        vertical: VerticalPosition | None = None

        for word in words:
            word = word.strip()
            if word in self.HORIZONTAL_WORDS:
                horizontal = self.HORIZONTAL_WORDS[word]
            elif word in self.VERTICAL_WORDS:
                vertical = self.VERTICAL_WORDS[word]

        # Default values if not specified
        if horizontal is None:
            horizontal = HorizontalPosition.CENTER
        if vertical is None:
            vertical = VerticalPosition.MIDDLE

        # Only return if at least one position was specified
        if any(w in self.HORIZONTAL_WORDS or w in self.VERTICAL_WORDS for w in words):
            return WindowPosition(horizontal=horizontal, vertical=vertical)

        return None

    def is_command_prefix(self, text: str) -> bool:
        """Check if text starts with a command prefix.

        Useful for detecting partial commands during interim results.

        Args:
            text: Text to check

        Returns:
            True if text appears to be starting a command
        """
        text_lower = text.lower().strip()
        command_prefixes = ["activate", "go to", "switch to", "end"]
        return any(text_lower.startswith(prefix) for prefix in command_prefixes)
