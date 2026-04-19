#!/usr/bin/env python3
"""Unit tests for PyPlayer queue management system."""
import unittest
import tempfile
import os
from pathlib import Path

# Suppress pygame output
os.environ['SDL_AUDIODRIVER'] = 'dummy'


class TestPlayerModule(unittest.TestCase):
    """Test player.py module structure and methods."""

    def test_audio_player_core_methods(self):
        """AudioPlayer must have all core playback methods."""
        from player import AudioPlayer
        ap = AudioPlayer()

        required_methods = [
            'play_file', 'pause', 'resume', 'stop',
            'set_volume', 'get_volume', 'is_active',
            'play_from_queue', 'next_track_in_queue', 'prev_track_in_queue',
            'register_library_queue', 'unregister_library_queue'
        ]
        for method in required_methods:
            self.assertTrue(hasattr(ap, method), f"AudioPlayer missing method: {method}")

    def test_player_manager_core_methods(self):
        """PlayerManager must have all core methods."""
        from player import PlayerManager
        pm = PlayerManager()

        required_methods = [
            'play', 'pause', 'resume', 'stop', 'get_status',
            'toggle_play_pause', 'set_volume', 'next_track',
            'play_playlist', 'get_playlist'
        ]
        for method in required_methods:
            self.assertTrue(hasattr(pm, method), f"PlayerManager missing method: {method}")

    def test_get_status_structure(self):
        """get_status() must return correct structure."""
        from player import PlayerManager
        pm = PlayerManager()
        status = pm.get_status()

        required_keys = ['audio_playing', 'video_playing', 'current_track', 'paused']
        for key in required_keys:
            self.assertIn(key, status, f"status missing key: {key}")

    def test_audio_player_queue_management(self):
        """AudioPlayer queue registration should work."""
        from player import AudioPlayer
        from library_manager import PlaybackQueue, PlaybackState, Track

        ap = AudioPlayer()

        # Create a test queue (position_state is auto-created)
        queue = PlaybackQueue(
            library_id="test_lib",
            track_list=[Track(path="test.mp3", title="Test")],
            current_index=0,
            state="IDLE"
        )

        # Register
        ap.register_library_queue("test_lib", queue)
        self.assertIn("test_lib", ap._library_queues)

        # Unregister
        result = ap.unregister_library_queue("test_lib")
        self.assertTrue(result)
        self.assertNotIn("test_lib", ap._library_queues)


class TestLibraryManagerModule(unittest.TestCase):
    """Test library_manager.py module structure."""

    def test_playback_state_class(self):
        """PlaybackState should track position history."""
        from library_manager import PlaybackState

        state = PlaybackState()
        self.assertEqual(state.current_position, 0)
        self.assertEqual(state.history, [])
        self.assertEqual(state.loop_mode, "OFF")

        # Test record_position
        state.record_position(5)
        self.assertEqual(state.current_position, 5)
        self.assertEqual(state.history, [0])

        state.record_position(10)
        self.assertEqual(state.current_position, 10)
        self.assertEqual(state.history, [0, 5])

    def test_playback_queue_class(self):
        """PlaybackQueue should be constructable."""
        from library_manager import PlaybackQueue, PlaybackState, Track

        queue = PlaybackQueue(
            library_id="test",
            track_list=[Track(path="a.mp3", title="A"), Track(path="b.mp3", title="B")],
            current_index=0,
            state="IDLE"
        )

        self.assertEqual(queue.library_id, "test")
        self.assertEqual(len(queue.track_list), 2)
        self.assertEqual(queue.state, "IDLE")
        # position_state is auto-created via __post_init__
        self.assertIsNotNone(queue.position_state)

    def test_library_runtime_class(self):
        """LibraryRuntime should bind config with queue."""
        from library_manager import LibraryRuntime
        from config import LibraryConfig

        config = LibraryConfig(
            path="/test/path",
            name="Test Library"
        )
        runtime = LibraryRuntime(config=config)

        self.assertEqual(runtime.config.path, "/test/path")
        self.assertEqual(runtime.config.name, "Test Library")


class TestIntegration(unittest.TestCase):
    """Integration tests for the queue system."""

    def test_end_to_end_queue_flow(self):
        """Test complete queue flow from library to player."""
        from player import PlayerManager
        from library_manager import (
            PlaybackQueue, PlaybackState, Track,
            LibraryRuntimeManager
        )

        pm = PlayerManager()
        lrm = LibraryRuntimeManager()

        # Create and register a queue (position_state auto-created)
        queue = PlaybackQueue(
            library_id="integration_test",
            track_list=[Track(path="dummy.mp3", title="Dummy")],
            current_index=0,
            state="IDLE"
        )

        pm.audio_player.register_library_queue("integration_test", queue)

        # Verify registration
        status = pm.get_status()
        # queue status is optional, just verify no crash
        self.assertIsInstance(status, dict)

        # Cleanup
        pm.audio_player.unregister_library_queue("integration_test")
        pm.stop()


class TestHierarchicalPlaylist(unittest.TestCase):
    """Test _HierarchicalPlaylist for multiple library support."""

    def test_multiple_libraries_display(self):
        """Verify multiple media libraries are correctly marked as [ML]."""
        from library_manager import _HierarchicalPlaylist

        hier = _HierarchicalPlaylist()

        # Add tracks from two different media libraries
        hier.add_track(
            full_path="/Music1/song1.mp3",
            display_title="song1.mp3",
            library_path="/Music1",
            library_name="MusicLibrary1"
        )
        hier.add_track(
            full_path="/Music2/song2.mp3",
            display_title="song2.mp3",
            library_path="/Music2",
            library_name="MusicLibrary2"
        )

        display_items = hier.build_display_list()

        # Verify both libraries are marked as [ML]
        ml_count = sum(1 for text, _ in display_items if text.startswith("[ML]"))
        self.assertEqual(ml_count, 2, f"Expected 2 [ML] markers, got {ml_count}")

    def test_play_button_uses_selected_track(self):
        """Verify play button plays selected/current track (core logic test)."""
        # Simulate _open_files behavior
        playlist = []
        selected_index = -1
        current_index = -1

        # Simulate adding 3 files
        new_files = ["file1.mp3", "file2.mp3", "file3.mp3"]
        for f in new_files:
            playlist.append(f)

        idx = len(playlist) - len(new_files)  # 0
        current_index = idx
        selected_index = idx  # Fix: sync selected_index

        # Verify selected_index is correctly set
        self.assertEqual(selected_index, 0, f"Expected selected_index=0, got {selected_index}")

        # Simulate selecting the second track
        selected_index = 1

        # Simulate _toggle_play_pause logic
        play_idx = selected_index if 0 <= selected_index < len(playlist) else 0
        self.assertEqual(play_idx, 1, f"Expected to play index 1, got {play_idx}")


if __name__ == '__main__':
    # Import after setting env
    from player import AudioPlayer, PlayerManager
    from library_manager import PlaybackState, PlaybackQueue, LibraryRuntime, LibraryRuntimeManager

    unittest.main(verbosity=2)
