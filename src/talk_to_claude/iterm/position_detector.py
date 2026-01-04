"""Position detection for iTerm2 split panes."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Union

import iterm2

from ..transcription.command_parser import HorizontalPosition, VerticalPosition, WindowPosition
from ..utils.logger import get_logger


@dataclass
class SessionPosition:
    """Position information for a session in the split layout."""

    session: iterm2.Session
    horizontal: HorizontalPosition
    vertical: VerticalPosition
    row: int  # 0-indexed row position
    col: int  # 0-indexed column position

    @property
    def window_position(self) -> WindowPosition:
        """Convert to WindowPosition for matching."""
        return WindowPosition(horizontal=self.horizontal, vertical=self.vertical)


class PositionDetector:
    """Detects positions of sessions in iTerm2 split pane layouts."""

    def __init__(self):
        self._logger = get_logger("iterm.position")

    def compute_positions(
        self,
        root: Union[iterm2.Splitter, iterm2.Session],
    ) -> List[SessionPosition]:
        """Compute positions for all sessions in a split layout.

        Args:
            root: Root splitter or session from tab.root

        Returns:
            List of SessionPosition objects
        """
        if isinstance(root, iterm2.Session):
            # Single session, no splits
            return [
                SessionPosition(
                    session=root,
                    horizontal=HorizontalPosition.CENTER,
                    vertical=VerticalPosition.MIDDLE,
                    row=0,
                    col=0,
                )
            ]

        # Build grid representation
        grid = self._build_grid(root)
        return self._grid_to_positions(grid)

    def _build_grid(
        self,
        splitter: iterm2.Splitter,
        row_start: int = 0,
        col_start: int = 0,
    ) -> List[List[Optional[iterm2.Session]]]:
        """Recursively build a grid representation of the split layout.

        Args:
            splitter: Splitter to process
            row_start: Starting row index
            col_start: Starting column index

        Returns:
            2D grid of sessions
        """
        children = splitter.children
        is_vertical = splitter.vertical  # True = children arranged left to right

        if is_vertical:
            # Horizontal split: children are columns
            grids = []
            for child in children:
                if isinstance(child, iterm2.Session):
                    grids.append([[child]])
                else:
                    grids.append(self._build_grid(child))

            # Merge horizontally: each child becomes a column
            return self._merge_horizontal(grids)
        else:
            # Vertical split: children are rows
            grids = []
            for child in children:
                if isinstance(child, iterm2.Session):
                    grids.append([[child]])
                else:
                    grids.append(self._build_grid(child))

            # Merge vertically: stack rows
            return self._merge_vertical(grids)

    def _merge_horizontal(
        self, grids: List[List[List[Optional[iterm2.Session]]]]
    ) -> List[List[Optional[iterm2.Session]]]:
        """Merge grids horizontally (side by side)."""
        if not grids:
            return []

        # Find maximum number of rows across all grids
        max_rows = max(len(g) for g in grids)

        result = []
        for row_idx in range(max_rows):
            row = []
            for grid in grids:
                if row_idx < len(grid):
                    row.extend(grid[row_idx])
                else:
                    # Pad with None if this grid doesn't have this row
                    cols = len(grid[0]) if grid else 1
                    row.extend([None] * cols)
            result.append(row)

        return result

    def _merge_vertical(
        self, grids: List[List[List[Optional[iterm2.Session]]]]
    ) -> List[List[Optional[iterm2.Session]]]:
        """Merge grids vertically (stacked)."""
        if not grids:
            return []

        # Find maximum number of columns across all grids
        max_cols = max(len(g[0]) if g else 1 for g in grids)

        result = []
        for grid in grids:
            for row in grid:
                # Pad row to max_cols if needed
                padded_row = row + [None] * (max_cols - len(row))
                result.append(padded_row)

        return result

    def _grid_to_positions(
        self, grid: List[List[Optional[iterm2.Session]]]
    ) -> List[SessionPosition]:
        """Convert grid representation to SessionPosition list.

        Args:
            grid: 2D grid of sessions

        Returns:
            List of SessionPosition objects
        """
        if not grid or not grid[0]:
            return []

        num_rows = len(grid)
        num_cols = len(grid[0])

        positions = []
        seen_sessions = set()

        for row_idx, row in enumerate(grid):
            for col_idx, session in enumerate(row):
                if session is None:
                    continue
                if session.session_id in seen_sessions:
                    continue
                seen_sessions.add(session.session_id)

                # Determine horizontal position
                if num_cols == 1:
                    h_pos = HorizontalPosition.CENTER
                elif col_idx == 0:
                    h_pos = HorizontalPosition.LEFT
                elif col_idx == num_cols - 1:
                    h_pos = HorizontalPosition.RIGHT
                else:
                    h_pos = HorizontalPosition.CENTER

                # Determine vertical position
                if num_rows == 1:
                    v_pos = VerticalPosition.MIDDLE
                elif row_idx == 0:
                    v_pos = VerticalPosition.UPPER
                elif row_idx == num_rows - 1:
                    v_pos = VerticalPosition.LOWER
                else:
                    v_pos = VerticalPosition.MIDDLE

                positions.append(
                    SessionPosition(
                        session=session,
                        horizontal=h_pos,
                        vertical=v_pos,
                        row=row_idx,
                        col=col_idx,
                    )
                )

        return positions

    def find_session_by_position(
        self,
        positions: List[SessionPosition],
        target: WindowPosition,
    ) -> Optional[iterm2.Session]:
        """Find session matching the target position.

        Args:
            positions: List of session positions
            target: Target position to find

        Returns:
            Matching session or None
        """
        # First try exact match
        for pos in positions:
            if (pos.horizontal == target.horizontal and
                pos.vertical == target.vertical):
                return pos.session

        # Try partial matches (e.g., just horizontal or just vertical)
        # Prioritize horizontal match if vertical is CENTER/MIDDLE
        if target.vertical == VerticalPosition.MIDDLE:
            for pos in positions:
                if pos.horizontal == target.horizontal:
                    return pos.session

        # Prioritize vertical match if horizontal is CENTER
        if target.horizontal == HorizontalPosition.CENTER:
            for pos in positions:
                if pos.vertical == target.vertical:
                    return pos.session

        self._logger.warning(f"No session found for position: {target}")
        return None
