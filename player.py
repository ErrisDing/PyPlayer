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
from pathlib import Path
from typing import List, Optional, Dict, Any

import cv2
import numpy as np
import soundfile as sf
import sounddevice as sd

import i18n
from library_manager import Track


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
        # Playback state
        self.is_playing = False
        self.is_paused = False
        self.current_track: Optional[Track] = None
        self.queue: List[Track] = []

        # Per-library queue management
        self._library_queues: Dict[str, 'PlaybackQueueInfo'] = {}

        # Track end callback support
        self._on_track_end_callback: Optional[callable] = None

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

    def set_track_end_callback(self, callback: callable) -> None:
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
    def play_file(self, filepath: str) -> bool:
        """Play a single file using soundfile + sounddevice.

        Args:
            filepath: Path to the audio file

        Returns:
            True if playback started successfully, False otherwise
        """
        try:
            # Stop any current playback
            self._stop_playback()

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

            # Apply volume
            if self._volume != 1.0:
                audio_data = audio_data * self._volume

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
            from metadata import extract_metadata
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

            # Start playback
            self._start_playback(from_sample=0)
            return True

        except Exception as e:
            print(i18n.console('console.play_failed', error=str(e)))
            import traceback
            traceback.print_exc()
            self.is_playing = False
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
        if not self.is_playing or self.is_paused:
            return

        with self._playback_lock:
            # Record current position before pausing
            if self._current_stream and self._current_stream.active:
                elapsed_samples = int((time.time() - self._play_start_time) * self._sample_rate)
                self._pause_position_samples = self._position_samples + elapsed_samples
                self._current_stream.stop()
            else:
                self._pause_position_samples = self._position_samples

            self._pause_event.set()
            self.is_paused = True

    def resume(self) -> None:
        """Resume playback from paused position."""
        if not self.is_paused:
            return

        self.is_paused = False
        self._pause_event.clear()

        # Resume from paused position
        self._start_playback(from_sample=self._pause_position_samples)

    def stop(self) -> None:
        """Stop playback and clear state."""
        self._stop_playback()
        with self._playback_lock:
            self.current_track = None
            self._audio_data = None
            self._filepath = None
            self._position_samples = 0
            self._pause_position_samples = 0
            self._total_samples = 0

    def set_volume(self, level: float) -> None:
        """Set volume, level range 0.0-1.0.

        Volume is applied to audio data during playback.
        """
        self._volume = max(0.0, min(1.0, level))

        # If currently playing, apply volume by adjusting audio data
        if self.is_playing and not self.is_paused and self._audio_data is not None:
            current_pos = self.get_position()
            with self._playback_lock:
                # Reload and apply new volume
                if self._filepath:
                    audio_data, sample_rate = sf.read(self._filepath, dtype='float32')
                    if audio_data.ndim == 1:
                        audio_data = audio_data.reshape(-1, 1)
                    if audio_data.shape[1] == 1:
                        audio_data = np.column_stack([audio_data, audio_data])
                    elif audio_data.shape[1] > 2:
                        audio_data = audio_data[:, :2]
                    self._audio_data = audio_data * self._volume

            # Seek to current position with new volume
            self._start_playback(from_sample=int(current_pos * self._sample_rate))

    def get_volume(self) -> float:
        """Get current volume level (0.0-1.0)."""
        return self._volume

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        if not self.is_playing or not self.current_track:
            return 0.0

        if self.is_paused:
            return self._pause_position_samples / self._sample_rate

        # Calculate position from playback start time
        with self._playback_lock:
            if self._current_stream and self._current_stream.active:
                elapsed_samples = int((time.time() - self._play_start_time) * self._sample_rate)
                position_samples = self._position_samples + elapsed_samples
                return min(position_samples, self._total_samples) / self._sample_rate
            else:
                return self._position_samples / self._sample_rate

    def get_duration(self) -> float:
        """Get current track duration in seconds."""
        if self.current_track and hasattr(self.current_track, 'duration'):
            return self.current_track.duration
        return self._total_samples / self._sample_rate if self._sample_rate > 0 else 0.0

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
        with self._playback_lock:
            self._position_samples = from_sample
            self._stop_event.clear()
            self._pause_event.clear()

        self.is_playing = True
        self.is_paused = False

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
        self.is_playing = False
        self.is_paused = False

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
                        outdata[:remaining] = samples_to_play[start:total_frames]
                        outdata[remaining:] = 0
                    else:
                        outdata.fill(0)
                    raise sd.CallbackStop()

                outdata[:] = samples_to_play[start:end]
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
                if self._current_stream is None or not self._current_stream.active:
                    break

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
                        return
                    break

                time.sleep(0.05)

            # Playback completed naturally
            if not self._stop_event.is_set() and self._on_track_end_callback:
                self.is_playing = False
                try:
                    self._on_track_end_callback()
                except Exception as e:
                    print(f"Error in track end callback: {e}")

        except Exception as e:
            print(f"Playback error: {e}")
            import traceback
            traceback.print_exc()
            self.is_playing = False

    def _playback_worker_chunked(self, from_sample: int = 0) -> None:
        """Playback thread worker for large files - uses chunked loading."""
        try:
            samples_per_chunk = int(self.CHUNK_DURATION_SEC * self._sample_rate)
            current_chunk = from_sample // samples_per_chunk
            offset_in_chunk = from_sample % samples_per_chunk

            while not self._stop_event.is_set():
                # Check if we've played all chunks
                chunk_start = current_chunk * samples_per_chunk
                chunk_end = min(chunk_start + samples_per_chunk, self._total_samples)

                if chunk_start >= self._total_samples:
                    break

                # Load current chunk
                with self._playback_lock:
                    if self._audio_data is None:
                        return
                    chunk_data = self._audio_data[chunk_start:chunk_end]

                # Apply offset for first chunk
                if offset_in_chunk > 0:
                    chunk_data = chunk_data[offset_in_chunk:]
                    offset_in_chunk = 0

                # Play this chunk
                current_frame = [0]
                total_frames = len(chunk_data)

                def audio_callback(outdata, frames, time_info, status):
                    if self._stop_event.is_set():
                        raise sd.CallbackStop()

                    start = current_frame[0]
                    end = start + frames

                    if end >= total_frames:
                        remaining = total_frames - start
                        if remaining > 0:
                            outdata[:remaining] = chunk_data[start:total_frames]
                            outdata[remaining:] = 0
                        else:
                            outdata.fill(0)
                        raise sd.CallbackStop()

                    outdata[:] = chunk_data[start:end]
                    current_frame[0] = end

                sample_rate = self._sample_rate
                channels = self._channels

                self._current_stream = sd.OutputStream(
                    samplerate=sample_rate,
                    channels=channels,
                    dtype='float32',
                    callback=audio_callback
                )

                self._play_start_time = time.time()
                self._current_stream.start()

                # Wait for chunk to finish
                while not self._stop_event.is_set():
                    if self._current_stream is None or not self._current_stream.active:
                        break

                    if self._pause_event.is_set():
                        elapsed_samples = int((time.time() - self._play_start_time) * sample_rate)
                        self._pause_position_samples = chunk_start + offset_in_chunk + elapsed_samples
                        if self._current_stream and self._current_stream.active:
                            self._current_stream.stop()

                        while self._pause_event.is_set() and not self._stop_event.is_set():
                            time.sleep(0.05)

                        if not self._stop_event.is_set():
                            return
                        break

                    time.sleep(0.05)

                if self._stop_event.is_set():
                    break

                # Move to next chunk
                with self._playback_lock:
                    self._position_samples = min((current_chunk + 1) * samples_per_chunk, self._total_samples)
                current_chunk += 1

            # Playback completed naturally
            if not self._stop_event.is_set() and self._on_track_end_callback:
                self.is_playing = False
                try:
                    self._on_track_end_callback()
                except Exception as e:
                    print(f"Error in track end callback: {e}")

        except Exception as e:
            print(f"Chunked playback error: {e}")
            import traceback
            traceback.print_exc()
            self.is_playing = False


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

    SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.aiff', '.au'}
    SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}

    def __init__(self):
        self.audio_player = AudioPlayer()
        self.video_player = None
        self._is_video_playing = False
        self._was_playing = False

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
        if self._is_video_playing and self.video_player:
            self.video_player.stop()

        file_type = self._check_file_type(filepath)
        if not file_type:
            print(i18n.console('console.unsupported_format', path=filepath))
            return False

        try:
            import cv2
            cv2.destroyAllWindows()
        except (cv2.error, RuntimeError):
            pass

        self.audio_player = AudioPlayer()
        self.video_player = VideoPlayer()
        self._is_video_playing = False

        if file_type == 'audio':
            result = self.audio_player.play_file(filepath)
            if result:
                self._was_playing = True
        else:
            import cv2
            self._is_video_playing = True
            result = self.video_player.play_video(filepath)

        return result

    def play_playlist(self, files: List[str]) -> bool:
        """Play playlist"""
        if not files:
            return False

        audio_files = [f for f in files if self._check_file_type(f) == 'audio']
        video_files = [f for f in files if self._check_file_type(f) == 'video']

        if audio_files:
            self.audio_player = AudioPlayer()
            result = self.audio_player.play_queue(audio_files)
            if result and len(video_files) > 0:
                print(i18n.console('console.start_video_play', path=video_files[0]))
                self._is_video_playing = True

        for video in video_files:
            self.video_player = VideoPlayer()
            if not self.video_player.play_video(video):
                return False

        return len(audio_files) > 0 or len(video_files) > 0

    def get_status(self) -> Dict[str, Any]:
        """Get current playback status"""
        result = {
            "audio_playing": self.audio_player.is_active(),
            "video_playing": self._is_video_playing,
            "current_track": self.audio_player.current_track.title if self.audio_player.current_track else None,
            "paused": self.audio_player.is_paused,
        }

        if hasattr(self.audio_player, '_library_queues') and self.audio_player._library_queues:
            result["library_queues_status"] = {
                lib_id: {
                    "queue_length": len(qinfo['queue'].track_list),
                    "current_index": qinfo['queue'].current_index,
                    "state": qinfo['queue'].state,
                    "position_history_len": len(qinfo['queue'].position_state.history)
                }
                for lib_id, qinfo in self.audio_player._library_queues.items()
            }

        return result

    def get_playlist(self) -> List[Track]:
        """Get current playlist (audio only)"""
        return self.audio_player.queue if hasattr(self.audio_player, 'queue') else []

    def pause(self) -> None:
        """Pause playback"""
        if not self._is_video_playing:
            self.audio_player.pause()

    def resume(self) -> None:
        """Resume playback"""
        if not self._is_video_playing:
            self.audio_player.resume()

    def stop(self) -> None:
        """Stop playback"""
        self.audio_player.stop()
        if self._is_video_playing and self.video_player:
            self.video_player.stop()
        self._is_video_playing = False

    def toggle_play_pause(self) -> bool:
        """Toggle play/pause state"""
        if self._is_video_playing and self.video_player:
            return False

        status = self.audio_player.get_status()
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
        self.audio_player.set_volume(level)

    def check_track_end(self) -> bool:
        """Check if the current track has just finished playing."""
        if self._is_video_playing:
            return False

        is_currently_playing = self.audio_player.is_playing and (
            self.audio_player.is_paused or
            (self.audio_player._current_stream and self.audio_player._current_stream.active)
        )

        if self._was_playing and not is_currently_playing and self.audio_player.current_track is not None:
            old_track = self.audio_player.current_track
            self.audio_player.current_track = None
            if self.audio_player._on_track_end_callback:
                try:
                    self.audio_player._on_track_end_callback()
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
        from tui import main as tui_main
        import curses
        curses.wrapper(tui_main)
    except ImportError:
        print("TUI module not found. Please ensure tui.py exists.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ('-t', '--tui'):
        launch_tui()
    else:
        main()
