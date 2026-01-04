"""ElevenLabs real-time transcription client."""

import asyncio
import json
from typing import Callable, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from .base import BaseTranscriber
from ..utils.logger import get_logger


class ElevenLabsTranscriber(BaseTranscriber):
    """Real-time speech-to-text using ElevenLabs' streaming API.

    ElevenLabs provides the Scribe model for speech-to-text transcription
    with support for real-time WebSocket streaming.
    """

    # ElevenLabs Speech-to-Text WebSocket endpoint
    WEBSOCKET_URL = "wss://api.elevenlabs.io/v1/speech-to-text/websocket"

    def __init__(
        self,
        api_key: str,
        model: str = "scribe_v1",
        language_code: str = "en",
        sample_rate: int = 16000,
    ):
        """Initialize ElevenLabs transcriber.

        Args:
            api_key: ElevenLabs API key
            model: Model to use (scribe_v1 is the primary STT model)
            language_code: Language code (e.g., 'en', 'es', 'fr')
            sample_rate: Audio sample rate in Hz
        """
        self.api_key = api_key
        self.model = model
        self.language_code = language_code
        self.sample_rate = sample_rate

        self._websocket: Optional[WebSocketClientProtocol] = None
        self._transcript_callback: Optional[Callable[[str, bool], None]] = None
        self._utterance_end_callback: Optional[Callable[[], None]] = None
        self._logger = get_logger("transcription.elevenlabs")
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None
        self._accumulated_text = ""
        self._last_final_text = ""

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
            self._logger.warning("Already connected to ElevenLabs")
            return

        try:
            # Build WebSocket URL with query parameters
            url = (
                f"{self.WEBSOCKET_URL}"
                f"?model_id={self.model}"
                f"&language_code={self.language_code}"
                f"&sample_rate={self.sample_rate}"
                f"&encoding=pcm_s16le"
            )

            # Connect with API key in header
            headers = {
                "xi-api-key": self.api_key,
            }

            self._websocket = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )

            self._connected = True
            self._logger.info("Connected to ElevenLabs streaming API")

            # Start receiving messages in background
            self._receive_task = asyncio.create_task(self._receive_messages())

        except Exception as e:
            self._logger.error(f"Failed to start ElevenLabs streaming: {e}")
            raise ConnectionError(f"Failed to connect to ElevenLabs: {e}")

    async def _receive_messages(self) -> None:
        """Receive and process messages from WebSocket."""
        try:
            async for message in self._websocket:
                await self._handle_message(message)
        except websockets.exceptions.ConnectionClosed as e:
            self._logger.info(f"ElevenLabs connection closed: {e}")
        except asyncio.CancelledError:
            self._logger.debug("Receive task cancelled")
        except Exception as e:
            self._logger.error(f"Error receiving ElevenLabs messages: {e}")
        finally:
            self._connected = False

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message.

        Args:
            message: JSON message from ElevenLabs
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "transcript":
                # Handle transcription result
                text = data.get("text", "")
                is_final = data.get("is_final", False)

                if text:
                    if self._transcript_callback:
                        self._transcript_callback(text, is_final)

                    self._logger.debug(
                        f"Transcript ({'final' if is_final else 'interim'}): {text}"
                    )

                    if is_final:
                        self._last_final_text = text

            elif msg_type == "utterance_end":
                # Handle utterance end
                self._logger.debug("Utterance end detected")
                if self._utterance_end_callback:
                    self._utterance_end_callback()

            elif msg_type == "error":
                # Handle error message
                error_msg = data.get("message", "Unknown error")
                self._logger.error(f"ElevenLabs error: {error_msg}")

            elif msg_type == "connected":
                self._logger.debug("ElevenLabs WebSocket connection confirmed")

        except json.JSONDecodeError as e:
            self._logger.error(f"Failed to parse ElevenLabs message: {e}")
        except Exception as e:
            self._logger.error(f"Error handling ElevenLabs message: {e}")

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to ElevenLabs for transcription.

        Args:
            audio_chunk: Raw audio data (16-bit PCM, specified sample rate, mono)
        """
        if not self._connected or not self._websocket:
            self._logger.warning("Not connected to ElevenLabs, cannot send audio")
            return

        try:
            # ElevenLabs expects binary audio data directly
            await self._websocket.send(audio_chunk)
        except websockets.exceptions.ConnectionClosed:
            self._logger.warning("ElevenLabs connection closed while sending audio")
            self._connected = False
        except Exception as e:
            self._logger.error(f"Error sending audio to ElevenLabs: {e}")

    async def stop_streaming(self) -> None:
        """Close WebSocket connection."""
        if not self._connected:
            return

        try:
            # Cancel receive task
            if self._receive_task:
                self._receive_task.cancel()
                try:
                    await asyncio.wait_for(self._receive_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                self._receive_task = None

            # Send end of stream signal if supported
            if self._websocket:
                try:
                    # Send empty message or close command
                    await asyncio.wait_for(
                        self._websocket.close(),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    self._logger.warning("ElevenLabs close timed out")

            self._logger.info("ElevenLabs streaming stopped")

        except Exception as e:
            self._logger.error(f"Error stopping ElevenLabs streaming: {e}")
        finally:
            self._connected = False
            self._websocket = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to ElevenLabs."""
        return self._connected
