"""Deepgram real-time transcription client."""

import asyncio
from typing import Callable

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)

from .base import BaseTranscriber
from ..utils.logger import get_logger


class DeepgramTranscriber(BaseTranscriber):
    """Real-time speech-to-text using Deepgram's streaming API."""

    def __init__(
        self,
        api_key: str,
        model: str = "nova-2-general",
        language: str = "en-US",
        interim_results: bool = True,
        smart_format: bool = True,
        utterance_end_ms: int = 1000,
    ):
        """Initialize Deepgram transcriber.

        Args:
            api_key: Deepgram API key
            model: Deepgram model to use
            language: Language code
            interim_results: Whether to receive interim (partial) results
            smart_format: Enable smart formatting (punctuation, etc.)
            utterance_end_ms: Milliseconds of silence to detect utterance end
        """
        self.api_key = api_key
        self.model = model
        self.language = language
        self.interim_results = interim_results
        self.smart_format = smart_format
        self.utterance_end_ms = utterance_end_ms

        self._client: DeepgramClient | None = None
        self._connection = None
        self._transcript_callback: Callable[[str, bool], None] | None = None
        self._utterance_end_callback: Callable[[], None] | None = None
        self._logger = get_logger("transcription.deepgram")
        self._connected = False

    def on_transcript(self, callback: Callable[[str, bool], None]) -> None:
        """Register callback for transcription results.

        Args:
            callback: Function called with (text, is_final) parameters
        """
        self._transcript_callback = callback

    def on_utterance_end(self, callback: Callable[[], None]) -> None:
        """Register callback for utterance end detection.

        Args:
            callback: Function called when utterance ends
        """
        self._utterance_end_callback = callback

    async def start_streaming(self) -> None:
        """Establish WebSocket connection for streaming transcription."""
        if self._connected:
            self._logger.warning("Already connected to Deepgram")
            return

        try:
            # Create Deepgram client
            config = DeepgramClientOptions(options={"keepalive": "true"})
            self._client = DeepgramClient(self.api_key, config)

            # Create live transcription connection
            self._connection = self._client.listen.asynclive.v("1")

            # Set up event handlers
            self._connection.on(LiveTranscriptionEvents.Open, self._on_open)
            self._connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
            self._connection.on(LiveTranscriptionEvents.UtteranceEnd, self._on_utterance_end)
            self._connection.on(LiveTranscriptionEvents.Error, self._on_error)
            self._connection.on(LiveTranscriptionEvents.Close, self._on_close)

            # Configure live options
            options = LiveOptions(
                model=self.model,
                language=self.language,
                smart_format=self.smart_format,
                interim_results=self.interim_results,
                utterance_end_ms=str(self.utterance_end_ms),
                encoding="linear16",
                sample_rate=16000,
                channels=1,
            )

            # Start the connection
            if await self._connection.start(options):
                self._connected = True
                self._logger.info("Connected to Deepgram streaming API")
            else:
                raise ConnectionError("Failed to connect to Deepgram")

        except Exception as e:
            self._logger.error(f"Failed to start Deepgram streaming: {e}")
            raise

    async def _on_open(self, client, open_response, **kwargs) -> None:
        """Handle connection open event."""
        self._logger.debug("Deepgram WebSocket connection opened")

    async def _on_transcript(self, client, result, **kwargs) -> None:
        """Handle transcription result event."""
        try:
            sentence = result.channel.alternatives[0].transcript
            if not sentence:
                return

            is_final = result.is_final
            if self._transcript_callback:
                self._transcript_callback(sentence, is_final)

            self._logger.debug(
                f"Transcript ({'final' if is_final else 'interim'}): {sentence}"
            )
        except Exception as e:
            self._logger.error(f"Error processing transcript: {e}")

    async def _on_utterance_end(self, client, utterance_end, **kwargs) -> None:
        """Handle utterance end event."""
        self._logger.debug("Utterance end detected")
        if self._utterance_end_callback:
            self._utterance_end_callback()

    async def _on_error(self, client, error, **kwargs) -> None:
        """Handle error event."""
        self._logger.error(f"Deepgram error: {error}")

    async def _on_close(self, client, close, **kwargs) -> None:
        """Handle connection close event."""
        self._logger.info("Deepgram connection closed")
        self._connected = False

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to Deepgram for transcription.

        Args:
            audio_chunk: Raw audio data (16-bit PCM, 16kHz, mono)
        """
        if not self._connected or not self._connection:
            self._logger.warning("Not connected to Deepgram, cannot send audio")
            return

        try:
            await self._connection.send(audio_chunk)
        except Exception as e:
            self._logger.error(f"Error sending audio to Deepgram: {e}")

    async def stop_streaming(self) -> None:
        """Close WebSocket connection."""
        if not self._connected:
            return

        try:
            if self._connection:
                await asyncio.wait_for(self._connection.finish(), timeout=2.0)
            self._logger.info("Deepgram streaming stopped")
        except asyncio.TimeoutError:
            self._logger.warning("Deepgram finish() timed out")
        except Exception as e:
            self._logger.error(f"Error stopping Deepgram streaming: {e}")
        finally:
            self._connected = False
            self._connection = None
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Deepgram."""
        return self._connected
