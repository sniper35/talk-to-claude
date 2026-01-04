"""OpenAI Realtime transcription client using WebSocket API."""

import asyncio
import base64
import json
from typing import Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from .base import BaseTranscriber
from ..utils.logger import get_logger


class OpenAITranscriber(BaseTranscriber):
    """Real-time speech-to-text using OpenAI's Realtime WebSocket API.

    Uses the Realtime API for true streaming transcription with:
    - Server-side voice activity detection (VAD)
    - Low-latency incremental transcripts
    - gpt-4o-transcribe model for high accuracy
    """

    REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
    REQUIRED_SAMPLE_RATE = 24000  # OpenAI Realtime API requires 24kHz

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-transcribe",
        language: str = "en",
        sample_rate: int = 16000,
        channels: int = 1,
        silence_duration_ms: int = 1000,
        vad_threshold: float = 0.5,
        **kwargs,  # Accept extra kwargs for compatibility
    ):
        """Initialize OpenAI Realtime transcriber.

        Args:
            api_key: OpenAI API key
            model: Model to use (gpt-4o-transcribe or gpt-4o-mini-transcribe)
            language: Language code for transcription
            sample_rate: Input audio sample rate in Hz (will be resampled to 24kHz)
            channels: Number of audio channels
            silence_duration_ms: Duration of silence to detect utterance end
            vad_threshold: Voice activity detection threshold (0.0 to 1.0)
        """
        self.api_key = api_key
        self.model = model
        self.language = language
        self.input_sample_rate = sample_rate
        self.channels = channels
        self.silence_duration_ms = silence_duration_ms
        self.vad_threshold = vad_threshold

        self._websocket: Optional[ClientConnection] = None
        self._transcript_callback: Optional[Callable[[str, bool], None]] = None
        self._utterance_end_callback: Optional[Callable[[], None]] = None
        self._logger = get_logger("transcription.openai")
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None
        self._current_transcript: str = ""

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
        """Establish WebSocket connection and configure transcription session."""
        if self._connected:
            self._logger.warning("Already connected to OpenAI Realtime API")
            return

        try:
            # Connect to WebSocket with required headers
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "OpenAI-Beta": "realtime=v1",
            }

            self._websocket = await websockets.connect(
                self.REALTIME_URL,
                additional_headers=headers,
            )
            self._connected = True
            self._logger.info("Connected to OpenAI Realtime API")

            # Configure the transcription session
            # For transcription-only sessions, use transcription_session.update
            session_config = {
                "type": "transcription_session.update",
                "session": {
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": self.model,
                        "language": self.language,
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": self.vad_threshold,
                        "silence_duration_ms": self.silence_duration_ms,
                    },
                },
            }
            await self._websocket.send(json.dumps(session_config))
            self._logger.debug(f"Sent session config: {session_config}")

            # Start receiving messages
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            self._logger.error(f"Failed to connect to OpenAI Realtime API: {e}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to OpenAI: {e}")

    async def _receive_loop(self) -> None:
        """Background task to receive and process WebSocket messages."""
        try:
            async for message in self._websocket:
                if not self._connected:
                    break

                try:
                    event = json.loads(message)
                    await self._handle_event(event)
                except json.JSONDecodeError as e:
                    self._logger.error(f"Failed to parse message: {e}")

        except websockets.exceptions.ConnectionClosed:
            self._logger.info("WebSocket connection closed")
        except Exception as e:
            if self._connected:
                self._logger.error(f"Error in receive loop: {e}")
        finally:
            self._connected = False

    async def _handle_event(self, event: dict) -> None:
        """Handle incoming WebSocket events.

        Args:
            event: Parsed JSON event from WebSocket
        """
        event_type = event.get("type", "")

        if event_type in ("session.created", "transcription_session.created"):
            self._logger.debug("Session created")

        elif event_type in ("session.updated", "transcription_session.updated"):
            self._logger.debug("Session updated")

        elif event_type == "input_audio_buffer.speech_started":
            self._logger.debug("Speech started")
            self._current_transcript = ""

        elif event_type == "input_audio_buffer.speech_stopped":
            self._logger.debug("Speech stopped")

        elif event_type == "conversation.item.input_audio_transcription.delta":
            # Incremental transcript update
            delta = event.get("delta", "")
            if delta:
                self._current_transcript += delta
                if self._transcript_callback:
                    self._transcript_callback(self._current_transcript, False)
                self._logger.debug(f"Transcript delta: {delta}")

        elif event_type == "conversation.item.input_audio_transcription.completed":
            # Final transcript for this utterance
            transcript = event.get("transcript", "")
            if transcript:
                self._current_transcript = transcript
                if self._transcript_callback:
                    self._transcript_callback(transcript, True)
                self._logger.debug(f"Transcript completed: {transcript}")

                # Signal utterance end
                if self._utterance_end_callback:
                    self._utterance_end_callback()

                self._current_transcript = ""

        elif event_type == "error":
            error = event.get("error", {})
            self._logger.error(f"OpenAI error: {error.get('message', 'Unknown error')}")

        elif event_type in ("response.created", "response.done", "response.output_item.added"):
            # Ignore response events (we're only doing transcription)
            pass

        else:
            self._logger.debug(f"Unhandled event type: {event_type}")

    def _resample_audio(self, audio_chunk: bytes) -> bytes:
        """Resample audio from input sample rate to 24kHz.

        Args:
            audio_chunk: Raw PCM audio at input sample rate

        Returns:
            Resampled PCM audio at 24kHz
        """
        if self.input_sample_rate == self.REQUIRED_SAMPLE_RATE:
            return audio_chunk

        import numpy as np

        # Convert bytes to numpy array (16-bit signed integers)
        samples = np.frombuffer(audio_chunk, dtype=np.int16)

        # Calculate resampling ratio
        ratio = self.REQUIRED_SAMPLE_RATE / self.input_sample_rate

        # Simple linear interpolation resampling
        num_output_samples = int(len(samples) * ratio)
        indices = np.linspace(0, len(samples) - 1, num_output_samples)
        resampled = np.interp(indices, np.arange(len(samples)), samples.astype(np.float32))

        # Convert back to 16-bit integers
        resampled = np.clip(resampled, -32768, 32767).astype(np.int16)

        return resampled.tobytes()

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to OpenAI for transcription.

        Args:
            audio_chunk: Raw audio data (16-bit PCM, mono)
        """
        if not self._connected or not self._websocket:
            self._logger.warning("Not connected to OpenAI, cannot send audio")
            return

        try:
            # Resample to 24kHz if needed
            resampled_audio = self._resample_audio(audio_chunk)

            # Base64 encode the audio
            audio_base64 = base64.b64encode(resampled_audio).decode("utf-8")

            # Send audio append event
            event = {
                "type": "input_audio_buffer.append",
                "audio": audio_base64,
            }
            await self._websocket.send(json.dumps(event))

        except Exception as e:
            self._logger.error(f"Error sending audio: {e}")

    async def stop_streaming(self) -> None:
        """Close WebSocket connection and cleanup."""
        if not self._connected:
            return

        try:
            self._connected = False

            # Cancel receive task
            if self._receive_task:
                self._receive_task.cancel()
                try:
                    await asyncio.wait_for(self._receive_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                self._receive_task = None

            # Close WebSocket
            if self._websocket:
                await self._websocket.close()
                self._websocket = None

            self._logger.info("OpenAI Realtime transcriber stopped")

        except Exception as e:
            self._logger.error(f"Error stopping OpenAI: {e}")
        finally:
            self._connected = False
            self._websocket = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to OpenAI Realtime API."""
        return self._connected


# Alias for backward compatibility
OpenAIWhisperTranscriber = OpenAITranscriber
