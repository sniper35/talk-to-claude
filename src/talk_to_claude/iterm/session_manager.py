"""Session manager for tracking Claude Code sessions."""

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

import iterm2

from ..transcription.command_parser import WindowPosition
from ..utils.logger import get_logger
from .controller import ITermController
from .position_detector import SessionPosition


@dataclass
class ManagedSession:
    """A managed Claude Code session with metadata."""

    session: iterm2.Session
    tab: iterm2.Tab
    position: Optional[SessionPosition] = None
    is_active: bool = False


class SessionManager:
    """Manages Claude Code sessions across iTerm2."""

    def __init__(self, controller: ITermController):
        """Initialize session manager.

        Args:
            controller: iTerm2 controller instance
        """
        self._controller = controller
        self._sessions: Dict[str, ManagedSession] = {}
        self._active_session_id: Optional[str] = None
        self._logger = get_logger("iterm.session_manager")

    async def refresh_sessions(self) -> None:
        """Scan for Claude Code sessions across all tabs."""
        if not self._controller.is_connected:
            self._logger.warning("Controller not connected, cannot refresh sessions")
            return

        # Get all Claude sessions
        claude_sessions = await self._controller.get_claude_sessions()

        # Update our session tracking
        current_ids = set()
        for session in claude_sessions:
            session_id = session.session_id
            current_ids.add(session_id)

            if session_id not in self._sessions:
                # Find the tab containing this session
                tab = await self._find_session_tab(session)
                if tab:
                    self._sessions[session_id] = ManagedSession(
                        session=session,
                        tab=tab,
                    )
                    self._logger.info(f"Registered new Claude session: {session_id}")

        # Remove sessions that no longer exist
        removed = set(self._sessions.keys()) - current_ids
        for session_id in removed:
            del self._sessions[session_id]
            self._logger.info(f"Removed Claude session: {session_id}")
            if self._active_session_id == session_id:
                self._active_session_id = None

        # Update positions for all sessions
        await self._update_positions()

    async def _find_session_tab(self, session: iterm2.Session) -> Optional[iterm2.Tab]:
        """Find the tab containing a session.

        Args:
            session: Session to find tab for

        Returns:
            Tab containing the session or None
        """
        app = await iterm2.async_get_app(self._controller._connection)
        for window in app.windows:
            for tab in window.tabs:
                if session in tab.sessions:
                    return tab
        return None

    async def _update_positions(self) -> None:
        """Update position information for all managed sessions."""
        # Group sessions by tab
        tabs: Dict[str, List[ManagedSession]] = {}
        for managed in self._sessions.values():
            tab_id = managed.tab.tab_id
            if tab_id not in tabs:
                tabs[tab_id] = []
            tabs[tab_id].append(managed)

        # Update positions for each tab
        for tab_id, managed_sessions in tabs.items():
            if managed_sessions:
                tab = managed_sessions[0].tab
                positions = await self._controller.get_session_positions(tab)

                # Map positions to managed sessions
                for pos in positions:
                    for managed in managed_sessions:
                        if managed.session.session_id == pos.session.session_id:
                            managed.position = pos
                            break

    async def get_session_for_position(
        self,
        position: WindowPosition,
    ) -> Optional[iterm2.Session]:
        """Find session at the specified position in the current tab.

        Args:
            position: Target position

        Returns:
            Session at position or None
        """
        # Get current tab (don't refresh every time for performance)
        tab = await self._controller.get_current_tab()
        if not tab:
            return None

        return await self._controller.find_session_by_position(tab, position)

    async def get_active_session(self) -> Optional[iterm2.Session]:
        """Get the currently active/focused Claude Code session.

        Always checks the currently focused pane first to ensure text
        goes to the pane the user is looking at.

        Returns:
            Active session or None
        """
        # Always check current focused session first (not cached)
        tab = await self._controller.get_current_tab()
        if tab:
            current = tab.current_session
            if current and current.session_id in self._sessions:
                self._active_session_id = current.session_id
                return current

        # Fall back to cached session if focus check failed
        if self._active_session_id and self._active_session_id in self._sessions:
            return self._sessions[self._active_session_id].session

        # Fall back to single session if only one exists
        if len(self._sessions) == 1:
            session = list(self._sessions.values())[0].session
            self._active_session_id = session.session_id
            return session

        return None

    async def set_active_session(self, session: iterm2.Session) -> None:
        """Set a session as active and focus it.

        Args:
            session: Session to activate
        """
        await self._controller.activate_session(session)
        self._active_session_id = session.session_id

        # Update active flag
        for sid, managed in self._sessions.items():
            managed.is_active = (sid == session.session_id)

    def get_session_count(self) -> int:
        """Get count of managed Claude Code sessions.

        Returns:
            Number of managed sessions
        """
        return len(self._sessions)

    def is_single_session(self) -> bool:
        """Check if there's only one Claude Code session.

        Returns:
            True if exactly one session exists
        """
        return len(self._sessions) == 1

    def get_all_sessions(self) -> List[iterm2.Session]:
        """Get all managed sessions.

        Returns:
            List of all Claude Code sessions
        """
        return [m.session for m in self._sessions.values()]

    async def send_text_to_active(self, text: str) -> bool:
        """Send text to the active session.

        Args:
            text: Text to send

        Returns:
            True if text was sent successfully
        """
        session = await self.get_active_session()
        if not session:
            self._logger.warning("No active session to send text to")
            return False

        await self._controller.send_text(session, text)
        return True

    async def submit_to_active(self, text: str) -> bool:
        """Send text with newline (submit) to the active session.

        Args:
            text: Text to submit

        Returns:
            True if text was submitted successfully
        """
        session = await self.get_active_session()
        if not session:
            self._logger.warning("No active session to submit to")
            return False

        await self._controller.send_text_with_newline(session, text)
        return True

    async def clear_current_line(self) -> bool:
        """Clear all current input in the active session.

        Sends Escape + Ctrl+C to cancel any multi-line input,
        then Ctrl+U to clear the current line.

        Returns:
            True if command was sent successfully
        """
        session = await self.get_active_session()
        if not session:
            self._logger.warning("No active session to clear line in")
            return False

        # Send Escape (exit any mode) + Ctrl+C (cancel) + Ctrl+U (clear line)
        # Escape = \x1b, Ctrl+C = \x03, Ctrl+U = \x15
        await self._controller.send_text(session, "\x1b\x03\x15")
        return True
