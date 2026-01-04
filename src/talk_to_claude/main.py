"""Main daemon for Talk to Claude - Voice interface for Claude Code."""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from .audio.capture import AudioCapture
from .iterm.controller import ITermController
from .iterm.session_manager import SessionManager
from .transcription.base import BaseTranscriber
from .transcription.command_parser import CommandParser, CommandType
from .transcription.factory import create_transcriber
from .ui.overlay import TranscriptOverlay
from .utils.config import Config
from .utils.logger import setup_logger, get_logger


class TalkToClaudeDaemon:
    """Main daemon that orchestrates voice-to-Claude functionality."""

    def __init__(self, config: Config):
        """Initialize the daemon.

        Args:
            config: Configuration object
        """
        self.config = config
        self._logger = get_logger("daemon")

        # Components
        self._audio: Optional[AudioCapture] = None
        self._transcriber: Optional[BaseTranscriber] = None
        self._parser: Optional[CommandParser] = None
        self._iterm: Optional[ITermController] = None
        self._session_manager: Optional[SessionManager] = None
        self._overlay: Optional[TranscriptOverlay] = None

        # State
        self._running = False
        self._text_buffer = ""
        self._shutdown_event = asyncio.Event()
        self._session_refresh_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the daemon and all components."""
        self._logger.info("Starting Talk to Claude daemon...")

        try:
            # Initialize components
            await self._init_components()

            # Set up signal handlers
            self._setup_signal_handlers()

            # Write PID file
            self._write_pid_file()

            self._running = True
            self._logger.info("Daemon started successfully")

            # Run main loop
            await self._main_loop()

        except Exception as e:
            self._logger.error(f"Fatal error: {e}")
            raise
        finally:
            await self.stop()

    async def _init_components(self) -> None:
        """Initialize all components."""
        # Audio capture
        audio_config = self.config.audio
        self._audio = AudioCapture(
            sample_rate=audio_config["sample_rate"],
            channels=audio_config["channels"],
            chunk_duration_ms=audio_config["chunk_duration_ms"],
        )

        # Transcription service (Deepgram, ElevenLabs, or OpenAI)
        trans_config = self.config.transcription
        service = trans_config.get("service", "deepgram")
        api_key = trans_config.get("api_key")
        if not api_key:
            service_upper = service.upper()
            raise ValueError(
                f"{service_upper}_API_KEY not set. "
                f"Please set it in your environment or config."
            )

        # Build config dict for factory with audio settings included
        factory_config = {
            **trans_config,
            "sample_rate": audio_config["sample_rate"],
            "channels": audio_config["channels"],
        }

        self._transcriber = create_transcriber(service, factory_config)
        self._logger.info(f"Using transcription service: {service}")

        # Command parser
        cmd_config = self.config.commands
        self._parser = CommandParser(
            end_voice_phrase=cmd_config.get("end_voice_phrase", "end voice"),
            additional_end_phrases=cmd_config.get("additional_end_phrases"),
        )

        # iTerm2 controller and session manager
        self._iterm = ITermController()
        await self._iterm.connect()
        self._session_manager = SessionManager(self._iterm)
        await self._session_manager.refresh_sessions()

        # Transcript overlay
        feedback_config = self.config.feedback
        if feedback_config.get("show_live_transcript", True):
            overlay_config = feedback_config.get("overlay", {})
            self._overlay = TranscriptOverlay(
                position=overlay_config.get("position", "top-right"),
                width=overlay_config.get("default_width", 400),
                height=overlay_config.get("default_height", 60),
                default_opacity=overlay_config.get("default_opacity", 0.8),
                min_width=overlay_config.get("min_width", 200),
                min_height=overlay_config.get("min_height", 40),
                remember_position=overlay_config.get("remember_position", True),
            )
            self._overlay.start()

        # Set up transcription callbacks
        self._transcriber.on_transcript(self._on_transcript)
        self._transcriber.on_utterance_end(self._on_utterance_end)

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        self._logger.info("Received shutdown signal")
        self._shutdown_event.set()

    def _write_pid_file(self) -> None:
        """Write PID file for daemon management."""
        pid_file = Path(self.config.daemon["pid_file"])
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))
        self._logger.debug(f"PID file written: {pid_file}")

    def _remove_pid_file(self) -> None:
        """Remove PID file."""
        pid_file = Path(self.config.daemon["pid_file"])
        if pid_file.exists():
            pid_file.unlink()
            self._logger.debug("PID file removed")

    async def _main_loop(self) -> None:
        """Main processing loop."""
        # Start audio capture
        self._audio.start()

        # Start transcription streaming
        await self._transcriber.start_streaming()

        # Start periodic session refresh task
        self._session_refresh_task = asyncio.create_task(self._periodic_session_refresh())

        # Show listening indicator
        if self._overlay:
            self._overlay.set_listening(True)

        self._logger.info("Listening for voice input...")

        try:
            # Stream audio to transcriber
            async for audio_chunk in self._audio.get_audio_stream():
                if self._shutdown_event.is_set():
                    break

                await self._transcriber.send_audio(audio_chunk)

        except asyncio.CancelledError:
            self._logger.info("Main loop cancelled")
        finally:
            # Cancel session refresh task
            if self._session_refresh_task:
                self._session_refresh_task.cancel()
                try:
                    await self._session_refresh_task
                except asyncio.CancelledError:
                    pass

    async def _periodic_session_refresh(self) -> None:
        """Periodically refresh sessions to detect new/closed Claude sessions."""
        refresh_interval = 5.0  # seconds

        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(refresh_interval)

                if self._shutdown_event.is_set():
                    break

                try:
                    previous_count = self._session_manager.get_session_count()
                    await self._session_manager.refresh_sessions()
                    current_count = self._session_manager.get_session_count()

                    # Log changes in session count
                    if current_count != previous_count:
                        self._logger.info(
                            f"Session count changed: {previous_count} -> {current_count}"
                        )

                        # Update overlay if no sessions
                        if current_count == 0 and self._overlay:
                            self._overlay.update_text("No active sessions", is_final=True)
                        elif previous_count == 0 and current_count > 0 and self._overlay:
                            # Sessions became available again
                            self._overlay.clear()
                            self._overlay.set_listening(True)

                except Exception as e:
                    self._logger.debug(f"Session refresh error: {e}")

        except asyncio.CancelledError:
            pass

    def _on_transcript(self, text: str, is_final: bool) -> None:
        """Handle transcription results.

        Args:
            text: Transcribed text
            is_final: Whether this is a final result
        """
        # Update overlay
        if self._overlay:
            self._overlay.update_text(text, is_final)

        if not is_final:
            # Interim result - just display
            return

        # Final result - process it
        self._process_transcript(text)

    def _on_utterance_end(self) -> None:
        """Handle utterance end detection."""
        self._logger.debug("Utterance end detected")

    def _process_transcript(self, text: str) -> None:
        """Process a final transcript.

        Args:
            text: Final transcribed text
        """
        if not text.strip():
            return

        # Parse the text for commands
        result = self._parser.parse(text)

        if result.type == CommandType.WINDOW_COMMAND:
            # Handle window activation command
            asyncio.create_task(self._handle_window_command(result.position))

        elif result.type == CommandType.CLEAR_RESTART:
            # Handle clear and restart command
            asyncio.create_task(self._clear_and_restart())

        elif result.type == CommandType.END_VOICE:
            # Handle end voice command - submit accumulated text
            if result.text:
                self._text_buffer += " " + result.text
            asyncio.create_task(self._submit_text())

        else:
            # Regular text - accumulate (don't inject in real-time for performance)
            if self._text_buffer:
                self._text_buffer += " " + result.text
            else:
                self._text_buffer = result.text

    async def _handle_window_command(self, position) -> None:
        """Handle window activation command.

        Args:
            position: Target window position
        """
        self._logger.info(f"Activating window at position: {position}")

        try:
            session = await self._session_manager.get_session_for_position(position)
            if session:
                await self._session_manager.set_active_session(session)
                if self._overlay:
                    self._overlay.update_text(f"Activated {position}", is_final=True)
            else:
                self._logger.warning(f"No session found at position: {position}")
                if self._overlay:
                    self._overlay.update_text(f"No window at {position}", is_final=True)
        except Exception as e:
            self._logger.error(f"Error activating window: {e}")

    async def _inject_text(self, text: str) -> None:
        """Inject text into the active session.

        Args:
            text: Text to inject
        """
        try:
            success = await self._session_manager.send_text_to_active(text + " ")
            if not success:
                self._logger.warning("Failed to inject text - no active session")
        except Exception as e:
            self._logger.error(f"Error injecting text: {e}")

    async def _clear_and_restart(self) -> None:
        """Clear current input and restart listening."""
        self._logger.info("Clearing input and restarting...")

        # Clear the text buffer
        self._text_buffer = ""

        # Clear the current line in the terminal (send Ctrl+U to clear line)
        try:
            await self._session_manager.clear_current_line()
        except Exception as e:
            self._logger.error(f"Error clearing line: {e}")

        # Update overlay
        if self._overlay:
            self._overlay.clear()
            self._overlay.set_listening(True)

    async def _submit_text(self) -> None:
        """Submit the accumulated text buffer."""
        if not self._text_buffer.strip():
            self._logger.debug("No text to submit")
            return

        self._logger.info(f"Submitting text: {self._text_buffer}")

        try:
            # Clear the current line first (in case of partial text)
            # Then send the complete text with newline
            success = await self._session_manager.submit_to_active(self._text_buffer.strip())
            if success:
                if self._overlay:
                    self._overlay.update_text("Submitted!", is_final=True)
                    await asyncio.sleep(1)

                    # Refresh sessions to check if there are still active Claude sessions
                    await self._session_manager.refresh_sessions()
                    session_count = self._session_manager.get_session_count()

                    if session_count > 0:
                        # Still have active sessions - continue listening
                        self._overlay.clear()
                        self._overlay.set_listening(True)
                        self._logger.debug(f"Still have {session_count} active Claude session(s)")
                    else:
                        # No more sessions - show message but keep listening
                        # (user might open new Claude sessions)
                        self._overlay.update_text("No active sessions", is_final=True)
                        self._logger.info("No active Claude sessions remaining")
            else:
                self._logger.warning("Failed to submit - no active session")
                if self._overlay:
                    self._overlay.update_text("No active session", is_final=True)

        except Exception as e:
            self._logger.error(f"Error submitting text: {e}")
        finally:
            self._text_buffer = ""

    async def stop(self) -> None:
        """Stop the daemon and cleanup."""
        self._logger.info("Stopping daemon...")
        self._running = False

        # Stop components with timeouts to prevent hanging
        if self._audio:
            self._audio.stop()

        if self._transcriber:
            try:
                await asyncio.wait_for(self._transcriber.stop_streaming(), timeout=3.0)
            except asyncio.TimeoutError:
                self._logger.warning("Transcriber stop timed out")

        if self._overlay:
            self._overlay.stop()

        if self._iterm:
            try:
                await asyncio.wait_for(self._iterm.disconnect(), timeout=2.0)
            except asyncio.TimeoutError:
                self._logger.warning("iTerm disconnect timed out")

        # Remove PID file
        self._remove_pid_file()

        self._logger.info("Daemon stopped")


def get_pid() -> Optional[int]:
    """Get the running daemon PID.

    Returns:
        PID if daemon is running, None otherwise
    """
    config = Config()
    pid_file = Path(config.daemon["pid_file"])

    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process is running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        return None


def start_daemon() -> None:
    """Start the daemon."""
    # Check if already running
    pid = get_pid()
    if pid:
        print(f"Daemon already running with PID {pid}")
        sys.exit(1)

    # Clean up any orphaned processes from previous runs
    _cleanup_orphaned_processes()

    # Initialize configuration
    config = Config()
    config.ensure_directories()

    # Set up logging
    logger = setup_logger(
        name="talk_to_claude",
        log_file=config.daemon["log_file"],
        console=True,
    )

    logger.info("Initializing Talk to Claude...")

    # Create and run daemon
    daemon = TalkToClaudeDaemon(config)

    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Daemon error: {e}")
        sys.exit(1)


def _cleanup_orphaned_processes() -> None:
    """Clean up any orphaned overlay subprocesses from previous runs.

    Finds Python processes spawned for multiprocessing that have PPID=1
    (orphaned, parent died) and are running our overlay code.
    """
    import subprocess

    try:
        # Find orphaned multiprocessing spawn processes (PPID=1)
        result = subprocess.run(
            ["pgrep", "-f", "multiprocessing.spawn"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return  # No matches

        pids = result.stdout.strip().split('\n')
        for pid in pids:
            if not pid:
                continue

            # Check if this process has PPID=1 (orphaned)
            ps_result = subprocess.run(
                ["ps", "-o", "ppid=", "-p", pid],
                capture_output=True,
                text=True
            )

            if ps_result.returncode == 0:
                ppid = ps_result.stdout.strip()
                if ppid == "1":
                    # This is an orphaned process - kill it
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        print(f"Cleaned up orphaned overlay process (PID {pid})")
                    except (ProcessLookupError, PermissionError):
                        pass

    except Exception:
        pass  # Non-critical - continue even if cleanup fails


def stop_daemon() -> None:
    """Stop the running daemon."""
    pid = get_pid()
    if not pid:
        print("Daemon is not running")
        # Still cleanup orphans even if main daemon not running
        _cleanup_orphaned_processes()
        return

    print(f"Stopping daemon (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)

        # Wait for graceful shutdown
        import time
        for _ in range(20):  # Wait up to 2 seconds
            time.sleep(0.1)
            try:
                os.kill(pid, 0)  # Check if still running
            except ProcessLookupError:
                break

        # Force kill if still running
        try:
            os.kill(pid, 0)
            print("Daemon didn't stop gracefully, force killing...")
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        print("Daemon stopped")

    except ProcessLookupError:
        print("Daemon was not running")
    except PermissionError:
        print("Permission denied - cannot stop daemon")
        sys.exit(1)

    # Clean up any orphaned overlay processes
    _cleanup_orphaned_processes()


def status_daemon() -> None:
    """Check daemon status."""
    pid = get_pid()
    if pid:
        print(f"Daemon is running (PID {pid})")
    else:
        print("Daemon is not running")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Talk to Claude - Voice interface for Claude Code"
    )
    parser.add_argument(
        "command",
        choices=["start", "stop", "status"],
        help="Command to execute",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file",
    )

    args = parser.parse_args()

    if args.command == "start":
        start_daemon()
    elif args.command == "stop":
        stop_daemon()
    elif args.command == "status":
        status_daemon()


if __name__ == "__main__":
    main()
