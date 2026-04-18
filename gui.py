#!/usr/bin/env python3
"""
PyPlayer - 基于 Tkinter 的图形用户界面
支持 MP3, WAV, AVI, MP4, MKV 等常见音视频格式
跨平台（Windows/Linux/macOS）
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sys
from pathlib import Path
from threading import Thread
import time


class PyPlayerGUI:
    """PyPlayer 图形界面播放器"""

    COLORS = {
        'primary': '#2196F3',
        'secondary': '#4CAF50',
        'background': '#f5f5f5',
        'panel': '#ffffff',
        'text': '#333333'
    }

    def __init__(self, root):
        self.root = root
        self.root.title("PyPlayer v1.0")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        # Import player module
        try:
            import player as pm
            self.player = pm.create_manager()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to initialize player: {e}")
            sys.exit(1)

        self.playlist = []  # List of Track objects
        self.current_index = -1
        self.selected_index = -1
        self.isPlaying = False
        self.isPaused = False

        self._setup_ui()
        self._scan_directory("current")

    def _setup_ui(self):
        """Setup the UI elements"""
        self.root.configure(bg=self.COLORS['background'])

        # Title bar
        title_frame = ttk.Frame(self.root, padding="10")
        title_frame.pack(fill=tk.X)
        title_label = ttk.Label(title_frame, text="=== PyPlayer Music/Video Player ===",
                                font=('Arial', 16, 'bold'))
        title_label.pack()

        # Status bar
        self.status_var = tk.StringVar(value="Ready - Press Space to play or click files")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               font=('Arial', 10), foreground='gray')
        status_bar.pack(fill=tk.X, padx=10, pady=(5, 10))

        # Playlist container
        playlist_frame = ttk.Frame(self.root, padding="10")
        playlist_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(playlist_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(toolbar, text="Open File(s)", command=self._open_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear Playlist", command=self._clear_playlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Scan Directory", command=lambda: self._scan_directory("current")).pack(side=tk.LEFT, padx=2)

        # Playlist listbox with scrollbar
        list_frame = ttk.Frame(playlist_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.playlist_box = tk.Listbox(list_frame, selectmode=tk.SINGLE, font=('Consolas', 10),
                                       yscrollcommand=scrollbar.set, bg=self.COLORS['panel'])
        self.playlist_box.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar.config(command=self.playlist_box.yview)

        self.playlist_box.bind('<<ListboxSelect>>', self._on_select)
        self.playlist_box.bind('<Double-Button-1>', self._on_double_click)

        # Control buttons
        controls = ttk.Frame(self.root, padding="10")
        controls.pack(fill=tk.X)

        btn_frame = ttk.Frame(controls)
        btn_frame.pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="< Prev", command=self._prev_track).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Play/Pause", command=self._toggle_play_pause).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Stop", command=self._stop).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Next >", command=self._next_track).pack(side=tk.LEFT, padx=2)

        # Volume slider
        vol_frame = ttk.Frame(controls)
        vol_frame.pack(side=tk.RIGHT)
        ttk.Label(vol_frame, text="Volume:").pack(side=tk.LEFT)
        self.volume_var = tk.IntVar(value=80)
        self.volume_slider = ttk.Scale(vol_frame, from_=0, to=100, variable=self.volume_var,
                                       command=self._set_volume)
        self.volume_slider.pack(side=tk.LEFT)

        # Keyboard bindings
        self.root.bind('<space>', lambda e: self._toggle_play_pause())
        self.root.bind('<n>', lambda e: self._next_track())
        self.root.bind('<m>', lambda e: self._prev_track())
        self.root.bind('<s>', lambda e: self._stop())
        self.root.bind('<o>', lambda e: self._open_files())

    def _scan_directory(self, location):
        """Scan directory for media files"""
        import player as pm

        paths = {
            "current": str(Path.cwd()),
            "~": str(Path.home()),
        }

        scan_path = paths.get(location, ".")
        if not Path(scan_path).exists():
            self.status_var.set(f"Directory does not exist: {scan_path}")
            return

        supported_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac',
                          '.avi', '.mp4', '.mkv', '.mov'}

        for root, dirs, files in os.walk(scan_path):
            if any(skip_dir in root.lower() for skip_dir in ['node_modules', '.git', '__pycache__']):
                continue
            for file in sorted(files):
                ext = Path(file).suffix.lower()
                if ext in supported_exts:
                    track = pm.Track(path=os.path.join(root, file), title=file)
                    self.playlist.append(track)

        self._update_playlist_display()
        self.status_var.set(f"Found {len(self.playlist)} media files")

    def _open_files(self):
        """Open files dialog"""
        files = filedialog.askopenfilenames(
            title="Select media files",
            filetypes=[
                ("Media Files", "*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.avi *.mp4 *.mkv *.mov"),
                ("All Files", "*.*")
            ]
        )

        if files:
            import player as pm
            for filepath in files:
                track = pm.Track(path=filepath, title=Path(filepath).name)
                self.playlist.append(track)
            self._update_playlist_display()
            # Auto-play first new file
            idx = len(self.playlist) - len(files)
            self.current_index = idx
            self.selected_index = idx
            if self.player.play(filepath):
                self.status_var.set(f"Now playing: {Path(filepath).name}")

    def _clear_playlist(self):
        """Clear the playlist"""
        import player as pm
        self.playlist.clear()
        self.current_index = -1
        self.selected_index = -1
        self._update_playlist_display()
        self.player.stop()
        self.status_var.set("Playlist cleared")

    def _update_playlist_display(self):
        """Update the playlist display"""
        self.playlist_box.delete(0, tk.END)
        for i, track in enumerate(self.playlist):
            indicator = "[NOW]" if i == self.current_index else "  "
            mark = ">>" if i == self.selected_index else "  "
            self.playlist_box.insert(tk.END, f"{indicator} {mark} {track.title}")

        # Update selection
        self.playlist_box.selection_clear(0, tk.END)
        if 0 <= self.current_index < len(self.playlist):
            self.playlist_box.selection_set(self.current_index)
            self.playlist_box.see(self.current_index)

    def _on_select(self, event):
        """Handle playlist selection"""
        selection = self.playlist_box.curselection()
        if selection:
            self.selected_index = selection[0]

    def _on_double_click(self, event):
        """Handle double-click on playlist item"""
        selection = self.playlist_box.curselection()
        if selection and self.playlist:
            idx = selection[0]
            self.current_index = idx
            track = self.playlist[idx]
            self._update_playlist_display()
            result = self.player.play(track.path)
            if result:
                self.status_var.set(f"Now playing: {track.title}")

    def _toggle_play_pause(self):
        """Toggle play/pause"""
        if not self.playlist:
            return

        status = self.player.get_status()
        if not status['current_track']:
            # Start playing selected track or first track
            idx = self.selected_index if 0 <= self.selected_index < len(self.playlist) else 0
            self.current_index = idx
            track = self.playlist[idx]
            result = self.player.play(track.path)
            if result:
                self.status_var.set(f"Now playing: {track.title}")
        elif status['paused']:
            self.player.resume()
            self.isPaused = False
            self.status_var.set("Playing")
        else:
            self.player.pause()
            self.isPaused = True
            self.status_var.set("Paused")

    def _stop(self):
        """Stop playback"""
        self.player.stop()
        self.isPlaying = False
        self.isPaused = False
        self.current_index = -1
        self._update_playlist_display()
        self.status_var.set("Playback stopped")

    def _next_track(self):
        """Play next track"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index + 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.status_var.set(f"Now playing: {track.title}")
        self._update_playlist_display()

    def _prev_track(self):
        """Play previous track"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index - 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.status_var.set(f"Now playing: {track.title}")
        self._update_playlist_display()

    def _set_volume(self, value):
        """Set volume (for audio files only)"""
        pass  # Volume control could be added for future versions


def run_gui():
    """Run the GUI application"""
    root = tk.Tk()
    app = PyPlayerGUI(root)

    # Run periodic status check in a separate thread
    def update_loop():
        while True:
            try:
                time.sleep(0.1)
                if not hasattr(app, 'player') or app.player is None:
                    continue
                status = app.player.get_status()
                if status['current_track'] and app.current_index < 0:
                    # Find the current playing track index
                    for i, track in enumerate(app.playlist):
                        if Path(track.path).name == status['current_track']:
                            app.current_index = i
                            break
            except Exception as e:
                pass

    # Start update thread (will be stopped when GUI closes)
    updater_thread = Thread(target=update_loop, daemon=True)
    updater_thread.start()

    root.mainloop()


if __name__ == "__main__":
    run_gui()
