#!/usr/bin/env python3
"""
Music player core module
Supported formats: MP3, WAV, AVI, MP4, MKV and other common audio/video formats
"""
import cv2
import pygame
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import re
import i18n


@dataclass
class Track:
    """Playlist item"""
    path: str
    title: str


class AudioPlayer:
    """Audio player (MP3, WAV, etc.)"""

    def __init__(self):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        self.is_playing = False
        self.is_paused = False
        self.current_track: Optional[Track] = None
        self.queue: List[Track] = []

    def play_file(self, filepath: str) -> bool:
        """Play single file"""
        try:
            pygame.mixer.music.load(filepath)
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.play()
            self.current_track = Track(path=filepath, title=Path(filepath).name)
            self.is_playing = True
            self.is_paused = False
            return True
        except (pygame.error, OSError, IOError) as e:
            print(i18n.console('console.play_failed', error=str(e)))
            return False

    def play_queue(self, files: List[str]) -> bool:
        """Play from queue"""
        try:
            if not files:
                return False
            pygame.mixer.music.queue(files[-1])  # Load the last one first
            pygame.mixer.music.load(files[0])
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.play()
            self.queue = [Track(path=f, title=Path(f).name) for f in files]
            self.current_track = self.queue[0]
            self.is_playing = True
            self.is_paused = False
            return True
        except (pygame.error, OSError, IOError) as e:
            print(i18n.console('console.queue_failed', error=str(e)))
            return False

    def pause(self) -> None:
        """Pause playback"""
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.is_paused = True

    def resume(self) -> None:
        """Resume playback"""
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.unpause()
            self.is_paused = False

    def stop(self) -> None:
        """Stop playback"""
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.current_track = None

    def set_volume(self, level: float) -> None:
        """Set volume, level range 0.0-1.0"""
        pygame.mixer.music.set_volume(max(0.0, min(1.0, level)))

    def get_volume(self) -> float:
        """Get current volume"""
        return pygame.mixer.music.get_volume()

    def is_active(self) -> bool:
        """Check if playing"""
        return pygame.mixer.music.get_busy() > 0 or (self.is_playing and not pygame.mixer.music.get_busy())


class VideoPlayer:
    """Video player (AVI, MP4, MKV, etc.)"""

    def __init__(self):
        self.is_playing = False
        self.current_file: Optional[str] = None
        import cv2
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
            # Set output window size
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
            self.stop()  # Video finished playing
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

    SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
    SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}

    def __init__(self):
        self.audio_player = AudioPlayer()
        self.video_player = None
        self._is_video_playing = False

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
        # First stop any previously playing media
        if self._is_video_playing and self.video_player:
            self.video_player.stop()

        file_type = self._check_file_type(filepath)
        if not file_type:
            print(i18n.console('console.unsupported_format', path=filepath))
            return False

        try:
            import pygame.mixer
            pygame.mixer.quit()
            import cv2
            cv2.destroyAllWindows()
        except (pygame.error, cv2.error):
            pass

        # Re-initialize
        self.audio_player = AudioPlayer()
        self.video_player = VideoPlayer()
        self._is_video_playing = False

        if file_type == 'audio':
            result = self.audio_player.play_file(filepath)
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

        # Process audio list first
        if audio_files:
            import pygame.mixer
            pygame.mixer.quit()
            self.audio_player = AudioPlayer()
            result = self.audio_player.play_queue(audio_files)
            if result and len(video_files) > 0:
                print(i18n.console('console.start_video_play', path=video_files[0]))
                self._is_video_playing = True

        # Handle video files list
        for video in video_files:
            import cv2
            self.video_player = VideoPlayer()
            if not self.video_player.play_video(video):
                return False

        return len(audio_files) > 0 or len(video_files) > 0

    def get_status(self) -> Dict[str, Any]:
        """Get current playback status"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        return {
            "audio_playing": self.audio_player.is_active(),
            "video_playing": self._is_video_playing,
            "current_track": self.audio_player.current_track.title if self.audio_player.current_track else None,
            "paused": self.audio_player.is_paused
        }

    def get_playlist(self) -> List[Track]:
        """Get current playlist (audio only)"""
        return self.audio_player.queue if hasattr(self.audio_player, 'queue') else []

    def pause(self) -> None:
        """Pause playback"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        if not self._is_video_playing:
            self.audio_player.pause()
        else:
            import cv2
            # Video pause shows current frame, doesn't actually pause decoding

    def resume(self) -> None:
        """Resume playback"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        if not self._is_video_playing:
            self.audio_player.resume()
        else:
            # Video continues rendering frames
            if self.video_player and self.video_player.render_frame():
                import time
                while True:
                    import cv2
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('r'):  # r resume
                        break
                    elif key == ord('q'):
                        return

    def stop(self) -> None:
        """Stop playback"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        self.audio_player.stop()
        if self._is_video_playing and self.video_player:
            self.video_player.stop()
        self._is_video_playing = False

    def toggle_play_pause(self) -> bool:
        """Toggle play/pause state"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except pygame.error:
            pass

        if self._is_video_playing and self.video_player:
            # Video: cannot simply pause, shows current frame
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
        # Simple implementation: replay current file (actual projects could use queue)
        pass

    def set_volume(self, level: float) -> None:
        """Set volume, level range 0.0-1.0"""
        self.audio_player.set_volume(level)


def create_manager() -> PlayerManager:
    """Create player manager singleton"""
    import pygame
    import cv2
    # Initialize pygame mixer first to avoid later issues
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except pygame.error as e:
        print(i18n.console('console.init_warning_audio', error=str(e)))

    # Setup OpenCV display backend (to avoid conflicts with Pygame)
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

        # Continue playing until complete or user exits
        while True:
            status = player.get_status()
            import time

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
        # Display supported formats
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
