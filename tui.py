#!/usr/bin/env python3
"""
PyPlayer - 基于 curses/ncurses 的终端用户界面
支持 MP3, WAV, AVI, MP4, MKV 等常见音视频格式
"""

import curses
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import time


@dataclass
class Track:
    """播放列表项"""
    path: str
    title: str
    duration: float = 0.0

    def __str__(self):
        return self.title


class TerminalUI:
    """基于 curses 的终端用户界面"""

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
        self.status_message = "PyPlayer - Press 'h' for help"
        self.running = True

        # 初始化颜色
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
        """设置播放器实例"""
        self.player = player

    def refresh_status(self, msg: str):
        """更新状态信息"""
        self.status_message = msg

    def draw_header(self):
        """绘制头部"""
        height, width = self.stdscr.getmaxyx()

        try:
            title = "=== PyPlayer Music/Video Player ==="
            self.stdscr.attron(self.COLORS['header'])
            self.stdscr.addstr(0, 0, f"{title:^{width}}")
            self.stdscr.attroff(self.COLORS['header'])

            # 显示当前状态
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
        """绘制播放列表"""
        height, width = self.stdscr.getmaxyx()
        start_row = 3

        if not self.playlist:
            try:
                self.stdscr.attron(self.COLORS['error'])
                self.stdscr.addstr(start_row, 2, "No files in playlist. Press 'o' to open file(s)")
                self.stdscr.attroff(self.COLORS['error'])
            except curses.error:
                pass
            return

        visible_lines = min(height - start_row - 3, len(self.playlist))
        scroll_start = max(0, self.selected_index - visible_lines // 2)
        scroll_end = min(scroll_start + visible_lines, len(self.playlist))

        for i in range(scroll_start, scroll_end):
            row = start_row + (i - scroll_start)
            track = self.playlist[i]

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
                line = f"{indicator} {track.title}"[:width-5]
                self.stdscr.attron(attr)
                self.stdscr.addstr(row, 2, line.ljust(width-4))
                self.stdscr.attroff(attr)
            except curses.error:
                pass

    def draw_footer(self):
        """绘制底部"""
        height, width = self.stdscr.getmaxyx()
        row = height - 2

        # 状态栏
        try:
            status_text = f" {self.status_message}"[:width-4]
            self.stdscr.attron(self.COLORS['footer'])
            self.stdscr.addstr(row, 0, f"{status_text:<{width}}")
            self.stdscr.attroff(self.COLORS['footer'])

            # 控制提示
            help_text = " [SPACE]=Play/Pause | N=Next | M=Prev | S=Stop | O=Open | Q=Quit"[:width-4]
            self.stdscr.attron(curses.color_pair(2) | curses.A_DIM)
            self.stdscr.addstr(row+1, 0, f"{help_text:<{width}}")
            self.stdscr.attroff(curses.color_pair(2) | curses.A_DIM)
        except curses.error:
            pass

    def draw(self):
        """绘制整个界面"""
        self.stdscr.clear()
        self.draw_header()
        self.draw_playlist()
        self.draw_footer()
        self.stdscr.refresh()

    def run(self):
        """主循环"""
        while self.running:
            self.draw()

            # 读取按键（带超时）
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
            elif key in [curses.KEY_UP, 258]:
                self.selected_index = max(0, self.selected_index - 1)
            elif key in [curses.KEY_DOWN, 259]:
                self.selected_index = min(len(self.playlist) - 1, self.selected_index + 1)

    def _handle_play_pause(self):
        """处理播放/暂停"""
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
        """处理停止"""
        if not self.player:
            return

        self.player.stop()
        self.refresh_status("Playback stopped")

    def _handle_next(self):
        """处理下一首"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index + 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.refresh_status(f"Now playing: {track.title}")

    def _handle_prev(self):
        """处理上一首"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index - 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.refresh_status(f"Now playing: {track.title}")

    def _handle_open(self):
        """处理打开文件"""
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

        except Exception as e:
            self.refresh_status(f"Error opening file: {e}")

    def show_help(self):
        """显示帮助信息"""
        height, width = self.stdscr.getmaxyx()
        help_msg = [
            "=== PyPlayer Controls ===",
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
    """加载测试文件"""
    test_dir = Path(__file__).parent / "test"
    if not test_dir.exists():
        ui.refresh_status("Test directory not found: ./test")
        return

    for wav_file in sorted(test_dir.glob("*.wav")):
        track = Track(path=str(wav_file), title=wav_file.name)
        ui.playlist.append(track)

    ui.refresh_status(f"Loaded {len(ui.playlist)} test file(s)")


def main(stdscr):
    """主函数"""
    # 设置 noecho mode
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
    """扫描媒体文件"""
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
