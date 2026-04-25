#!/usr/bin/env python3
"""
Music player core module
Supported formats: MP3, WAV, FLAC, OGG, M4A, AAC and other common audio formats
Uses soundfile + sounddevice + numpy for universal format support and precise seeking
"""
import sys
import threading
import time
import math
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

import cv2
import numpy as np
import soundfile as sf
import sounddevice as sd

from . import i18n
from .library_manager import Track


class PlayerState(Enum):
    """播放器状态枚举"""
    IDLE = auto()        # 空闲
    LOADING = auto()     # 加载中
    PLAYING = auto()     # 播放中
    PAUSED = auto()      # 已暂停
    STOPPING = auto()    # 停止中
    ERROR = auto()       # 错误


class PlayerStateMachine:
    """线程安全的播放器状态机"""

    # 合法状态转换映射
    VALID_TRANSITIONS = {
        PlayerState.IDLE: {PlayerState.LOADING, PlayerState.ERROR},
        PlayerState.LOADING: {PlayerState.PLAYING, PlayerState.ERROR, PlayerState.IDLE},
        PlayerState.PLAYING: {PlayerState.PAUSED, PlayerState.STOPPING, PlayerState.IDLE, PlayerState.ERROR},
        PlayerState.PAUSED: {PlayerState.PLAYING, PlayerState.STOPPING, PlayerState.IDLE},
        PlayerState.STOPPING: {PlayerState.IDLE, PlayerState.ERROR},
        PlayerState.ERROR: {PlayerState.IDLE, PlayerState.LOADING},
    }

    def __init__(self):
        self._state = PlayerState.IDLE
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[PlayerState, PlayerState], None]] = []

    @property
    def state(self) -> PlayerState:
        """获取当前状态"""
        with self._lock:
            return self._state

    def can_transition_to(self, new_state: PlayerState) -> bool:
        """检查是否可以转换到新状态"""
        with self._lock:
            return new_state in self.VALID_TRANSITIONS.get(self._state, set())

    def transition_to(self, new_state: PlayerState) -> bool:
        """尝试转换到新状态，返回是否成功"""
        with self._lock:
            if not self.can_transition_to(new_state):
                return False
            old_state = self._state
            self._state = new_state
            # 触发回调
            for callback in self._callbacks:
                try:
                    callback(old_state, new_state)
                except Exception as e:
                    print(f"State change callback error: {e}")
            return True

    def force_transition(self, new_state: PlayerState) -> None:
        """强制转换状态（用于错误恢复等特殊情况）"""
        with self._lock:
            old_state = self._state
            self._state = new_state
            for callback in self._callbacks:
                try:
                    callback(old_state, new_state)
                except Exception as e:
                    print(f"State change callback error: {e}")

    def add_callback(self, callback: Callable[[PlayerState, PlayerState], None]) -> None:
        """添加状态变化回调"""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[PlayerState, PlayerState], None]) -> None:
        """移除状态变化回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    # 向后兼容属性
    @property
    def is_playing(self) -> bool:
        return self._state == PlayerState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self._state == PlayerState.PAUSED


class AudioPlayer:
    """Audio player using soundfile + sounddevice for universal format support and precise seeking.

    Features:
    - All formats support seeking (MP3, WAV, FLAC, OGG, M4A, AAC, etc.)
    - Precise position tracking using sample indices
    - Volume control via numpy array operations
    - Chunked loading for large files

    Extended with per-library queue support for independent playback state management.
    """

    # Chunk loading configuration for large files
    CHUNK_DURATION_SEC = 60.0  # 60 seconds per chunk
    LARGE_FILE_THRESHOLD_MB = 50
    LARGE_FILE_THRESHOLD_MINUTES = 30

    def __init__(self):
        # State machine for thread-safe state management
        self._state_machine = PlayerStateMachine()

        # Track end callback support
        self._on_track_end_callback: Optional[Callable] = None

        # Audio data (numpy array)
        self._audio_data: Optional[np.ndarray] = None
        self._sample_rate: int = 44100
        self._channels: int = 2

        # Position tracking (in samples)
        self._position_samples: int = 0
        self._total_samples: int = 0

        # Timing for position calculation
        self._play_start_time: float = 0.0
        self._pause_position_samples: int = 0

        # Volume
        self._volume: float = 1.0

        # Thread control
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._playback_lock = threading.Lock()

        # Stream control
        self._current_stream: Optional[sd.OutputStream] = None

        # Chunk loading state
        self._use_chunked_loading = False
        self._current_chunk_index: int = 0
        self._total_chunks: int = 0
        self._filepath: Optional[str] = None

        # Double buffering for seamless chunk transitions
        self._chunk_buffer_lock = threading.Lock()
        self._next_chunk_data: Optional[np.ndarray] = None
        self._next_chunk_index: int = -1  # Index of the preloaded chunk (-1 = none)
        self._current_chunk_data: Optional[np.ndarray] = None  # Currently playing chunk
        self._current_chunk_index: int = -1  # Index of current chunk
        self._chunk_offset: int = 0  # Offset within the current chunk (for position tracking)

        # Current track and queue
        self.current_track: Optional[Track] = None
        self.queue: List[Track] = []

        # Per-library queue management
        self._library_queues: Dict[str, 'PlaybackQueueInfo'] = {}

    # Backward-compatible properties using state machine
    @property
    def is_playing(self) -> bool:
        return self._state_machine.is_playing

    @is_playing.setter
    def is_playing(self, value: bool) -> None:
        # For backward compatibility, allow setting but prefer state machine
        if value:
            self._state_machine.transition_to(PlayerState.PLAYING)
        elif self._state_machine.state == PlayerState.PLAYING:
            self._state_machine.transition_to(PlayerState.IDLE)

    @property
    def is_paused(self) -> bool:
        return self._state_machine.is_paused

    @is_paused.setter
    def is_paused(self, value: bool) -> None:
        if value:
            self._state_machine.transition_to(PlayerState.PAUSED)
        elif self._state_machine.state == PlayerState.PAUSED:
            self._state_machine.transition_to(PlayerState.PLAYING)

    @property
    def state(self) -> PlayerState:
        """Get current player state"""
        return self._state_machine.state

    def set_track_end_callback(self, callback: Callable) -> None:
        """Set the callback function for when a track ends playing."""
        self._on_track_end_callback = callback

    def clear_track_end_callback(self) -> None:
        """Clear the track end callback function."""
        self._on_track_end_callback = None

    def play_from_queue(self, library_id: str, position_index: Optional[int] = None) -> bool:
        """Play the current track from the specified queue."""
        if not self._library_queues.get(library_id):
            print(f"No queue found for library: {library_id}")
            return False

        queue_info = self._library_queues[library_id]
        playback_queue = queue_info['queue']
        current_index = position_index if position_index is not None else playback_queue.current_index

        if not (0 <= current_index < len(playback_queue.track_list)):
            print(f"Invalid position index: {current_index} for library {library_id}")
            return False

        track = playback_queue.track_list[current_index]
        return self.play_file(track.path)

    def next_track_in_queue(self, library_id: str, loop_mode: str = "OFF") -> bool:
        """Advance to the next track in the specified queue."""
        if not self._library_queues.get(library_id):
            print(f"No queue found for library: {library_id}")
            return False

        queue_info = self._library_queues[library_id]
        playback_queue = queue_info['queue']

        old_pos = playback_queue.current_index
        if loop_mode == "ALL" and playback_queue.current_index >= len(playback_queue.track_list) - 1:
            playback_queue.current_index = -1

        new_index = playback_queue.current_index + 1

        if loop_mode == "ALL":
            if not (0 <= new_index < len(playback_queue.track_list)):
                new_index = 0
        elif loop_mode != "ONE" and playback_queue.current_index < len(playback_queue.track_list) - 1:
            new_index = old_pos + 1

        if new_index != old_pos:
            playback_queue.position_state.record_position(new_index)

        track = playback_queue.track_list[new_index]
        return self.play_file(track.path)

    def prev_track_in_queue(self, library_id: str) -> bool:
        """Go back to the previous track in the specified queue."""
        if not self._library_queues.get(library_id):
            print(f"No queue found for library: {library_id}")
            return False

        queue_info = self._library_queues[library_id]
        playback_queue = queue_info['queue']

        old_pos = playback_queue.current_index
        new_index = max(0, old_pos - 1)

        if new_index != old_pos:
            playback_queue.position_state.record_position(new_index)

        track = playback_queue.track_list[new_index]
        return self.play_file(track.path)

    def register_library_queue(self, library_id: str, queue: 'PlaybackQueue') -> None:
        """Register/update media library queue info."""
        self._library_queues[library_id] = {
            'queue': queue,
            'registered_at': datetime.now() if isinstance(self, AudioPlayer) else None
        }

    def unregister_library_queue(self, library_id: str) -> bool:
        """Unregister media library queue."""
        if library_id in self._library_queues:
            del self._library_queues[library_id]
            return True
        return False

    # Core playback methods
    def _stop_playback_sync(self) -> None:
        """同步停止播放 - 确保在播放新文件前完全停止

        This method guarantees that all playback activity is stopped
        before returning, preventing concurrent audio playback.
        """
        # Signal stop to playback thread
        self._stop_event.set()
        self._pause_event.set()

        # Transition to STOPPING state
        self._state_machine.force_transition(PlayerState.STOPPING)

        # Stop sounddevice stream
        if self._current_stream:
            try:
                if self._current_stream.active:
                    self._current_stream.stop()
                self._current_stream.close()
            except Exception:
                pass
            self._current_stream = None

        # CRITICAL: Stop ALL sounddevice streams to prevent concurrent playback
        # This ensures any orphaned streams or buffered audio is stopped
        try:
            sd.stop()
        except Exception:
            pass

        # Wait for playback thread to finish with timeout
        # IMPORTANT: Check if we're NOT the playback thread itself to avoid RuntimeError
        if self._playback_thread and self._playback_thread.is_alive():
            current_thread = threading.current_thread()
            if self._playback_thread is not current_thread:
                self._playback_thread.join(timeout=2.0)
            # If we ARE the playback thread, just proceed - the thread will exit naturally

        self._playback_thread = None

        # Transition to IDLE state
        self._state_machine.force_transition(PlayerState.IDLE)

    def play_file(self, filepath: str) -> bool:
        """Play a single file using soundfile + sounddevice.

        Args:
            filepath: Path to the audio file

        Returns:
            True if playback started successfully, False otherwise
        """
        try:
            # Synchronously stop any current playback before loading new file
            self._stop_playback_sync()

            # Transition to LOADING state
            if not self._state_machine.transition_to(PlayerState.LOADING):
                print("Warning: Could not transition to LOADING state")

            # Load audio using soundfile
            # soundfile supports: WAV, FLAC, OGG, MP3 (with libsndfile >= 1.0.31)
            audio_data, sample_rate = sf.read(filepath, dtype='float32')

            # Ensure 2D array (samples, channels)
            if audio_data.ndim == 1:
                audio_data = audio_data.reshape(-1, 1)

            # Convert mono to stereo if needed
            if audio_data.shape[1] == 1:
                audio_data = np.column_stack([audio_data, audio_data])
            elif audio_data.shape[1] > 2:
                # Mix down to stereo (average channels)
                audio_data = audio_data[:, :2]

            # Store original audio data (volume applied dynamically in playback)
            with self._playback_lock:
                self._audio_data = audio_data
                self._sample_rate = sample_rate
                self._channels = audio_data.shape[1]
                self._total_samples = audio_data.shape[0]
                self._filepath = filepath

                # Determine chunked loading
                self._use_chunked_loading = self._is_large_file(filepath)
                self._current_chunk_index = 0
                self._total_chunks = int(math.ceil(self._total_samples / (self.CHUNK_DURATION_SEC * sample_rate)))

            # Extract metadata for track info
            from .metadata import extract_metadata
            metadata = extract_metadata(filepath)

            self.current_track = Track(
                path=filepath,
                title=metadata.title,
                artist=metadata.artist,
                album=metadata.album,
                duration=metadata.duration
            )

            # Reset position
            self._position_samples = 0
            self._pause_position_samples = 0

            # Start playback (this will transition to PLAYING)
            self._start_playback(from_sample=0)
            return True

        except Exception as e:
            print(i18n.console('console.play_failed', error=str(e)))
            import traceback
            traceback.print_exc()
            self._state_machine.force_transition(PlayerState.ERROR)
            return False

    def play_queue(self, files: List[str]) -> bool:
        """Play from queue."""
        try:
            if not files:
                return False
            self.queue = [Track(path=f, title=Path(f).name) for f in files]
            return self.play_file(files[0])
        except Exception as e:
            print(i18n.console('console.queue_failed', error=str(e)))
            return False

    def pause(self) -> None:
        """Pause playback."""
        if not self._state_machine.is_playing:
            return
        if self._state_machine.state == PlayerState.PAUSED:
            return

        # Set pause event FIRST to prevent race condition with playback worker
        self._pause_event.set()

        with self._playback_lock:
            # Record current position before pausing
            if self._current_stream and self._current_stream.active:
                elapsed_samples = int((time.time() - self._play_start_time) * self._sample_rate)
                self._pause_position_samples = self._position_samples + elapsed_samples
                self._current_stream.stop()
            else:
                self._pause_position_samples = self._position_samples

            self._state_machine.transition_to(PlayerState.PAUSED)

    def resume(self) -> None:
        """Resume playback from paused position."""
        if self._state_machine.state != PlayerState.PAUSED:
            return

        self._state_machine.transition_to(PlayerState.PLAYING)
        self._pause_event.clear()

        # Resume from paused position
        self._start_playback(from_sample=self._pause_position_samples)

    def stop(self) -> None:
        """Stop playback and clear state."""
        self._stop_playback_sync()
        with self._playback_lock:
            self.current_track = None
            self._audio_data = None
            self._filepath = None
            self._position_samples = 0
            self._pause_position_samples = 0
            self._total_samples = 0

    def set_volume(self, level: float) -> None:
        """Set volume, level range 0.0-1.0.

        Volume is applied dynamically during playback.
        """
        self._volume = max(0.0, min(1.0, level))

    def get_volume(self) -> float:
        """Get current volume level (0.0-1.0)."""
        return self._volume

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        if not self.is_playing or not self.current_track:
            return 0.0

        if self.is_paused:
            return self._pause_position_samples / self._sample_rate

        # For chunked playback, use directly updated position
        if self._use_chunked_loading:
            with self._playback_lock:
                return self._position_samples / self._sample_rate

        # For normal playback, calculate position from playback start time
        with self._playback_lock:
            if self._current_stream and self._current_stream.active:
                elapsed_samples = int((time.time() - self._play_start_time) * self._sample_rate)
                position_samples = self._position_samples + elapsed_samples
                return min(position_samples, self._total_samples) / self._sample_rate
            else:
                return self._position_samples / self._sample_rate

    def get_duration(self) -> float:
        """Get current track duration in seconds."""
        # Prefer actual decoded duration over metadata
        if self._sample_rate > 0 and self._total_samples > 0:
            return self._total_samples / self._sample_rate
        # Fallback to metadata if available
        if self.current_track and hasattr(self.current_track, 'duration'):
            return self.current_track.duration
        return 0.0

    def seek(self, position_seconds: float) -> bool:
        """Seek to a position in the current track.

        All formats support seeking with soundfile backend.

        Args:
            position_seconds: Target position in seconds

        Returns:
            True if seek was successful, False otherwise
        """
        if not self.is_playing or not self.current_track:
            return False

        try:
            # Clamp position to valid range
            duration = self.get_duration()
            position_seconds = max(0.0, min(position_seconds, duration))
            target_sample = int(position_seconds * self._sample_rate)

            was_paused = self.is_paused

            # Stop current playback
            if self._current_stream and self._current_stream.active:
                self._current_stream.stop()

            # Update position
            with self._playback_lock:
                self._position_samples = target_sample
                self._pause_position_samples = target_sample

            self._stop_event.set()
            # Wait for playback thread to finish
            if self._playback_thread and self._playback_thread.is_alive():
                self._playback_thread.join(timeout=1.0)
            self._stop_event.clear()

            # If was paused, stay paused at new position
            if was_paused:
                self.is_paused = True
                return True

            # Restart playback from new position
            self._start_playback(from_sample=target_sample)
            return True

        except Exception:
            return False

    def is_seekable(self) -> bool:
        """Check if current track supports seeking.

        All formats support seeking with soundfile backend.
        """
        return True

    def is_active(self) -> bool:
        """Check if audio is actively playing."""
        if not self.is_playing:
            return False
        if self.is_paused:
            return True
        if self._current_stream and self._current_stream.active:
            return True
        return self.is_playing

    # Internal playback methods

    def _is_large_file(self, filepath: str) -> bool:
        """Check if the file should use chunked loading."""
        try:
            file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
            if file_size_mb > self.LARGE_FILE_THRESHOLD_MB:
                return True
            duration_minutes = self._total_samples / (self._sample_rate * 60) if self._sample_rate > 0 else 0
            if duration_minutes > self.LARGE_FILE_THRESHOLD_MINUTES:
                return True
        except OSError:
            pass
        return False

    def _start_playback(self, from_sample: int = 0) -> None:
        """Start playback from a given sample position in a background thread."""
        # CRITICAL: Ensure any residual audio is stopped before starting new playback
        try:
            sd.stop()
            # Small delay to allow audio system to clean up
            time.sleep(0.05)
        except Exception:
            pass

        with self._playback_lock:
            self._position_samples = from_sample
            self._stop_event.clear()
            self._pause_event.clear()

        # Transition to PLAYING state
        self._state_machine.force_transition(PlayerState.PLAYING)

        # Choose playback strategy
        if self._use_chunked_loading:
            self._playback_thread = threading.Thread(
                target=self._playback_worker_chunked,
                args=(from_sample,),
                daemon=True
            )
        else:
            self._playback_thread = threading.Thread(
                target=self._playback_worker,
                args=(from_sample,),
                daemon=True
            )

        self._playback_thread.start()

    def _stop_playback(self) -> None:
        """Stop all playback activity."""
        self._stop_event.set()
        self._pause_event.set()

        # Clear chunk buffers
        with self._chunk_buffer_lock:
            self._next_chunk_data = None
            self._next_chunk_index = -1
        self._current_chunk_data = None
        self._current_chunk_index = -1

        # Stop sounddevice stream
        if self._current_stream:
            try:
                if self._current_stream.active:
                    self._current_stream.stop()
                self._current_stream.close()
            except Exception:
                pass
            self._current_stream = None

        # Wait for playback thread to finish
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=2.0)

        self._playback_thread = None
        self._state_machine.force_transition(PlayerState.IDLE)

    def _playback_worker(self, from_sample: int = 0) -> None:
        """Playback thread worker - plays from sample position using sounddevice stream."""
        try:
            # Slice audio from the target position
            with self._playback_lock:
                if self._audio_data is None:
                    return
                samples_to_play = self._audio_data[from_sample:]
                sample_rate = self._sample_rate
                channels = self._channels

            # Create callback-based output stream for better control
            current_frame = [0]  # Use list for mutability in closure
            total_frames = len(samples_to_play)

            def audio_callback(outdata, frames, time_info, status):
                if self._stop_event.is_set():
                    raise sd.CallbackStop()

                start = current_frame[0]
                end = start + frames

                if end >= total_frames:
                    # End of audio - pad with zeros if needed
                    remaining = total_frames - start
                    if remaining > 0:
                        # Apply volume dynamically
                        outdata[:remaining] = samples_to_play[start:total_frames] * self._volume
                        outdata[remaining:] = 0
                    else:
                        outdata.fill(0)
                    raise sd.CallbackStop()

                # Apply volume dynamically during playback
                outdata[:] = samples_to_play[start:end] * self._volume
                current_frame[0] = end

            # Create and start stream
            self._current_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype='float32',
                callback=audio_callback
            )

            self._play_start_time = time.time()
            self._current_stream.start()

            # Monitor playback state
            while not self._stop_event.is_set():
                # Check pause event FIRST before checking stream activity
                if self._pause_event.is_set():
                    # Pause: record position and stop stream
                    elapsed_samples = int((time.time() - self._play_start_time) * sample_rate)
                    self._pause_position_samples = from_sample + elapsed_samples
                    if self._current_stream and self._current_stream.active:
                        self._current_stream.stop()

                    # Wait for resume or stop
                    while self._pause_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.05)

                    if not self._stop_event.is_set() and not self._pause_event.is_set():
                        # Resume: exit this thread, resume() will start a new one
                        return
                    # Stop event was set, exit normally
                    break

                # Now check if stream stopped (only after checking pause)
                if self._current_stream is None or not self._current_stream.active:
                    break

                time.sleep(0.05)

            # Playback completed naturally
            if not self._stop_event.is_set() and self._on_track_end_callback:
                self._state_machine.force_transition(PlayerState.IDLE)
                try:
                    self._on_track_end_callback()
                except Exception as e:
                    print(f"Error in track end callback: {e}")

        except Exception as e:
            print(f"Playback error: {e}")
            import traceback
            traceback.print_exc()
            self._state_machine.force_transition(PlayerState.ERROR)

    def _preload_next_chunk(self, chunk_index: int, samples_per_chunk: int) -> None:
        """Preload the next chunk into buffer for seamless transition."""
        chunk_start = chunk_index * samples_per_chunk
        chunk_end = min(chunk_start + samples_per_chunk, self._total_samples)

        if chunk_start >= self._total_samples:
            with self._chunk_buffer_lock:
                self._next_chunk_data = None
                self._next_chunk_index = -1
            return

        with self._playback_lock:
            if self._audio_data is None:
                return
            chunk_data = self._audio_data[chunk_start:chunk_end].copy()

        with self._chunk_buffer_lock:
            self._next_chunk_data = chunk_data
            self._next_chunk_index = chunk_index

    def _get_chunk_data(self, chunk_index: int, samples_per_chunk: int) -> Optional[np.ndarray]:
        """Get chunk data from preload buffer or load directly."""
        with self._chunk_buffer_lock:
            if self._next_chunk_index == chunk_index and self._next_chunk_data is not None:
                # Use preloaded data
                chunk_data = self._next_chunk_data
                self._next_chunk_data = None
                self._next_chunk_index = -1
                return chunk_data

        # Load directly if not preloaded
        chunk_start = chunk_index * samples_per_chunk
        chunk_end = min(chunk_start + samples_per_chunk, self._total_samples)

        if chunk_start >= self._total_samples:
            return None

        with self._playback_lock:
            if self._audio_data is None:
                return None
            return self._audio_data[chunk_start:chunk_end].copy()

    def _switch_to_next_chunk(self, samples_per_chunk: int) -> bool:
        """Switch to the next chunk from preload buffer. Returns True if successful."""
        with self._chunk_buffer_lock:
            if self._next_chunk_data is not None:
                self._current_chunk_data = self._next_chunk_data
                self._current_chunk_index = self._next_chunk_index
                self._next_chunk_data = None
                self._next_chunk_index = -1
                return True

        # Fallback: load directly (should rarely happen)
        next_idx = self._current_chunk_index + 1
        data = self._get_chunk_data(next_idx, samples_per_chunk)
        if data is not None:
            self._current_chunk_data = data
            self._current_chunk_index = next_idx
            return True
        return False

    def _playback_worker_chunked(self, from_sample: int = 0) -> None:
        """Playback thread worker for large files - uses chunked loading with double buffering."""
        try:
            samples_per_chunk = int(self.CHUNK_DURATION_SEC * self._sample_rate)
            current_chunk = from_sample // samples_per_chunk
            offset_in_chunk = from_sample % samples_per_chunk

            # Initialize current chunk
            self._current_chunk_data = self._get_chunk_data(current_chunk, samples_per_chunk)
            self._current_chunk_index = current_chunk
            self._chunk_offset = offset_in_chunk  # Store offset for position tracking
            if self._current_chunk_data is None:
                return

            # Apply offset for first chunk
            if offset_in_chunk > 0:
                self._current_chunk_data = self._current_chunk_data[offset_in_chunk:]
                offset_in_chunk = 0

            # Start preloading next chunk immediately
            preload_thread = threading.Thread(
                target=self._preload_next_chunk,
                args=(current_chunk + 1, samples_per_chunk),
                daemon=True
            )
            preload_thread.start()

            # Playback state (no locks needed in callback)
            current_frame = [0]
            need_new_chunk = [False]
            chunk_exhausted = [False]

            def audio_callback(outdata, frames, time_info, status):
                if self._stop_event.is_set():
                    raise sd.CallbackStop()

                written = 0
                while written < frames:
                    chunk_data = self._current_chunk_data
                    if chunk_data is None:
                        outdata[written:] = 0
                        raise sd.CallbackStop()

                    remaining_in_chunk = len(chunk_data) - current_frame[0]

                    if remaining_in_chunk <= 0:
                        # Chunk exhausted, try to get next from preload buffer
                        if need_new_chunk[0]:
                            # Already requested but not ready, output silence briefly
                            outdata[written:written + 1] = 0
                            written += 1
                            continue

                        need_new_chunk[0] = True
                        # Try non-blocking switch
                        if self._switch_to_next_chunk(samples_per_chunk):
                            current_frame[0] = 0
                            self._chunk_offset = 0  # Reset offset when switching to new chunk
                            need_new_chunk[0] = False
                            # Trigger next preload
                            threading.Thread(
                                target=self._preload_next_chunk,
                                args=(self._current_chunk_index + 1, samples_per_chunk),
                                daemon=True
                            ).start()
                            continue
                        else:
                            # No more data
                            chunk_exhausted[0] = True
                            outdata[written:] = 0
                            raise sd.CallbackStop()

                    # Write audio data
                    to_write = min(frames - written, remaining_in_chunk)
                    start = current_frame[0]
                    end = start + to_write

                    outdata[written:written + to_write] = chunk_data[start:end] * self._volume
                    current_frame[0] = end
                    written += to_write

            sample_rate = self._sample_rate
            channels = self._channels

            # Create single stream for entire playback
            self._current_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype='float32',
                callback=audio_callback,
                blocksize=4096
            )

            self._play_start_time = time.time()
            self._current_stream.start()

            # Monitor thread: preload chunks and update position
            last_preloaded_chunk = current_chunk
            while not self._stop_event.is_set():
                # Check pause event FIRST before checking stream activity
                if self._pause_event.is_set():
                    if self._current_stream and self._current_stream.active:
                        self._current_stream.stop()

                    while self._pause_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.05)

                    if not self._stop_event.is_set():
                        # Resume: exit this thread, resume() will start a new one
                        return
                    # Stop event was set, exit normally
                    break

                # Now check if stream stopped (only after checking pause)
                if self._current_stream is None or not self._current_stream.active:
                    break

                # Preload next chunk if current chunk changed
                if self._current_chunk_index > last_preloaded_chunk:
                    threading.Thread(
                        target=self._preload_next_chunk,
                        args=(self._current_chunk_index + 1, samples_per_chunk),
                        daemon=True
                    ).start()
                    last_preloaded_chunk = self._current_chunk_index

                # Update position tracking (chunk_start + offset_in_chunk + current_frame)
                with self._playback_lock:
                    self._position_samples = min(
                        self._current_chunk_index * samples_per_chunk + self._chunk_offset + current_frame[0],
                        self._total_samples
                    )

                time.sleep(0.02)

            # Playback ended
            if not self._stop_event.is_set() and self._on_track_end_callback:
                self._state_machine.force_transition(PlayerState.IDLE)
                try:
                    self._on_track_end_callback()
                except Exception as e:
                    print(f"Error in track end callback: {e}")

        except Exception as e:
            print(f"Chunked playback error: {e}")
            import traceback
            traceback.print_exc()
            self._state_machine.force_transition(PlayerState.ERROR)


class VideoPlayer:
    """Video player (AVI, MP4, MKV, etc.)"""

    def __init__(self):
        self.is_playing = False
        self.current_file: Optional[str] = None
        self.cap = None
        self.frame_delay = 0.033  # Approximately 30fps

    def play_video(self, filepath: str) -> bool:
        """Play video file"""
        try:
            if not self._close():
                print("Failed to close, forcing reopen")
            self.cap = cv2.VideoCapture(filepath)
            if not self.cap.isOpened():
                return False
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cv2.namedWindow('PyPlayer Video', cv2.WINDOW_NORMAL)
            cv2.resizeWindow('PyPlayer Video', min(width, 1280), min(height, 720))
            self.current_file = filepath
            self.is_playing = True
            return True
        except (cv2.error, OSError, IOError) as e:
            print(i18n.console('console.video_play_failed', error=str(e)))
            import traceback
            traceback.print_exc()
            return False

    def _close(self) -> None:
        """Close current video"""
        if self.cap is not None and self.cap.isOpened():
            try:
                self.cap.release()
            except (cv2.error, AttributeError):
                pass
            self.cap = None
        try:
            cv2.destroyWindow('PyPlayer Video')
        except cv2.error:
            pass

    def render_frame(self) -> bool:
        """Render a frame"""
        if not self.is_playing or self.cap is None:
            return False
        ret, frame = self.cap.read()
        if not ret:
            self.stop()
            return False
        cv2.imshow('PyPlayer Video', frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            self.stop()
            print(i18n.console('console.user_exit'))
            return False
        import time
        time.sleep(self.frame_delay)
        return True

    def stop(self) -> None:
        """Stop playback"""
        self._close()
        self.is_playing = False


class PlayerManager:
    """Player manager, automatically selects audio or video mode"""

    SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.aiff', '.au', '.ncm'}
    SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}

    def __init__(self):
        # Use singleton AudioPlayer instance
        self._audio_player = AudioPlayer()
        self._video_player: Optional[VideoPlayer] = None
        self._is_video_playing = False
        self._was_playing = False

    @property
    def audio_player(self) -> AudioPlayer:
        """Read-only access to the singleton AudioPlayer."""
        return self._audio_player

    @property
    def video_player(self) -> Optional[VideoPlayer]:
        """Read-only access to the VideoPlayer."""
        return self._video_player

    @video_player.setter
    def video_player(self, value: Optional[VideoPlayer]) -> None:
        """Allow setting video player."""
        self._video_player = value

    def get_supported_formats(self) -> dict:
        """Get supported formats"""
        return {
            "音频": list(sorted(self.SUPPORTED_AUDIO)),
            "视频": list(sorted(self.SUPPORTED_VIDEO))
        }

    def _check_file_type(self, filepath: str) -> Optional[str]:
        """Determine file type: audio or video"""
        ext = Path(filepath).suffix.lower()
        if ext in self.SUPPORTED_AUDIO:
            return 'audio'
        elif ext in self.SUPPORTED_VIDEO:
            return 'video'
        else:
            return None

    def play(self, filepath: str) -> bool:
        """Play file (auto-select mode)"""
        if self._is_video_playing and self._video_player:
            self._video_player.stop()

        file_type = self._check_file_type(filepath)
        if not file_type:
            print(i18n.console('console.unsupported_format', path=filepath))
            return False

        try:
            import cv2
            cv2.destroyAllWindows()
        except (cv2.error, RuntimeError):
            pass

        self._video_player = VideoPlayer()
        self._is_video_playing = False

        if file_type == 'audio':
            # Use singleton audio_player - play_file will stop any current playback
            result = self._audio_player.play_file(filepath)
            if result:
                self._was_playing = True
        else:
            import cv2
            self._is_video_playing = True
            result = self._video_player.play_video(filepath)

        return result

    def play_playlist(self, files: List[str]) -> bool:
        """Play playlist"""
        if not files:
            return False

        audio_files = [f for f in files if self._check_file_type(f) == 'audio']
        video_files = [f for f in files if self._check_file_type(f) == 'video']

        if audio_files:
            # Use singleton audio_player - play_queue will handle stopping
            result = self._audio_player.play_queue(audio_files)
            if result and len(video_files) > 0:
                print(i18n.console('console.start_video_play', path=video_files[0]))
                self._is_video_playing = True

        for video in video_files:
            self._video_player = VideoPlayer()
            if not self._video_player.play_video(video):
                return False

        return len(audio_files) > 0 or len(video_files) > 0

    def get_status(self) -> Dict[str, Any]:
        """Get current playback status"""
        result = {
            "audio_playing": self._audio_player.is_active(),
            "video_playing": self._is_video_playing,
            "current_track": self._audio_player.current_track.title if self._audio_player.current_track else None,
            "paused": self._audio_player.is_paused,
            "state": self._audio_player.state.name,  # Add state enum name
        }

        if hasattr(self._audio_player, '_library_queues') and self._audio_player._library_queues:
            result["library_queues_status"] = {
                lib_id: {
                    "queue_length": len(qinfo['queue'].track_list),
                    "current_index": qinfo['queue'].current_index,
                    "state": qinfo['queue'].state,
                    "position_history_len": len(qinfo['queue'].position_state.history)
                }
                for lib_id, qinfo in self._audio_player._library_queues.items()
            }

        return result

    def get_playlist(self) -> List[Track]:
        """Get current playlist (audio only)"""
        return self._audio_player.queue if hasattr(self._audio_player, 'queue') else []

    def pause(self) -> None:
        """Pause playback"""
        if not self._is_video_playing:
            self._audio_player.pause()

    def resume(self) -> None:
        """Resume playback"""
        if not self._is_video_playing:
            self._audio_player.resume()

    def stop(self) -> None:
        """Stop playback"""
        self._audio_player.stop()
        if self._is_video_playing and self._video_player:
            self._video_player.stop()
        self._is_video_playing = False

    def toggle_play_pause(self) -> bool:
        """Toggle play/pause state"""
        if self._is_video_playing and self._video_player:
            return False

        status = self.get_status()
        if not status['current_track']:
            return False

        if status['paused']:
            self.resume()
            return True
        else:
            self.pause()
            return True

    def next_track(self) -> None:
        """Switch to next track"""
        pass

    def set_volume(self, level: float) -> None:
        """Set volume, level range 0.0-1.0"""
        self._audio_player.set_volume(level)

    def check_track_end(self) -> bool:
        """Check if the current track has just finished playing."""
        if self._is_video_playing:
            return False

        is_currently_playing = self._audio_player.is_playing and (
            self._audio_player.is_paused or
            (self._audio_player._current_stream and self._audio_player._current_stream.active)
        )

        if self._was_playing and not is_currently_playing and self._audio_player.current_track is not None:
            old_track = self._audio_player.current_track
            self._audio_player.current_track = None
            if self._audio_player._on_track_end_callback:
                try:
                    self._audio_player._on_track_end_callback()
                except Exception as e:
                    print(f"Error in track end callback: {e}")
            return True

        self._was_playing = is_currently_playing
        return False


def create_manager() -> PlayerManager:
    """Create player manager singleton"""
    try:
        cv2.namedWindow('PyPlayer Video', cv2.WINDOW_NORMAL)
        cv2.destroyWindow('PyPlayer Video')
    except (cv2.error, RuntimeError) as e:
        print(i18n.console('console.init_warning_video', error=str(e)))

    return PlayerManager()


def main() -> int:
    """Simple test"""
    print(i18n.get('console.test_title'))
    player = create_manager()

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        result = player.play(filepath)
        if not result:
            return 1

        while True:
            status = player.get_status()

            if status['audio_playing']:
                time.sleep(0.1)
            elif status['video_playing'] and player.video_player:
                import cv2
                key = cv2.waitKey(33) & 0xFF
                if key == ord('q'):
                    break
            else:
                break

        print(i18n.console('console.play_complete_or_stopped'))
        return 0
    else:
        formats = player.get_supported_formats()
        audio_fmts = ', '.join(formats['音频'])
        video_fmts = ', '.join(formats['视频'])
        print(f"\n{i18n.console('console.supported_formats_audio', formats=audio_fmts)}")
        print(f"{i18n.console('console.supported_formats_video', formats=video_fmts)}\n")


def launch_tui() -> None:
    """Launch terminal UI mode"""
    try:
        from tui.tui import main as tui_main
        import curses
        curses.wrapper(tui_main)
    except ImportError:
        print("TUI module not found. Please ensure tui/tui.py exists.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ('-t', '--tui'):
        launch_tui()
    else:
        main()
