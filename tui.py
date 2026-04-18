#!/usr/bin/env python3
"""
PyPlayer - Terminal user interface based on curses/ncurses
Supports common audio/video formats: MP3, WAV, AVI, MP4, MKV, etc.
"""

import curses
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import time
import i18n


@dataclass
class Track:
    """Playlist item"""
    path: str
    title: str
    duration: float = 0.0

    def __str__(self):
        return self.title


class TerminalUI:
    """Terminal user interface based on curses"""

    COLORS = {
        'header': None,
        'body': None,
        'highlight': None,
        'error': None,
        'footer': None,
    }

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.player = None
        self.playlist: List[Track] = []
        self.current_index = 0
        self.selected_index = 0
        self.status_message = i18n.get('status.ready')
        self.running = True

        # Initialize colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)      # header
        curses.init_pair(2, curses.COLOR_WHITE, -1)     # body
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # highlight
        curses.init_pair(4, curses.COLOR_RED, -1)       # error
        curses.init_pair(5, curses.COLOR_GREEN, -1)     # footer

        self.COLORS['header'] = curses.color_pair(1) | curses.A_BOLD
        self.COLORS['body'] = curses.color_pair(2)
        self.COLORS['highlight'] = curses.color_pair(3)
        self.COLORS['error'] = curses.color_pair(4)
        self.COLORS['footer'] = curses.color_pair(5)

    def set_player(self, player):
        """Set player instance"""
        self.player = player

    def refresh_status(self, msg: str):
        """Update status message"""
        self.status_message = msg

    def draw_header(self):
        """Draw header"""
        height, width = self.stdscr.getmaxyx()

        try:
            title = i18n.get('main.title')
            self.stdscr.attron(self.COLORS['header'])
            self.stdscr.addstr(0, 0, f"{title:^{width}}")
            self.stdscr.attroff(self.COLORS['header'])

            # Show current status
            if self.player:
                status = self.player.get_status()
                track_info = ""
                if status['current_track']:
                    track_info = f" | Playing: {status['current_track']}"
                if status['paused']:
                    track_info += " [PAUSED]"

                try:
                    self.stdscr.addstr(1, 2, f"{track_info[:width-4]}")
                except curses.error:
                    pass
        except curses.error:
            pass

    def draw_playlist(self):
        """Draw playlist (supports hierarchical display)"""
        height, width = self.stdscr.getmaxyx()
        start_row = 3

        if not self.playlist:
            try:
                self.stdscr.attron(self.COLORS['error'])
                self.stdscr.addstr(start_row, 2, i18n.get('no_files_playlist', default="No files in playlist. Press 'o' to open file(s)"))
                self.stdscr.attroff(self.COLORS['error'])
            except curses.error:
                pass
            return

        # Build hierarchical display using library_manager's _HierarchicalPlaylist
        from library_manager import _HierarchicalPlaylist
        hier = _HierarchicalPlaylist()
        for track in self.playlist:
            hier.add_track(track.path, track.title)

        display_items = hier.build_display_list()

        visible_lines = min(height - start_row - 3, len(display_items))
        scroll_start = max(0, self.selected_index - visible_lines // 2)
        scroll_end = min(scroll_start + visible_lines, len(display_items))

        for i in range(scroll_start, scroll_end):
            row = start_row + (i - scroll_start)
            display_text, track_info = display_items[i]

            # Determine color/attr based on selection and playing state
            if i == self.current_index:
                indicator = "[NOW PLAYING]"
                attr = self.COLORS['highlight']
            elif i == self.selected_index:
                indicator = ">>"
                attr = curses.A_BOLD
            else:
                indicator = "  "
                attr = self.COLORS['body']

            try:
                line = f"{indicator} {display_text}"[:width-5]
                self.stdscr.attron(attr)
                self.stdscr.addstr(row, 2, line.ljust(width-4))
                self.stdscr.attroff(attr)
            except curses.error:
                pass

        # Store display_items for double-click handling in TUI (optional enhancement)
        self._playlist_display_items = display_items

    def draw_footer(self):
        """Draw footer"""
        height, width = self.stdscr.getmaxyx()
        row = height - 2

        # Status bar
        try:
            status_text = f" {self.status_message}"[:width-4]
            self.stdscr.attron(self.COLORS['footer'])
            self.stdscr.addstr(row, 0, f"{status_text:<{width}}")
            self.stdscr.attroff(self.COLORS['footer'])

            # Control hints
            help_text = i18n.get('tui.help_keys', default=" [SPACE]=Play/Pause | N=Next | M=Prev | S=Stop | O=Open | L=Library | Q=Quit")[:width-4]
            self.stdscr.attron(curses.color_pair(2) | curses.A_DIM)
            self.stdscr.addstr(row+1, 0, f"{help_text:<{width}}")
            self.stdscr.attroff(curses.color_pair(2) | curses.A_DIM)
        except curses.error:
            pass

    def draw(self):
        """Draw entire interface"""
        self.stdscr.clear()
        self.draw_header()
        self.draw_playlist()
        self.draw_footer()
        self.stdscr.refresh()

    def run(self):
        """Main loop"""
        while self.running:
            self.draw()

            # Read key input (with timeout)
            try:
                key = self.stdscr.getch(100)  # 100ms timeout for status updates
            except curses.error:
                key = -1

            if key == ord('q'):
                self.running = False
            elif key in [ord('n'), ord('N')]:
                self._handle_next()
            elif key in [ord('m'), ord('M')]:
                self._handle_prev()
            elif key == ord(' '):
                self._handle_play_pause()
            elif key == ord('s'):
                self._handle_stop()
            elif key in [ord('o'), ord('O')]:
                self._handle_open()
            elif key == ord('h'):
                self.show_help()
            elif key in [ord('l'), ord('L')]:
                self._show_library_manager_menu()
            elif key == 10:  # Enter key - can trigger folder playback or play file
                self._handle_double_click()
                time.sleep(0.1)  # Small delay to avoid repeat triggers
            elif key in [curses.KEY_UP, 258]:
                self.selected_index = max(0, self.selected_index - 1)
            elif key in [curses.KEY_DOWN, 259]:
                self.selected_index = min(len(self.playlist) - 1, self.selected_index + 1)

    def _handle_play_pause(self):
        """Handle play/pause"""
        if not self.player:
            return

        status = self.player.get_status()
        if not status['current_track'] and self.playlist:
            # Start playing first track or selected track
            idx = self.selected_index
            result = self.player.play(self.playlist[idx].path)
            if result:
                self.refresh_status(f"Now playing: {self.playlist[idx].title}")
        else:
            # Toggle play/pause
            if self.player.toggle_play_pause():
                if status['paused']:
                    self.refresh_status("Paused")
                else:
                    self.refresh_status("Playing")

    def _handle_stop(self):
        """Handle stop"""
        if not self.player:
            return

        self.player.stop()
        self.refresh_status("Playback stopped")

    def _handle_next(self):
        """Handle next track"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index + 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.refresh_status(f"Now playing: {track.title}")

    def _handle_prev(self):
        """Handle previous track"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index - 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.refresh_status(f"Now playing: {track.title}")

    def _handle_open(self):
        """Handle open file"""
        try:
            filename = curses.getstr(5, 2, 80)
            filepath = filename.decode('utf-8').strip()

            if not filepath:
                return

            path = Path(filepath).resolve()
            if not path.exists():
                self.refresh_status(f"File not found: {filepath}")
                time.sleep(1)
                return

            # Add to playlist and play
            track = Track(path=str(path), title=path.name)
            self.playlist.append(track)
            self.selected_index = len(self.playlist) - 1
            self.current_index = self.selected_index

            if not self.player:
                import player as pm
                self.player = pm.create_manager()

            result = self.player.play(str(path))
            if result:
                self.refresh_status(f"Added and playing: {path.name}")
            else:
                self.refresh_status(f"Failed to play: {path.name}")

        except (OSError, IOError, RuntimeError) as e:
            self.refresh_status(f"Error opening file: {e}")

    def _handle_double_click(self):
        """Handle double-click or Enter on playlist item for folder playback"""
        if not hasattr(self, '_playlist_display_items') or not self._playlist_display_items:
            return

        track_info = self._playlist_display_items[self.selected_index][1]
        if track_info and track_info.get('is_folder'):
            folder_path = track_info.get('path')
            folder_name = track_info.get('title', '')
            if folder_path:
                # Find all tracks in this folder
                folder_tracks = [t for t in self.playlist
                               if Path(t.path).is_relative_to(folder_path) or str(Path(t.path)).startswith(folder_path)]

                if folder_tracks:
                    folder_tracks.sort(key=lambda t: t.path)
                    first_track = folder_tracks[0]
                    self.current_index = self.playlist.index(first_track) if first_track in self.playlist else 0

                    if self.player:
                        result = self.player.play(str(first_track.path))
                        if result:
                            self.refresh_status(f"Now playing from folder: {folder_name}")

    def _show_library_manager_menu(self):
        """Show library management menu"""
        from config import SettingsManager

        # Initialize settings manager if not already done
        try:
            if not hasattr(self, 'settings_manager'):
                self.settings_manager = SettingsManager()
            else:
                self.settings_manager.load()  # Reload to get latest changes
        except (ImportError, AttributeError, OSError, IOError) as e:
            self.refresh_status(f"Failed to load settings: {e}")
            time.sleep(1)
            return

        height, width = self.stdscr.getmaxyx()
        menu_h, menu_w = min(20, height - 4), min(60, width - 4)
        start_y, start_x = (height - menu_h) // 2, (width - menu_w) // 2

        # Create menu window
        try:
            menu_win = curses.newwin(menu_h, menu_w, start_y, start_x)
            menu_win.box()

            # Title
            title = " Library Management "
            menu_win.addstr(0, (menu_w - len(title)) // 2, title[:menu_w-2], curses.A_BOLD)

            # Load libraries
            libs = self.settings_manager.settings.media_libraries
            lib_titles = []  # For tracking displayed titles with indices

            for i, lib in enumerate(libs):
                name = lib.name or Path(lib.path).name
                path = lib.path[:width - len(name) - 15] if len(path) > width - len(name) - 15 else path
                menu_win.addstr(3 + i, 2, f"[{i+1}] {name}: {path}")
                lib_titles.append((lib, name))

            # If no libraries, show message
            if not libs:
                menu_win.addstr(4, 2, "No libraries configured.")
                menu_win.addstr(5, 2, "Press 'A' to add one.")

            # Help text at bottom
            help_text = i18n.get('tui.lib_menu_keys', default=" [A]Add  [D]Delete  [S]Scan  [Q]Quit")
            menu_win.addstr(menu_h - 1, (menu_w - len(help_text)) // 2, help_text[:menu_w-4])

            menu_win.refresh()

            # Menu loop
            while True:
                key = menu_win.getch()

                if key in [ord('q'), ord('Q')]:
                    break
                elif key == ord('\n') or key == 10:  # Enter to select
                    pass
                else:
                    if key in [ord('a'), ord('A')] and libs:
                        self._menu_add_library(menu_win, len(libs))
                        menu_win.refresh()
                    elif key in [ord('d'), ord('D')] and libs:
                        idx = self._get_menu_selection_index(menu_win)
                        if idx is not None and 0 <= idx < len(libs):
                            lib, _ = lib_titles[idx]
                            # For TUI, we confirm by showing the path and requiring Enter to continue
                            try:
                                menu_win.addstr(12, 2, f"DELETE '{lib.path}'? (Press any key to confirm)", curses.A_BOLD)
                                menu_win.refresh()
                                menu_win.getch()
                                if self.settings_manager.remove_library(lib.path):
                                    self.refresh_status(f"Deleted: {Path(lib.path).name}")
                                    time.sleep(0.5)
                                    break  # Redraw menu
                            except curses.error:
                                pass
                    elif key in [ord('s'), ord('S')]:
                        result = self._menu_scan_libraries(menu_win)
                        if result:
                            self.refresh_status(f"Scanned {result} files total")
                            time.sleep(1)
                            break

        except curses.error as e:
            self.refresh_status(f"Menu error: {e}")
            time.sleep(0.5)

    def _get_menu_selection_index(self, menu_win):
        """Get user's selection index from menu"""
        try:
            c = menu_win.getch()
            if 48 < c <= 57:  # Digits 1-9
                return c - 49  # Convert to 0-based index
        except curses.error:
            pass
        return None

    def _menu_add_library(self, menu_win, lib_count):
        """Show path input dialog to add library"""
        input_h, input_w = 6, 50
        start_y, start_x = (menu_win.getmaxyx()[0] - input_h) // 2 + 2, \
                           (menu_win.getmaxyx()[1] - input_w) // 2

        input_win = curses.newwin(input_h, input_w, start_y, start_x)
        input_win.box()
        input_win.addstr(1, 2, "Library Path:", curses.A_BOLD)
        input_win.addstr(2, 2, "Enter or paste path:")
        input_win.refresh()

        try:
            curses.echo()
            curses.curs_set(1)

            # Get user input
            path_bytes = input_win.getstr(3, 2, 45)
            path = path_bytes.decode('utf-8').strip()

            curses.noecho()
            curses.curs_set(0)

            if not path:
                return

            lib_path = Path(path).expanduser().resolve()
            if not lib_path.exists():
                self.refresh_status(f"Path does not exist: {path}")
                time.sleep(1)
                return

            # Try to add library
            try:
                from config import SettingsManager
                sm = SettingsManager()
                dir_name = lib_path.name or "Library"
                if sm.add_library(str(lib_path), dir_name):
                    self.refresh_status(i18n.get('library_added', default=f"Added: {dir_name}"))
                    time.sleep(0.5)
                else:
                    self.refresh_status("Failed to add library")
                    time.sleep(1)
            except (OSError, IOError, AttributeError) as e:
                self.refresh_status(f"Error adding library: {e}")
                time.sleep(1)

        except (ValueError, TypeError, AttributeError) as e:
            curses.noecho()
            curses.curs_set(0)
            self.refresh_status(f"Input error: {e}")
            time.sleep(0.5)

    def _menu_scan_libraries(self, menu_win):
        """Show scan results"""
        from library_manager import LibraryManager

        try:
            manager = LibraryManager()
            result = manager.scan_all_libraries()
            total = sum(len(files) for files in result.values())

            # Show summary window
            height, width = menu_win.getmaxyx()
            info_h, info_w = 10, 40
            start_y, start_x = (height - info_h) // 2 + 3, \
                               (width - info_w) // 2

            info_win = curses.newwin(info_h, info_w, start_y, start_x)
            info_win.box()
            info_win.addstr(1, 2, " Scan Results ", curses.A_BOLD | curses.A_UNDERLINE)
            info_win.addstr(3, 2, f"Total files scanned: {total}")

            for path, files in list(result.items())[:5]:
                name = Path(path).name
                info_win.addstr(4 + list(result.keys()).index(path), 2,
                              f"{name}: {len(files)} files")

            info_win.addstr(info_h - 2, 2, "Press any key to continue", curses.A_DIM)
            info_win.refresh()

            # Wait for keypress
            while True:
                c = info_win.getch(100)
                if c != -1:
                    break

            return total

        except (OSError, IOError, PermissionError) as e:
            self.refresh_status(f"Scan error: {e}")
            time.sleep(1)
            return 0

    def show_help(self):
        """Show help information"""
        height, width = self.stdscr.getmaxyx()
        help_msg = [
            "=== PyPlayer Controls ===",
            "",
            "Library Management:",
            "  L         - Library management menu",
            "",
            "Navigation:",
            "  UP/DOWN   - Select track in playlist",
            "  N         - Next track",
            "  M         - Previous track",
            "",
            "Playback:",
            "  SPACE     - Play/Pause toggle",
            "  S         - Stop playback",
            "  O         - Open file(s)",
            "",
            "Other:",
            "  H         - Show this help",
            "  Q         - Quit player",
            "",
            "Press any key to continue..."
        ]

        # Draw help window
        try:
            for i, line in enumerate(help_msg[:10]):
                self.stdscr.addstr(2 + i, 5, line[:width-10])
        except curses.error:
            pass

        self.stdscr.refresh()

        # Wait for keypress
        while True:
            try:
                c = self.stdscr.getch(100)
                if c != -1:
                    break
            except curses.error:
                break


def load_test_file(ui):
    """Load test file"""
    test_dir = Path(__file__).parent / "test"
    if not test_dir.exists():
        ui.refresh_status("Test directory not found: ./test")
        return

    for wav_file in sorted(test_dir.glob("*.wav")):
        track = Track(path=str(wav_file), title=wav_file.name)
        ui.playlist.append(track)

    ui.refresh_status(f"Loaded {len(ui.playlist)} test file(s)")


def main(stdscr):
    """Main function"""
    # Set noecho mode
    curses.noecho()
    # Enable keypad
    stdscr.keypad(True)
    # Hide cursor
    curses.curs_set(0)

    # Create and run UI
    ui = TerminalUI(stdscr)

    try:
        import player as pm
        ui.player = pm.create_manager()

        # Auto-scan for media files in current directory
        scan_directory(ui, "current")

        # If no files found, try test directory
        if not ui.playlist:
            load_test_file(ui)

        ui.run()

    except Exception as e:
        stdscr.addstr(0, 0, f"Error: {e}")
        stdscr.refresh()
        time.sleep(2)

    finally:
        curses.echo()
        curses.curs_set(1)


def scan_directory(ui, location):
    """Scan media files"""
    if ui.player is None:
        import player as pm
        ui.player = pm.create_manager()

    paths = {
        "current": os.getcwd(),
        "~": str(Path.home()),
        "~/Music": str(Path.home() / "Music"),
        "~/Videos": str(Path.home() / "Videos"),
    }

    scan_path = paths.get(location, ".")

    if not Path(scan_path).exists():
        ui.refresh_status(f"Directory does not exist: {scan_path}")
        return

    supported_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.avi', '.mp4', '.mkv', '.mov'}

    for root, dirs, files in os.walk(scan_path):
        if any(skip_dir in root.lower() for skip_dir in ['node_modules', '.git', '__pycache__']):
            continue
        for file in sorted(files):
            ext = Path(file).suffix.lower()
            if ext in supported_exts:
                track = Track(path=os.path.join(root, file), title=file)
                ui.playlist.append(track)

    ui.refresh_status(f"Scanned {location}: found {len(ui.playlist)} media files")


if __name__ == "__main__":
    curses.wrapper(main)
