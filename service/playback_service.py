#!/usr/bin/env python3
"""
Playback Service - Encapsulates AudioPlayer with PyQt Signals
Provides thread-safe interface for playback control
"""

from typing import Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

# Import from core layer
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.player import AudioPlayer, PlayerState


class PlaybackService(QObject):
    """
    Playback service wrapping AudioPlayer with PyQt signals.
    All signals are emitted from the main thread, ensuring thread safety.
    """

    # Signals for state changes (thread-safe)
    state_changed = pyqtSignal(object)       # PlayerState
    position_changed = pyqtSignal(float)     # position in seconds
    duration_changed = pyqtSignal(float)     # duration in seconds
    track_changed = pyqtSignal(object)       # Track object
    track_ended = pyqtSignal()               # emitted when track finishes
    volume_changed = pyqtSignal(float)       # volume level 0.0-1.0
    error_occurred = pyqtSignal(str)         # error message

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # Create the core AudioPlayer
        self._player = AudioPlayer()

        # Set up callback for track end
        self._player.set_track_end_callback(self._on_track_end)

        # Register state change callback
        self._player._state_machine.add_callback(self._on_state_change)

        # Track info cache
        self._current_position: float = 0.0
        self._current_duration: float = 0.0

    def _on_track_end(self) -> None:
        """Called when track ends - emit signal from main thread."""
        self.track_ended.emit()

    def _on_state_change(self, old_state: PlayerState, new_state: PlayerState) -> None:
        """Called when player state changes."""
        self.state_changed.emit(new_state)

    # === Public API ===

    def play(self, filepath: str) -> bool:
        """
        Play a file.

        Args:
            filepath: Path to the audio file

        Returns:
            True if playback started successfully
        """
        try:
            result = self._player.play_file(filepath)
            if result and self._player.current_track:
                self.track_changed.emit(self._player.current_track)
                duration = self._player.get_duration()
                if duration > 0:
                    self.duration_changed.emit(duration)
            return result
        except Exception as e:
            self.error_occurred.emit(str(e))
            return False

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()

    def resume(self) -> None:
        """Resume playback."""
        self._player.resume()

    def stop(self) -> None:
        """Stop playback."""
        self._player.stop()
        self.track_changed.emit(None)

    def toggle_play_pause(self) -> bool:
        """
        Toggle between play and pause.

        Returns:
            True if now playing, False if now paused
        """
        if self._player.is_paused:
            self._player.resume()
            return True
        elif self._player.is_playing:
            self._player.pause()
            return False
        return False

    def seek(self, position_seconds: float) -> bool:
        """
        Seek to position.

        Args:
            position_seconds: Target position in seconds

        Returns:
            True if seek was successful
        """
        return self._player.seek(position_seconds)

    def set_volume(self, level: float) -> None:
        """
        Set volume level.

        Args:
            level: Volume level 0.0-1.0
        """
        level = max(0.0, min(1.0, level))
        self._player.set_volume(level)
        self.volume_changed.emit(level)

    def get_volume(self) -> float:
        """Get current volume level (0.0-1.0)."""
        return self._player.get_volume()

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        return self._player.get_position()

    def get_duration(self) -> float:
        """Get current track duration in seconds."""
        return self._player.get_duration()

    def get_state(self) -> PlayerState:
        """Get current player state."""
        return self._player.state

    @property
    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._player.is_playing

    @property
    def is_paused(self) -> bool:
        """Check if paused."""
        return self._player.is_paused

    @property
    def current_track(self) -> Optional[object]:
        """Get current track."""
        return self._player.current_track

    @property
    def audio_player(self) -> AudioPlayer:
        """Direct access to AudioPlayer for advanced use."""
        return self._player

    # === Queue Management ===

    def register_library_queue(self, library_id: str, queue: object) -> None:
        """Register a playback queue for a library."""
        self._player.register_library_queue(library_id, queue)

    def unregister_library_queue(self, library_id: str) -> bool:
        """Unregister a playback queue."""
        return self._player.unregister_library_queue(library_id)

    def play_from_queue(self, library_id: str, position_index: Optional[int] = None) -> bool:
        """Play from a registered queue."""
        return self._player.play_from_queue(library_id, position_index)

    def next_track_in_queue(self, library_id: str, loop_mode: str = "OFF") -> bool:
        """Advance to next track in queue."""
        return self._player.next_track_in_queue(library_id, loop_mode)

    def prev_track_in_queue(self, library_id: str) -> bool:
        """Go to previous track in queue."""
        return self._player.prev_track_in_queue(library_id)
