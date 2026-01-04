"""Voice Activity Detection (VAD) module.

This is an optional module for detecting when the user starts/stops speaking.
Currently a placeholder - can be enhanced with WebRTC VAD or Silero VAD.
"""

from typing import Callable, Optional

import numpy as np

from ..utils.logger import get_logger


class VoiceActivityDetector:
    """Simple energy-based voice activity detection."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        energy_threshold: float = 0.01,
        silence_duration_ms: int = 500,
    ):
        """Initialize VAD.

        Args:
            sample_rate: Audio sample rate in Hz
            frame_duration_ms: Duration of each frame to analyze
            energy_threshold: RMS energy threshold for speech detection
            silence_duration_ms: Duration of silence to trigger end of speech
        """
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.energy_threshold = energy_threshold
        self.silence_duration_ms = silence_duration_ms

        self._frame_size = int(sample_rate * frame_duration_ms / 1000)
        self._silence_frames = int(silence_duration_ms / frame_duration_ms)
        self._consecutive_silence = 0
        self._is_speaking = False
        self._logger = get_logger("audio.vad")

        # Callbacks
        self._on_speech_start: Optional[Callable[[], None]] = None
        self._on_speech_end: Optional[Callable[[], None]] = None

    def on_speech_start(self, callback: Callable[[], None]) -> None:
        """Register callback for speech start detection.

        Args:
            callback: Function to call when speech starts
        """
        self._on_speech_start = callback

    def on_speech_end(self, callback: Callable[[], None]) -> None:
        """Register callback for speech end detection.

        Args:
            callback: Function to call when speech ends
        """
        self._on_speech_end = callback

    def process_audio(self, audio_data: bytes) -> bool:
        """Process audio data and detect voice activity.

        Args:
            audio_data: Raw audio bytes (16-bit PCM)

        Returns:
            True if speech is detected in this frame
        """
        # Convert bytes to numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)

        # Normalize to [-1, 1]
        audio_array = audio_array / 32768.0

        # Calculate RMS energy
        rms_energy = np.sqrt(np.mean(audio_array ** 2))

        # Determine if speech is present
        is_speech = rms_energy > self.energy_threshold

        if is_speech:
            self._consecutive_silence = 0
            if not self._is_speaking:
                self._is_speaking = True
                self._logger.debug("Speech started")
                if self._on_speech_start:
                    self._on_speech_start()
        else:
            self._consecutive_silence += 1
            if self._is_speaking and self._consecutive_silence >= self._silence_frames:
                self._is_speaking = False
                self._logger.debug("Speech ended")
                if self._on_speech_end:
                    self._on_speech_end()

        return is_speech

    def reset(self) -> None:
        """Reset VAD state."""
        self._consecutive_silence = 0
        self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        """Check if user is currently speaking."""
        return self._is_speaking
