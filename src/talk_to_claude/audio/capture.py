"""Audio capture from microphone using sounddevice."""

import asyncio
import queue
import threading
from typing import AsyncIterator

import numpy as np
import sounddevice as sd

from ..utils.logger import get_logger


class AudioCapture:
    """Captures audio from the microphone for streaming to transcription service."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 100,
        dtype: str = "int16",
    ):
        """Initialize audio capture.

        Args:
            sample_rate: Audio sample rate in Hz (16000 recommended for speech)
            channels: Number of audio channels (1 for mono)
            chunk_duration_ms: Duration of each audio chunk in milliseconds
            dtype: Audio data type (int16 for 16-bit PCM)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        self.dtype = dtype
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)

        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._running = False
        self._logger = get_logger("audio.capture")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        """Callback function called by sounddevice for each audio chunk.

        Args:
            indata: Input audio data as numpy array
            frames: Number of frames
            time_info: Timing information
            status: Status flags
        """
        if status:
            self._logger.warning(f"Audio callback status: {status}")

        # Convert to bytes and add to queue
        audio_bytes = indata.tobytes()
        try:
            self._audio_queue.put_nowait(audio_bytes)
        except queue.Full:
            self._logger.warning("Audio queue full, dropping chunk")

    def start(self) -> None:
        """Start capturing audio from the default microphone."""
        if self._running:
            self._logger.warning("Audio capture already running")
            return

        self._running = True
        self._audio_queue = queue.Queue(maxsize=100)

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.chunk_size,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._logger.info(
                f"Audio capture started: {self.sample_rate}Hz, "
                f"{self.channels}ch, {self.chunk_duration_ms}ms chunks"
            )
        except Exception as e:
            self._running = False
            self._logger.error(f"Failed to start audio capture: {e}")
            raise

    def stop(self) -> None:
        """Stop audio capture."""
        if not self._running:
            return

        self._running = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # Clear the queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        self._logger.info("Audio capture stopped")

    async def get_audio_stream(self) -> AsyncIterator[bytes]:
        """Async generator that yields audio chunks.

        Yields:
            Audio data as bytes
        """
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Use run_in_executor to avoid blocking the event loop
                audio_chunk = await loop.run_in_executor(
                    None, self._audio_queue.get, True, 0.1
                )
                yield audio_chunk
            except queue.Empty:
                # No audio available, continue waiting
                continue
            except Exception as e:
                if self._running:
                    self._logger.error(f"Error getting audio chunk: {e}")
                break

    @property
    def is_running(self) -> bool:
        """Check if audio capture is running."""
        return self._running

    @staticmethod
    def list_devices() -> list[dict]:
        """List available audio input devices.

        Returns:
            List of device information dictionaries
        """
        devices = sd.query_devices()
        input_devices = []
        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                input_devices.append({
                    "index": i,
                    "name": device["name"],
                    "channels": device["max_input_channels"],
                    "sample_rate": device["default_samplerate"],
                })
        return input_devices
