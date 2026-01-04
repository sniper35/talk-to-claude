"""Live transcript overlay using subprocess for macOS compatibility."""

import json
import multiprocessing
import os
import queue
import threading
from pathlib import Path
from typing import Optional

from ..utils.logger import get_logger


# Settings file path
SETTINGS_DIR = Path.home() / ".talk-to-claude"
SETTINGS_FILE = SETTINGS_DIR / "overlay_settings.json"

# Default overlay settings
DEFAULT_SETTINGS = {
    "x": None,  # None means use position preset
    "y": None,
    "width": 400,
    "height": 60,
    "opacity": 0.8,
}


def _load_settings() -> dict:
    """Load overlay settings from disk."""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                # Merge with defaults to handle missing keys
                settings = DEFAULT_SETTINGS.copy()
                settings.update(saved)
                return settings
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()


def _save_settings(settings: dict) -> None:
    """Save overlay settings to disk."""
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


def _overlay_process(
    cmd_queue: multiprocessing.Queue,
    position: str,
    width: int,
    height: int,
    font_size: int,
    default_opacity: float,
    min_width: int,
    min_height: int,
    remember_position: bool,
):
    """Run the overlay in a separate process where we control the main thread.

    This runs in a subprocess, allowing NSWindow to be created on the main thread.
    """
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    from AppKit import (
        NSApplication,
        NSColor,
        NSFont,
        NSMakeRect,
        NSScreen,
        NSTextField,
        NSWindow,
        NSWindowStyleMaskBorderless,
        NSStatusWindowLevel,
        NSRunLoop,
        NSDate,
        NSView,
        NSCursor,
        NSEvent,
        NSLeftMouseDown,
        NSLeftMouseUp,
        NSLeftMouseDragged,
        NSScrollWheel,
    )
    from Foundation import NSPoint, NSSize

    POSITIONS = {
        "top-left": (20, -80),
        "top-right": (-420, -80),
        "bottom-left": (20, 80),
        "bottom-right": (-420, 80),
    }

    # Load saved settings
    saved_settings = _load_settings() if remember_position else DEFAULT_SETTINGS.copy()

    # Current state
    current_opacity = saved_settings.get("opacity", default_opacity)

    # Initialize application
    app = NSApplication.sharedApplication()

    # Get screen dimensions
    screen = NSScreen.mainScreen()
    screen_frame = screen.frame()

    # Determine initial position
    if remember_position and saved_settings.get("x") is not None and saved_settings.get("y") is not None:
        # Use saved position
        x = saved_settings["x"]
        y = saved_settings["y"]
        width = saved_settings.get("width", width)
        height = saved_settings.get("height", height)
    else:
        # Calculate window position from preset
        x_offset, y_offset = POSITIONS.get(position, POSITIONS["top-right"])

        if x_offset < 0:
            x = screen_frame.size.width + x_offset
        else:
            x = x_offset

        if y_offset < 0:
            y = screen_frame.size.height + y_offset
        else:
            y = y_offset

    # Skip custom view for resize handle - use simple NSView instead
    # The resize functionality still works via mouse event handling

    # Create window
    rect = NSMakeRect(x, y, width, height)
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect,
        NSWindowStyleMaskBorderless,
        2,  # NSBackingStoreBuffered
        False,
    )

    # Configure window
    window.setLevel_(NSStatusWindowLevel)
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, current_opacity))
    window.setHasShadow_(True)
    window.setCollectionBehavior_(1 << 6)  # NSWindowCollectionBehaviorCanJoinAllSpaces

    # Make window draggable by background and allow mouse events
    window.setMovableByWindowBackground_(True)
    window.setIgnoresMouseEvents_(False)

    # Set minimum and maximum size constraints
    window.setMinSize_(NSSize(min_width, min_height))
    window.setMaxSize_(NSSize(screen_frame.size.width, screen_frame.size.height / 2))

    # Create content view with rounded corners
    content_view = window.contentView()
    content_view.setWantsLayer_(True)
    content_view.layer().setCornerRadius_(10)

    # Create text field
    text_rect = NSMakeRect(15, 10, width - 50, height - 20)  # Leave space for resize handle
    text_field = NSTextField.alloc().initWithFrame_(text_rect)
    text_field.setBezeled_(False)
    text_field.setDrawsBackground_(False)
    text_field.setEditable_(False)
    text_field.setSelectable_(False)
    text_field.setTextColor_(NSColor.cyanColor())
    text_field.setFont_(NSFont.systemFontOfSize_(font_size))
    text_field.setStringValue_("Listening...")

    content_view.addSubview_(text_field)

    # Create simple resize handle view in bottom-right corner
    # Using standard NSView - the grip is indicated by cursor change on hover
    resize_handle = NSView.alloc().initWithFrame_(NSMakeRect(width - 20, 0, 20, 20))
    content_view.addSubview_(resize_handle)

    # Show window
    window.orderFrontRegardless()

    # Track resize state
    is_resizing = False
    resize_start_point = None
    resize_start_size = None

    def save_current_settings():
        """Save current window settings."""
        if remember_position:
            frame = window.frame()
            settings = {
                "x": frame.origin.x,
                "y": frame.origin.y,
                "width": frame.size.width,
                "height": frame.size.height,
                "opacity": current_opacity,
            }
            _save_settings(settings)

    def update_text_field_frame():
        """Update text field frame when window is resized."""
        frame = window.frame()
        text_field.setFrame_(NSMakeRect(15, 10, frame.size.width - 50, frame.size.height - 20))
        # Update resize handle position
        resize_handle.setFrame_(NSMakeRect(frame.size.width - 20, 0, 20, 20))

    def point_in_resize_zone(point, frame):
        """Check if point is in the resize zone (bottom-right corner)."""
        resize_zone_size = 20
        return (point.x >= frame.size.width - resize_zone_size and
                point.y <= resize_zone_size)

    def handle_scroll_event(event):
        """Handle scroll wheel event to adjust opacity."""
        nonlocal current_opacity

        # Get scroll delta (positive = scroll up = more opaque)
        delta = event.scrollingDeltaY()

        # Adjust opacity (0.05 per scroll unit)
        new_opacity = current_opacity + (delta * 0.02)
        new_opacity = max(0.3, min(1.0, new_opacity))  # Clamp between 0.3 and 1.0

        if new_opacity != current_opacity:
            current_opacity = new_opacity
            window.setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, current_opacity)
            )
            save_current_settings()

    # Run loop with manual polling
    run_loop = NSRunLoop.currentRunLoop()
    running = True

    # Track window movement for saving
    last_frame = window.frame()

    while running:
        # Process pending UI events (0.2s polling - reduces CPU usage while staying responsive)
        run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))

        # Check for window movement/resize and save settings
        current_frame = window.frame()
        if (current_frame.origin.x != last_frame.origin.x or
            current_frame.origin.y != last_frame.origin.y or
            current_frame.size.width != last_frame.size.width or
            current_frame.size.height != last_frame.size.height):
            update_text_field_frame()
            save_current_settings()
            last_frame = current_frame

        # Handle mouse events for resizing (check without blocking, already waited above)
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            (1 << NSLeftMouseDown) | (1 << NSLeftMouseUp) | (1 << NSLeftMouseDragged) | (1 << NSScrollWheel),
            None,  # Don't wait, just check for pending events
            "NSDefaultRunLoopMode",
            True
        )

        if event:
            event_type = event.type()

            if event_type == NSScrollWheel:
                # Check if scroll is over our window
                mouse_location = NSEvent.mouseLocation()
                window_frame = window.frame()
                if (window_frame.origin.x <= mouse_location.x <= window_frame.origin.x + window_frame.size.width and
                    window_frame.origin.y <= mouse_location.y <= window_frame.origin.y + window_frame.size.height):
                    handle_scroll_event(event)

            elif event_type == NSLeftMouseDown:
                # Check if click is in resize zone
                location = event.locationInWindow()
                frame = window.frame()
                if point_in_resize_zone(location, frame):
                    is_resizing = True
                    resize_start_point = NSEvent.mouseLocation()
                    resize_start_size = (frame.size.width, frame.size.height)
                    NSCursor.resizeDiagonalCursor().push()
                else:
                    # Let the window handle normal dragging
                    app.sendEvent_(event)

            elif event_type == NSLeftMouseDragged:
                if is_resizing and resize_start_point and resize_start_size:
                    current_point = NSEvent.mouseLocation()
                    delta_x = current_point.x - resize_start_point.x
                    delta_y = resize_start_point.y - current_point.y  # Invert Y for bottom-right resize

                    new_width = max(min_width, resize_start_size[0] + delta_x)
                    new_height = max(min_height, resize_start_size[1] + delta_y)

                    # Get current origin and adjust for height change (keep top-left corner fixed)
                    current_frame = window.frame()
                    new_y = current_frame.origin.y + current_frame.size.height - new_height

                    window.setFrame_display_(
                        NSMakeRect(current_frame.origin.x, new_y, new_width, new_height),
                        True
                    )
                else:
                    app.sendEvent_(event)

            elif event_type == NSLeftMouseUp:
                if is_resizing:
                    is_resizing = False
                    resize_start_point = None
                    resize_start_size = None
                    NSCursor.pop()
                    save_current_settings()
                else:
                    app.sendEvent_(event)

        # Check for commands
        try:
            while True:
                try:
                    cmd = cmd_queue.get_nowait()
                    if cmd["action"] == "stop":
                        running = False
                        break
                    elif cmd["action"] == "update":
                        text = cmd.get("text", "")
                        is_final = cmd.get("is_final", False)
                        if not is_final and text:
                            text = f"... {text}"
                        text_field.setStringValue_(text)
                        if is_final:
                            text_field.setTextColor_(NSColor.greenColor())
                        else:
                            text_field.setTextColor_(NSColor.whiteColor())
                    elif cmd["action"] == "listening":
                        if cmd.get("listening", False):
                            text_field.setStringValue_("Listening...")
                            text_field.setTextColor_(NSColor.cyanColor())
                        else:
                            text_field.setStringValue_("")
                    elif cmd["action"] == "clear":
                        text_field.setStringValue_("")
                    elif cmd["action"] == "show":
                        window.orderFrontRegardless()
                    elif cmd["action"] == "hide":
                        window.orderOut_(None)
                    elif cmd["action"] == "set_opacity":
                        new_opacity = cmd.get("opacity", default_opacity)
                        new_opacity = max(0.3, min(1.0, new_opacity))
                        current_opacity = new_opacity
                        window.setBackgroundColor_(
                            NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, current_opacity)
                        )
                        save_current_settings()
                except queue.Empty:
                    break
        except Exception:
            pass


class TranscriptOverlay:
    """Floating overlay window to display live transcription.

    Uses a subprocess to handle AppKit UI since NSWindow requires main thread.
    """

    def __init__(
        self,
        position: str = "top-right",
        width: int = 400,
        height: int = 60,
        font_size: int = 16,
        default_opacity: float = 0.8,
        min_width: int = 200,
        min_height: int = 40,
        remember_position: bool = True,
    ):
        """Initialize transcript overlay.

        Args:
            position: Default position preset (top-left, top-right, bottom-left, bottom-right)
            width: Default window width
            height: Default window height
            font_size: Font size for transcript text
            default_opacity: Default window opacity (0.3-1.0)
            min_width: Minimum window width
            min_height: Minimum window height
            remember_position: Whether to persist window position/size/opacity
        """
        self.position = position
        self.width = width
        self.height = height
        self.font_size = font_size
        self.default_opacity = default_opacity
        self.min_width = min_width
        self.min_height = min_height
        self.remember_position = remember_position

        self._process: Optional[multiprocessing.Process] = None
        self._cmd_queue: Optional[multiprocessing.Queue] = None
        self._running = False
        self._logger = get_logger("ui.overlay")
        self._current_text = ""
        self._is_listening = False

    def start(self) -> None:
        """Start the overlay in a subprocess."""
        if self._running:
            self._logger.warning("Overlay already running")
            return

        try:
            # Use spawn for macOS compatibility (fork doesn't work with Objective-C)
            # Set PYTHONPATH to ensure subprocess finds venv packages
            import sys
            venv_site_packages = [p for p in sys.path if 'site-packages' in p]
            if venv_site_packages:
                current_pythonpath = os.environ.get('PYTHONPATH', '')
                new_pythonpath = ':'.join(venv_site_packages)
                if current_pythonpath:
                    new_pythonpath = f"{new_pythonpath}:{current_pythonpath}"
                os.environ['PYTHONPATH'] = new_pythonpath

            ctx = multiprocessing.get_context('spawn')
            self._cmd_queue = ctx.Queue()
            self._process = ctx.Process(
                target=_overlay_process,
                args=(
                    self._cmd_queue,
                    self.position,
                    self.width,
                    self.height,
                    self.font_size,
                    self.default_opacity,
                    self.min_width,
                    self.min_height,
                    self.remember_position,
                ),
                daemon=True,
            )
            self._process.start()
            self._running = True
            self._logger.info("Transcript overlay started (subprocess)")
        except Exception as e:
            self._logger.error(f"Failed to start overlay: {e}")

    def stop(self) -> None:
        """Stop the overlay."""
        if not self._running:
            return

        self._running = False

        try:
            if self._cmd_queue:
                self._cmd_queue.put({"action": "stop"})
            if self._process:
                self._process.join(timeout=1.0)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=0.5)
                if self._process.is_alive():
                    self._process.kill()  # Force kill if still alive
                self._process = None
        except Exception as e:
            self._logger.debug(f"Error stopping overlay: {e}")

        self._logger.info("Transcript overlay stopped")

    def update_text(self, text: str, is_final: bool = False) -> None:
        """Update the displayed transcript text."""
        self._current_text = text
        if self._cmd_queue and self._running:
            try:
                self._cmd_queue.put_nowait({"action": "update", "text": text, "is_final": is_final})
            except Exception:
                pass

    def set_listening(self, listening: bool) -> None:
        """Set listening state indicator."""
        self._is_listening = listening
        if self._cmd_queue and self._running and not self._current_text:
            try:
                self._cmd_queue.put_nowait({"action": "listening", "listening": listening})
            except Exception:
                pass

    def clear(self) -> None:
        """Clear the displayed text."""
        self._current_text = ""
        if self._cmd_queue and self._running:
            try:
                self._cmd_queue.put_nowait({"action": "clear"})
            except Exception:
                pass

    def show(self) -> None:
        """Show the overlay window."""
        if self._cmd_queue and self._running:
            try:
                self._cmd_queue.put_nowait({"action": "show"})
            except Exception:
                pass

    def hide(self) -> None:
        """Hide the overlay window."""
        if self._cmd_queue and self._running:
            try:
                self._cmd_queue.put_nowait({"action": "hide"})
            except Exception:
                pass

    def set_opacity(self, opacity: float) -> None:
        """Set the window background opacity.

        Args:
            opacity: Opacity value between 0.3 (very transparent) and 1.0 (fully opaque)
        """
        if self._cmd_queue and self._running:
            try:
                self._cmd_queue.put_nowait({"action": "set_opacity", "opacity": opacity})
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        """Check if overlay is running."""
        return self._running
