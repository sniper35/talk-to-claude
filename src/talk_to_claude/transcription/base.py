"""Abstract base class for speech-to-text transcription services."""

from abc import ABC, abstractmethod
from typing import Callable


class BaseTranscriber(ABC):
    """Abstract base class for speech-to-text transcription services.

    All transcription providers must implement this interface to ensure
    consistent behavior across different services (Deepgram, ElevenLabs, OpenAI, etc.).
    """

    @abstractmethod
    def on_transcript(self, callback: Callable[[str, bool], None]) -> None:
        """Register callback for transcription results.

        Args:
            callback: Function called with (text, is_final) parameters.
                     - text: The transcribed text
                     - is_final: Whether this is a final result or interim
        """
        ...

    @abstractmethod
    def on_utterance_end(self, callback: Callable[[], None]) -> None:
        """Register callback for utterance end detection.

        Args:
            callback: Function called when an utterance ends (silence detected)
        """
        ...

    @abstractmethod
    async def start_streaming(self) -> None:
        """Start the streaming connection for real-time transcription.

        Establishes connection to the transcription service and prepares
        to receive audio data.

        Raises:
            ConnectionError: If unable to connect to the service
        """
        ...

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to the transcription service.

        Args:
            audio_chunk: Raw audio data (typically 16-bit PCM, 16kHz, mono)
        """
        ...

    @abstractmethod
    async def stop_streaming(self) -> None:
        """Stop the streaming connection and cleanup resources."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to the transcription service.

        Returns:
            True if connected and ready to receive audio, False otherwise
        """
        ...
