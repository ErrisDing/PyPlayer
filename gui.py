#!/usr/bin/env python3
"""
PyPlayer - Tkinter-based graphical user interface
Supports common audio/video formats: MP3, WAV, AVI, MP4, MKV, etc.
Cross-platform (Windows/Linux/macOS)
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sys
from pathlib import Path
from threading import Thread
import time
from typing import Optional
import i18n


class PyPlayerGUI:
    """PyPlayer graphical interface player"""

    COLORS = {
        'primary': '#2196F3',
        'secondary': '#4CAF50',
        'background': '#f5f5f5',
        'panel': '#ffffff',
        'text': '#333333'
    }

    def __init__(self, root):
        self.root = root
        i18n.detect_init()  # Ensure locale is initialized
        self.root.title(i18n.get('window.title'))
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        # Import player module
        try:
            import player as pm
            self.player = pm.create_manager()
        except (ImportError, AttributeError, RuntimeError) as e:
            messagebox.showerror(
                i18n.dialog('dialog.title.error'),
                i18n.dialog('dialog.error.init_player', error=str(e))
            )
            sys.exit(1)

        # Initialize SettingsManager for library management
        try:
            from config import SettingsManager
            self.settings_manager = SettingsManager()
        except (ImportError, AttributeError, OSError, IOError) as e:
            messagebox.showwarning(
                i18n.dialog('dialog.title.warning'),
                i18n.dialog('dialog.warning.init_settings', error=str(e))
            )
            self.settings_manager = None

        self.playlist = []  # List of Track objects
        self.current_index = -1
        self.selected_index = -1
        self.isPlaying = False
        self.isPaused = False

        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI elements"""
        self.root.configure(bg=self.COLORS['background'])

        # Title bar
        title_frame = ttk.Frame(self.root, padding="10")
        title_frame.pack(fill=tk.X)
        title_label = ttk.Label(title_frame, text=i18n.get('main.title'),
                                font=('Arial', 16, 'bold'))
        title_label.pack()

        # Status bar
        self.status_var = tk.StringVar(value=i18n.get('status.ready'))
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               font=('Arial', 10), foreground='gray')
        status_bar.pack(fill=tk.X, padx=10, pady=(5, 10))

        # Show library status if available
        try:
            if self.settings_manager and hasattr(self, 'settings_manager'):
                libs = self.settings_manager.settings.media_libraries
                if libs:
                    self.status_var.set(i18n.get('status.loaded_libraries', n=len(libs)))
        except AttributeError:
            pass

        # Playlist container
        playlist_frame = ttk.Frame(self.root, padding="10")
        playlist_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(playlist_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(toolbar, text=i18n.get('button.open_file'), command=self._open_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text=i18n.get('button.clear_playlist'), command=self._clear_playlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text=i18n.get('button.scan_directory'), command=lambda: self._scan_directory("current")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text=i18n.get('button.library_mgr'), command=self._show_library_manager_dialog).pack(side=tk.LEFT, padx=2)

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

        ttk.Button(btn_frame, text=i18n.get('button.prev_track'), command=self._prev_track).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=i18n.get('button.play_pause'), command=self._toggle_play_pause).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=i18n.get('button.stop'), command=self._stop).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=i18n.get('button.next_track'), command=self._next_track).pack(side=tk.LEFT, padx=2)

        # Volume slider
        vol_frame = ttk.Frame(controls)
        vol_frame.pack(side=tk.RIGHT)
        ttk.Label(vol_frame, text=i18n.get('volume.label')).pack(side=tk.LEFT)
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
        from library_manager import LibraryManager

        # When location is "current", scan configured media libraries
        if location == "current":
            manager = LibraryManager()
            result = manager.scan_all_libraries()

            if not result:
                self.status_var.set("No media libraries configured. Open Library Manager to add one.")
                return

            # Clear existing playlist and add tracks with relative paths
            self.playlist.clear()
            for lib_path, files in result.items():
                try:
                    for media_file in files:
                        # Store full path in Track, but use relative path as title for hierarchy
                        relative_title = str(Path(media_file.path).relative_to(lib_path))
                        track = pm.Track(path=media_file.path, title=relative_title)
                        self.playlist.append(track)
                except ValueError:
                    # Path is not relative to lib_path, use filename only
                    for media_file in files:
                        track = pm.Track(path=media_file.path, title=Path(media_file.path).name)
                        self.playlist.append(track)

            self._update_playlist_display()
            self.status_var.set(f"Found {len(self.playlist)} media files across {len(result)} library(ies)")
        else:
            # Original behavior for other locations
            paths = {
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
            title=i18n.get('file.title'),
            filetypes=[
                ("Media Files", "*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.avi *.mp4 *.mkv *.mov"),
                ("All Files", "*.*")
            ]
        )

        if files:
            import player as pm
            for filepath in files:
                # Use relative path from first library or just filename
                title = Path(filepath).name
                if self.settings_manager and self.settings_manager.settings.media_libraries:
                    try:
                        lib_path = self.settings_manager.settings.media_libraries[0].path
                        title = str(Path(filepath).relative_to(lib_path))
                    except ValueError:
                        title = Path(filepath).name
                track = pm.Track(path=filepath, title=title)
                self.playlist.append(track)
            self._update_playlist_display()
            # Auto-play first new file
            idx = len(self.playlist) - len(files)
            self.current_index = idx
            self.selected_index = idx
            if self.player.play(filepath):
                self.status_var.set(i18n.get('status.now_playing', title=Path(filepath).name))

    def _clear_playlist(self):
        """Clear the playlist"""
        import player as pm
        self.playlist.clear()
        self.current_index = -1
        self.selected_index = -1
        self._update_playlist_display()
        self.player.stop()
        self.status_var.set(i18n.get('status.playlist_cleared'))

    def _update_playlist_display(self):
        """Update the playlist display with hierarchical structure using full paths"""
        from library_manager import _HierarchicalPlaylist

        # Build hierarchy from playlist using full paths
        hier = _HierarchicalPlaylist()
        for track in self.playlist:
            rel_title = self._get_relative_title(track.path)
            hier.add_track(track.path, rel_title)

        display_items = hier.build_display_list()

        self.playlist_box.delete(0, tk.END)
        for display_text, _track_info in display_items:
            self.playlist_box.insert(tk.END, display_text)

        # Restore selection if still valid
        self.playlist_box.selection_clear(0, tk.END)

    def _get_relative_title(self, filepath):
        """Get relative title for a track path.

        Tries to compute relative path from library root, falls back to filename or full path.
        """
        try:
            if not self.settings_manager or not self.settings_manager.settings.media_libraries:
                return Path(filepath).name
            lib_path = self.settings_manager.settings.media_libraries[0].path
            return str(Path(filepath).relative_to(lib_path))
        except ValueError:
            # Track is outside the library root, use filename with drive prefix if on Windows
            p = Path(filepath)
            return f"{p.drive or ''}{p.name}" if hasattr(p, 'drive') and p.drive else p.name

    def _on_select(self, event):
        """Handle playlist selection"""
        selection = self.playlist_box.curselection()
        if selection:
            self.selected_index = selection[0]

    def _get_track_info_from_display_idx(self, display_idx: int) -> Optional[dict]:
        """Map a display index back to track info dict containing path and type.

        Args:
            display_idx: Index in the displayed playlist

        Returns:
            Track info dict with keys: 'is_folder', 'path', 'title', or None if invalid index
        """
        from library_manager import _HierarchicalPlaylist

        hier = _HierarchicalPlaylist()
        for track in self.playlist:
            rel_title = self._get_relative_title(track.path)
            hier.add_track(track.path, rel_title)

        display_items = hier.build_display_list()
        if 0 <= display_idx < len(display_items):
            _, track_info = display_items[display_idx]
            return track_info
        return None

    def _get_track_from_display_idx(self, display_idx: int):
        """Get Track object from a display index.

        Args:
            display_idx: Index in the displayed playlist

        Returns:
            Track object or None if invalid index
        """
        track_info = self._get_track_info_from_display_idx(display_idx)
        if not track_info:
            return None

        # For folders, return first file in that folder; for files return the actual track
        is_folder = track_info.get('is_folder', False)

        # Build hierarchy once outside the loop - optimize from previous method
        from library_manager import _HierarchicalPlaylist
        hier = _HierarchicalPlaylist()
        for t in self.playlist:
            t_rel = self._get_relative_title(t.path)
            hier.add_track(t.path, t_rel)

        items = hier.build_display_list()

        # Try to match by full_path from track_info
        if track_info.get('full_path'):
            for i, (display_text, info) in enumerate(items):
                if i < len(items) and info.get('full_path') == track_info.get('path'):
                    return self.playlist[i]

        # Fallback: find by matching display title
        for track in self.playlist:
            if str(Path(track.path).name) == track_info.get('title'):
                return track

        return None

    def _on_double_click(self, event):
        """Handle double-click on playlist item.

        For folders (marked with [D]), triggers batch playback of all files in that folder.
        For files (marked with [F]), plays the selected file.
        """
        try:
            selection = self.playlist_box.curselection()
            if not selection or not self.playlist:
                return

            idx = selection[0]
            track_info = self._get_track_info_from_display_idx(idx)

            if not track_info:
                return

            display_text = self.playlist_box.get(idx)
            is_folder = track_info.get('is_folder', False)
            folder_path = track_info.get('path')

            # Handle folder click - batch playback of all files in folder
            if is_folder and folder_path:
                folder_name = display_text.replace("[D] ", "").replace("  ", "").strip()
                self._play_folder(folder_path, folder_name)
                return

            # Handle file click (or non-folder items)
            track = self._get_track_from_display_idx(idx)
            if track:
                self.current_index = idx
                result = self.player.play(track.path)
                if result:
                    self.status_var.set(i18n.get('status.now_playing', title=track.title))
                else:
                    # Try to find by matching path/name
                    for i, t in enumerate(self.playlist):
                        if Path(t.path).name == track_info.get('title'):
                            self.current_index = i
                            result = self.player.play(t.path)
                            if result:
                                self.status_var.set(f"Now playing: {t.title}")
                            break
                self._update_playlist_display()
        except (OSError, IOError, AttributeError, RuntimeError) as e:
            self.status_var.set(f"Error on double-click: {e}")

    def _play_folder(self, folder_path: str, folder_name: str):
        """Play all files in a folder starting with the first one.

        Args:
            folder_path: Full path to the folder
            folder_name: Display name of the folder (used for status message)
        """
        # Find all tracks in this folder - normalize paths for comparison
        folder_norm = folder_path.replace('\\', '/')

        def is_in_folder(track_path):
            track_norm = str(Path(track_path)).replace('\\', '/')
            return track_norm.startswith(folder_norm + '/') or track_norm == folder_norm

        folder_tracks = [t for t in self.playlist if is_in_folder(t.path)]

        if not folder_tracks:
            return

        # Sort by path to maintain consistent order
        folder_tracks.sort(key=lambda t: t.path)

        # Play the first track
        first_track = folder_tracks[0]
        self.current_index = self.playlist.index(first_track) if first_track in self.playlist else -1

        result = self.player.play(first_track.path)
        if result:
            self.status_var.set(i18n.get('status.now_playing', title=f"folder: {folder_name}"))

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
                self.status_var.set(i18n.get('status.now_playing', title=track.title))
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
        self.status_var.set(i18n.get('status.stopped'))

    def _next_track(self):
        """Play next track"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index + 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.status_var.set(i18n.get('status.now_playing', title=track.title))
        self._update_playlist_display()

    def _prev_track(self):
        """Play previous track"""
        if not self.playlist or len(self.playlist) < 2:
            return

        self.current_index = (self.current_index - 1) % len(self.playlist)
        track = self.playlist[self.current_index]
        result = self.player.play(track.path)
        if result:
            self.status_var.set(i18n.get('status.now_playing', title=track.title))
        self._update_playlist_display()

    def _set_volume(self, value):
        """Set volume (only effective for audio files)"""
        import player as pm
        volume = float(value) / 100.0  # Convert 0-100 to 0.0-1.0
        self.player.set_volume(volume)

    def _show_library_manager_dialog(self):
        """Show media library management dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title(i18n.dialog('dialog.title.library_management'))
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Create container frame
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(main_frame, text=i18n.dialog('dialog.title.library_management'), font=('Arial', 12, 'bold'))
        title_label.pack(anchor=tk.W, pady=(0, 5))

        # Listbox to show libraries
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.library_listbox = tk.Listbox(list_frame, font=('Consolas', 9), yscrollcommand=scrollbar.set, height=8)
        self.library_listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar.config(command=self.library_listbox.yview)

        # Update list with current libraries
        for lib in self.settings_manager.settings.media_libraries:
            name = lib.name or Path(lib.path).name
            path = lib.path
            display_text = f"{name}\n{path}"
            self.library_listbox.insert(tk.END, display_text)

        # Buttons frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text=i18n.get('button.add', default='Add'), width=8, command=self._add_library).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=i18n.get('button.delete', default='Delete'), width=8, command=lambda: self._remove_library(self.library_listbox)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=i18n.get('button.scan_directory', default='Scan All'), width=8, command=self._scan_libraries).pack(side=tk.LEFT, padx=2)

        # Close button
        ttk.Button(dialog, text=i18n.get('button.close', default='Close'), command=lambda: dialog.destroy()).pack(pady=(5, 0))

    def _add_library(self):
        """Add media library - open directory selection dialog"""
        path = filedialog.askdirectory(title=i18n.get('file.select_library', default="Select Library Folder"))
        if path and self.settings_manager:
            # Use folder name as default name
            dir_name = Path(path).name or "Library"
            if self.settings_manager.add_library(path, dir_name):
                messagebox.showinfo(
                    i18n.dialog('dialog.title.success'),
                    i18n.dialog('dialog.msg_added_library', name=dir_name, path=path)
                )
                # Refresh the list if dialog exists
                if hasattr(self, 'library_listbox') and self.library_listbox:
                    self.library_listbox.delete(0, tk.END)
                    for lib in self.settings_manager.settings.media_libraries:
                        name = lib.name or Path(lib.path).name
                        display_text = f"{name}\n{lib.path}"
                        self.library_listbox.insert(tk.END, display_text)
            else:
                messagebox.showerror(
                    i18n.dialog('dialog.title.error'),
                    i18n.dialog('dialog.add_failed', default="Failed to add library")
                )

    def _remove_library(self, listbox):
        """Delete selected media library"""
        selection = listbox.curselection() if listbox else []
        if not selection and not hasattr(self, 'library_listbox'):
            return

        idx = selection[0] if selection else self.library_listbox.curselection()[0] if self.library_listbox else -1
        if idx < 0:
            messagebox.showwarning(
                i18n.dialog('dialog.title.warning'),
                i18n.dialog('dialog.select_library_delete', default="Please select a library to delete")
            )
            return

        lib = self.settings_manager.settings.media_libraries[idx]
        if messagebox.askyesno(
            i18n.dialog('dialog.title.confirm'),
            i18n.dialog('dialog.confirm_delete_media_lib', path=lib.path)
        ):
            if self.settings_manager.remove_library(lib.path):
                messagebox.showinfo(i18n.dialog('dialog.title.success'), i18n.get('library_removed'))
                # Refresh list
                self.library_listbox.delete(0, tk.END)
                for lib in self.settings_manager.settings.media_libraries:
                    name = lib.name or Path(lib.path).name
                    display_text = f"{name}\n{lib.path}"
                    self.library_listbox.insert(tk.END, display_text)

    def _scan_libraries(self):
        """Scan all media libraries"""
        import player as pm

        from library_manager import LibraryManager
        manager = LibraryManager()
        result = manager.scan_all_libraries()

        total_files = sum(len(files) for files in result.values())

        msg = f"{i18n.dialog('dialog.scan_complete_msg')}\n"
        for path, files in result.items():
            if files:
                name = Path(path).name
                msg += f"\n{name}: {len(files)} files"
        msg += f"\n\nTotal: {total_files} files"

        messagebox.showinfo(i18n.dialog('dialog.scan_results'), msg)


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
            except AttributeError:
                pass

    # Start update thread (will be stopped when GUI closes)
    updater_thread = Thread(target=update_loop, daemon=True)
    updater_thread.start()

    root.mainloop()


if __name__ == "__main__":
    run_gui()
