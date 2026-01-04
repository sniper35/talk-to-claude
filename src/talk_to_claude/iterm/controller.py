"""iTerm2 controller for session management and text injection."""

import asyncio
from typing import Callable, List, Optional

import iterm2

from ..transcription.command_parser import WindowPosition
from ..utils.logger import get_logger
from .position_detector import PositionDetector, SessionPosition


class ITermController:
    """Controls iTerm2 sessions via the Python API."""

    def __init__(self):
        self._connection: iterm2.Connection | None = None
        self._app: iterm2.App | None = None
        self._position_detector = PositionDetector()
        self._logger = get_logger("iterm.controller")
        self._connected = False

    async def connect(self) -> None:
        """Connect to iTerm2 application.

        Raises:
            ConnectionError: If unable to connect to iTerm2
        """
        if self._connected:
            self._logger.warning("Already connected to iTerm2")
            return

        try:
            self._connection = await iterm2.Connection.async_create()
            self._app = await iterm2.async_get_app(self._connection)
            self._connected = True
            self._logger.info("Connected to iTerm2")
        except Exception as e:
            self._logger.error(f"Failed to connect to iTerm2: {e}")
            raise ConnectionError(f"Cannot connect to iTerm2: {e}")

    async def disconnect(self) -> None:
        """Disconnect from iTerm2."""
        self._connected = False
        self._connection = None
        self._app = None
        self._logger.info("Disconnected from iTerm2")

    async def get_current_tab(self) -> Optional[iterm2.Tab]:
        """Get the currently active tab.

        Returns:
            Current tab or None
        """
        if not self._app:
            return None

        window = self._app.current_window
        if window:
            return window.current_tab
        return None

    async def get_all_sessions(self) -> List[iterm2.Session]:
        """Get all sessions across all windows and tabs.

        Returns:
            List of all sessions
        """
        if not self._app:
            return []

        sessions = []
        for window in self._app.windows:
            for tab in window.tabs:
                sessions.extend(tab.sessions)
        return sessions

    async def get_claude_sessions(self) -> List[iterm2.Session]:
        """Find all sessions running Claude Code.

        Returns:
            List of sessions running Claude Code
        """
        all_sessions = await self.get_all_sessions()
        claude_sessions = []

        for session in all_sessions:
            if await self._is_claude_session(session):
                claude_sessions.append(session)

        return claude_sessions

    async def _is_claude_session(self, session: iterm2.Session) -> bool:
        """Check if a session is running Claude Code.

        Args:
            session: Session to check

        Returns:
            True if session is running Claude Code
        """
        try:
            # Get the session's current command/process name with timeout
            profile = await asyncio.wait_for(
                session.async_get_profile(), timeout=1.0
            )
            name = profile.name if profile else ""

            # Check session name or command for "claude"
            if "claude" in name.lower():
                return True

            # Alternative: Check the session's title/name
            session_title = session.name or ""
            if "claude" in session_title.lower():
                return True

            # Could also check running process, but this requires more setup
            return False
        except asyncio.TimeoutError:
            self._logger.debug("Timeout checking session profile")
            return False
        except Exception as e:
            self._logger.debug(f"Error checking session: {e}")
            return False

    async def get_session_positions(self, tab: iterm2.Tab) -> List[SessionPosition]:
        """Get position information for all sessions in a tab.

        Args:
            tab: Tab to analyze

        Returns:
            List of SessionPosition objects
        """
        root = tab.root
        return self._position_detector.compute_positions(root)

    async def find_session_by_position(
        self,
        tab: iterm2.Tab,
        position: WindowPosition,
    ) -> Optional[iterm2.Session]:
        """Find session at the specified position in a tab.

        Args:
            tab: Tab to search in
            position: Target position

        Returns:
            Session at position or None
        """
        positions = await self.get_session_positions(tab)
        return self._position_detector.find_session_by_position(positions, position)

    async def activate_session(self, session: iterm2.Session) -> None:
        """Bring a session to focus.

        Args:
            session: Session to activate
        """
        try:
            await asyncio.wait_for(session.async_activate(), timeout=1.0)
            self._logger.info(f"Activated session: {session.session_id}")
        except asyncio.TimeoutError:
            self._logger.warning("Timeout activating session")
        except Exception as e:
            self._logger.error(f"Failed to activate session: {e}")
            raise

    async def send_text(self, session: iterm2.Session, text: str) -> None:
        """Send text to a session as if typed.

        Args:
            session: Target session
            text: Text to send
        """
        try:
            await asyncio.wait_for(session.async_send_text(text), timeout=2.0)
            self._logger.debug(f"Sent text to session {session.session_id}: {text[:50]}...")
        except asyncio.TimeoutError:
            self._logger.warning("Timeout sending text to session")
        except Exception as e:
            self._logger.error(f"Failed to send text: {e}")
            raise

    async def send_text_with_newline(self, session: iterm2.Session, text: str) -> None:
        """Send text followed by Enter key press (submit).

        Args:
            session: Target session
            text: Text to send
        """
        # Use \r (carriage return) which is what the Enter key sends in terminals
        await self.send_text(session, text + "\r")

    async def is_single_pane(self, tab: iterm2.Tab) -> bool:
        """Check if tab has only one pane.

        Args:
            tab: Tab to check

        Returns:
            True if tab has only one session
        """
        return len(tab.sessions) == 1

    async def get_session_count(self, tab: iterm2.Tab) -> int:
        """Get number of sessions in a tab.

        Args:
            tab: Tab to count sessions in

        Returns:
            Number of sessions
        """
        return len(tab.sessions)

    @property
    def is_connected(self) -> bool:
        """Check if connected to iTerm2."""
        return self._connected


async def run_with_iterm(
    callback: Callable[[ITermController], None],
) -> None:
    """Run a callback function with an iTerm2 connection.

    This is useful for running scripts that need iTerm2 access.

    Args:
        callback: Async function to run with controller
    """
    controller = ITermController()
    try:
        await controller.connect()
        await callback(controller)
    finally:
        await controller.disconnect()
