#!/usr/bin/env python3
"""
PyPlayer - Tkinter-based graphical user interface
Supports common audio/video formats: MP3, WAV, AVI, MP4, MKV, etc.
Cross-platform (Windows/Linux/macOS)
"""

import io
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Thread
from tkinter import ttk, filedialog, messagebox
from typing import Optional

import i18n

# Try to import PIL for album art display
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Default cover path
DEFAULT_COVER_PATH = Path(__file__).parent / "resource" / "default_cover.png"


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

        # QueueNode architecture - replaces flat playlist
        from library_manager import DisplayIndexMap
        self.queue_nodes = []  # List of QueueNode (FileNode or FolderNode)
        self.display_map = DisplayIndexMap()  # Maps display indices to queue nodes
        self.current_node_idx: int = -1  # Current playing node index
        self.current_sub_index: int = -1  # Current track index within a folder node

        # Legacy compatibility - self.playlist can still be accessed but maps to queue_nodes
        self.current_index = -1
        self.selected_index = -1

        self._setup_ui()

    @property
    def isPlaying(self) -> bool:
        """Backward-compatible property that delegates to audio player state."""
        return self.player.audio_player.is_playing

    @property
    def isPaused(self) -> bool:
        """Backward-compatible property that delegates to audio player state."""
        return self.player.audio_player.is_paused

    @property
    def playlist(self):
        """Backward-compatible access to flat track list from queue_nodes."""
        tracks = []
        for node in self.queue_nodes:
            tracks.extend(node.get_tracks())
        return tracks

    @playlist.setter
    def playlist(self, value):
        """Setter for backward compatibility - converts to FileNodes."""
        from library_manager import FileNode
        import player as pm
        self.queue_nodes = []
        for track in value:
            node = FileNode(track=track, display_text=track.title, path=track.path)
            self.queue_nodes.append(node)

    def _configure_styles(self):
        """Configure ttk styles for a more modern look."""
        style = ttk.Style()
        style.theme_use('clam')  # Use clam theme as base

        # Configure colors
        style.configure('TFrame', background=self.COLORS['background'])
        style.configure('TLabel', background=self.COLORS['background'], foreground=self.COLORS['text'])
        style.configure('TButton', padding=5)
        style.configure('NowPlaying.TFrame', background=self.COLORS['panel'], relief='solid', borderwidth=1)
        style.configure('NowPlaying.TLabel', background=self.COLORS['panel'], foreground=self.COLORS['text'])

    def _create_now_playing_panel(self):
        """Create the Now Playing panel with album art and metadata."""
        # Now Playing container
        now_playing_frame = ttk.Frame(self.root, padding="10", style='NowPlaying.TFrame')
        now_playing_frame.pack(fill=tk.X, padx=10, pady=5)

        # Left side: Album art
        self.album_art_frame = ttk.Frame(now_playing_frame, padding="5")
        self.album_art_frame.pack(side=tk.LEFT, padx=(0, 10))

        # Default placeholder image (100x100 gray square)
        self.default_album_art = None
        self.album_art_label = ttk.Label(self.album_art_frame, text="")
        self.album_art_label.pack()
        self._set_default_album_art()

        # Right side: Metadata
        metadata_frame = ttk.Frame(now_playing_frame, padding="5")
        metadata_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Song title (large font)
        self.song_title_var = tk.StringVar(value=i18n.get('metadata.no_track', default='No track playing'))
        self.song_title_label = ttk.Label(
            metadata_frame,
            textvariable=self.song_title_var,
            font=('Arial', 14, 'bold'),
            style='NowPlaying.TLabel'
        )
        self.song_title_label.pack(anchor=tk.W, pady=(0, 5))

        # Artist (secondary)
        self.artist_var = tk.StringVar(value="")
        self.artist_label = ttk.Label(
            metadata_frame,
            textvariable=self.artist_var,
            font=('Arial', 11),
            foreground='#666666',
            style='NowPlaying.TLabel'
        )
        self.artist_label.pack(anchor=tk.W, pady=(0, 2))

        # Album (secondary)
        self.album_var = tk.StringVar(value="")
        self.album_label = ttk.Label(
            metadata_frame,
            textvariable=self.album_var,
            font=('Arial', 10),
            foreground='#888888',
            style='NowPlaying.TLabel'
        )
        self.album_label.pack(anchor=tk.W)

    def _set_default_album_art(self):
        """Set default placeholder for album art."""
        if PIL_AVAILABLE:
            # Try to load default cover image
            if DEFAULT_COVER_PATH.exists():
                try:
                    img = Image.open(DEFAULT_COVER_PATH)
                    img.thumbnail((100, 100), Image.Resampling.LANCZOS)
                    # Create square canvas if needed
                    canvas = Image.new('RGB', (100, 100), color='#ffffff')
                    offset = ((100 - img.width) // 2, (100 - img.height) // 2)
                    if img.mode == 'RGBA':
                        canvas.paste(img, offset, mask=img.split()[3])
                    else:
                        canvas.paste(img, offset)
                    self.default_album_art = ImageTk.PhotoImage(canvas)
                    self.album_art_label.configure(image=self.default_album_art)
                    return
                except Exception as e:
                    print(f"Warning: Failed to load default cover: {e}")
            # Fallback: create a gray placeholder image
            img = Image.new('RGB', (100, 100), color='#cccccc')
            self.default_album_art = ImageTk.PhotoImage(img)
            self.album_art_label.configure(image=self.default_album_art)
        else:
            self.album_art_label.configure(text="[No Art]")

    def _update_album_art(self, album_art_bytes: Optional[bytes]):
        """Update album art display.

        Args:
            album_art_bytes: Raw image data from metadata, or None for default
        """
        if not PIL_AVAILABLE:
            self.album_art_label.configure(text="[No PIL]")
            return

        if album_art_bytes is None:
            self._set_default_album_art()
            return

        try:
            # Load image from bytes
            img = Image.open(io.BytesIO(album_art_bytes))

            # Resize to 100x100 maintaining aspect ratio
            img.thumbnail((100, 100), Image.Resampling.LANCZOS)

            # Create square canvas with padding if needed
            canvas = Image.new('RGB', (100, 100), color='#ffffff')
            offset = ((100 - img.width) // 2, (100 - img.height) // 2)
            canvas.paste(img, offset)

            self.current_album_art = ImageTk.PhotoImage(canvas)
            self.album_art_label.configure(image=self.current_album_art)
        except Exception:
            self._set_default_album_art()

    def _create_progress_panel(self):
        """Create progress bar with time displays."""
        progress_frame = ttk.Frame(self.root, padding="10")
        progress_frame.pack(fill=tk.X)

        # Current time (left)
        self.current_time_var = tk.StringVar(value="0:00")
        current_time_label = ttk.Label(
            progress_frame,
            textvariable=self.current_time_var,
            font=('Consolas', 10)
        )
        current_time_label.pack(side=tk.LEFT)

        # Progress slider (middle)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_slider = ttk.Scale(
            progress_frame,
            from_=0.0,
            to=100.0,
            variable=self.progress_var,
            orient=tk.HORIZONTAL,
            command=self._on_progress_change
        )
        self.progress_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # Total duration (right)
        self.total_time_var = tk.StringVar(value="0:00")
        total_time_label = ttk.Label(
            progress_frame,
            textvariable=self.total_time_var,
            font=('Consolas', 10)
        )
        total_time_label.pack(side=tk.RIGHT)

        # Progress update state
        self._progress_dragging = False
        self._progress_update_enabled = True

    def _format_time(self, seconds: float) -> str:
        """Format seconds to M:SS or H:MM:SS format.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted time string
        """
        if seconds < 0:
            seconds = 0

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"

    def _on_progress_change(self, value):
        """Handle progress slider drag."""
        self._progress_dragging = True

    def _on_progress_release(self, event):
        """Handle progress slider release to seek."""
        if not self._progress_dragging:
            return

        self._progress_dragging = False

        # Calculate target position
        target_position = float(self.progress_var.get())

        # Seek to position
        if hasattr(self.player.audio_player, 'seek'):
            success = self.player.audio_player.seek(target_position)
            if not success:
                # Seek not supported for this format
                pass

    def _update_progress(self):
        """Update progress bar and time displays (called periodically)."""
        if not self._progress_update_enabled:
            self.root.after(250, self._update_progress)
            return

        try:
            # Get current position and duration
            if hasattr(self.player.audio_player, 'get_position'):
                position = self.player.audio_player.get_position()
                duration = self.player.audio_player.get_duration()

                if duration > 0 and not self._progress_dragging:
                    # Update slider range and value
                    self.progress_slider.configure(to=duration)
                    self.progress_var.set(position)

                    # Update time displays
                    self.current_time_var.set(self._format_time(position))
                    self.total_time_var.set(self._format_time(duration))
                elif duration <= 0:
                    self.current_time_var.set("0:00")
                    self.total_time_var.set("0:00")
        except Exception:
            pass

        # Schedule next update
        self.root.after(250, self._update_progress)

    def _update_now_playing(self, track):
        """Update Now Playing panel with track metadata.

        Args:
            track: Track object with metadata
        """
        if track is None:
            self.song_title_var.set(i18n.get('metadata.no_track', default='No track playing'))
            self.artist_var.set("")
            self.album_var.set("")
            self._update_album_art(None)
            return

        # Update title
        title = track.title if track.title else Path(track.path).stem
        self.song_title_var.set(title)

        # Update artist
        artist = getattr(track, 'artist', None)
        if artist and artist != "Unknown Artist":
            self.artist_var.set(artist)
        else:
            self.artist_var.set("")

        # Update album
        album = getattr(track, 'album', None)
        if album and album != "Unknown Album":
            self.album_var.set(album)
        else:
            self.album_var.set("")

    def _update_now_playing_with_art(self, filepath: str):
        """Update Now Playing panel with track metadata including album art.

        Args:
            filepath: Path to the audio file
        """
        try:
            from metadata import extract_metadata
            metadata = extract_metadata(filepath)

            # Update title
            self.song_title_var.set(metadata.title)

            # Update artist
            if metadata.artist and metadata.artist != "Unknown Artist":
                self.artist_var.set(metadata.artist)
            else:
                self.artist_var.set("")

            # Update album
            if metadata.album and metadata.album != "Unknown Album":
                self.album_var.set(metadata.album)
            else:
                self.album_var.set("")

            # Update album art
            self._update_album_art(metadata.album_art)
        except Exception as e:
            # Fallback to basic display
            self.song_title_var.set(Path(filepath).stem)
            self.artist_var.set("")
            self.album_var.set("")
            self._update_album_art(None)

    def _setup_ui(self):
        """Setup the UI elements"""
        self.root.configure(bg=self.COLORS['background'])

        # Configure ttk styles
        self._configure_styles()

        # Title bar
        title_frame = ttk.Frame(self.root, padding="10")
        title_frame.pack(fill=tk.X)
        title_label = ttk.Label(title_frame, text=i18n.get('main.title'),
                                font=('Arial', 16, 'bold'))
        title_label.pack()

        # Now Playing panel (album art + metadata)
        self._create_now_playing_panel()

        # Progress bar and timer
        self._create_progress_panel()

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
        ttk.Button(btn_frame, text=i18n.get('button.next_track'), command=self._next_track).pack(side=tk.LEFT, padx=2)

        # Volume slider
        vol_frame = ttk.Frame(controls)
        vol_frame.pack(side=tk.RIGHT)
        ttk.Label(vol_frame, text=i18n.get('volume.label')).pack(side=tk.LEFT)
        self.volume_var = tk.IntVar(value=80)
        self.volume_slider = ttk.Scale(vol_frame, from_=0, to=100, variable=self.volume_var,
                                       command=self._set_volume)
        self.volume_slider.pack(side=tk.LEFT)

        # Bind progress slider release event
        self.progress_slider.bind('<ButtonRelease-1>', self._on_progress_release)

        # Start progress update loop
        self.root.after(250, self._update_progress)

        # Keyboard bindings
        self.root.bind('<space>', lambda e: self._toggle_play_pause())
        self.root.bind('<n>', lambda e: self._next_track())
        self.root.bind('<m>', lambda e: self._prev_track())
        self.root.bind('<o>', lambda e: self._open_files())

    def _scan_directory(self, location):
        """扫描目录并构建队列节点

        Args:
            location: "current" to scan configured libraries, or a specific path
        """
        import player as pm
        from library_manager import LibraryManager, FolderNode, FileNode

        # When location is "current", scan configured media libraries
        if location == "current":
            manager = LibraryManager()
            result = manager.scan_all_libraries()

            if not result:
                self.status_var.set("No media libraries configured. Open Library Manager to add one.")
                return

            # Build queue_nodes from scanned files, grouped by parent directory
            self.queue_nodes = []

            # Collect all scanned tracks first
            all_tracks = []
            for lib_path, files in result.items():
                try:
                    for media_file in files:
                        relative_title = str(Path(media_file.path).relative_to(lib_path))
                        track = pm.Track(path=media_file.path, title=relative_title)
                        all_tracks.append((media_file.path, track))
                except ValueError:
                    for media_file in files:
                        track = pm.Track(path=media_file.path, title=Path(media_file.path).name)
                        all_tracks.append((media_file.path, track))

            # Group by parent directory
            folder_groups: dict = {}
            for filepath, track in all_tracks:
                parent = str(Path(filepath).parent)
                if parent not in folder_groups:
                    folder_groups[parent] = []
                folder_groups[parent].append(track)

            # Create FolderNodes for each directory
            for folder_path, tracks in sorted(folder_groups.items()):
                tracks.sort(key=lambda t: t.path)
                node = FolderNode(
                    display_text=Path(folder_path).name,
                    path=folder_path,
                    tracks=tracks
                )
                self.queue_nodes.append(node)

            self._update_playlist_display()
            self.status_var.set(f"Found {len(all_tracks)} media files across {len(result)} library(ies)")
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

            # Collect tracks
            all_tracks = []
            for root, dirs, files in os.walk(scan_path):
                if any(skip_dir in root.lower() for skip_dir in ['node_modules', '.git', '__pycache__']):
                    continue
                for file in sorted(files):
                    ext = Path(file).suffix.lower()
                    if ext in supported_exts:
                        track = pm.Track(path=os.path.join(root, file), title=file)
                        all_tracks.append((os.path.join(root, file), track))

            # Group by parent directory and build FolderNodes
            folder_groups: dict = {}
            for filepath, track in all_tracks:
                parent = str(Path(filepath).parent)
                if parent not in folder_groups:
                    folder_groups[parent] = []
                folder_groups[parent].append(track)

            self.queue_nodes = []
            for folder_path, tracks in sorted(folder_groups.items()):
                tracks.sort(key=lambda t: t.path)
                node = FolderNode(
                    display_text=Path(folder_path).name,
                    path=folder_path,
                    tracks=tracks
                )
                self.queue_nodes.append(node)

            self._update_playlist_display()
            self.status_var.set(f"Found {len(all_tracks)} media files")

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
            from library_manager import FileNode

            added_count = 0
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
                node = FileNode(track=track, display_text=title, path=filepath)
                self.queue_nodes.append(node)
                added_count += 1

            self._update_playlist_display()
            # Auto-play first new file
            idx = len(self.queue_nodes) - added_count
            self.current_node_idx = idx
            self.current_sub_index = 0
            if self.player.play(filepath):
                self._update_now_playing_with_art(filepath)
                self.status_var.set(i18n.get('status.now_playing', title=Path(filepath).name))

    def _clear_playlist(self):
        """Clear the playlist"""
        self.queue_nodes = []
        self.display_map.clear()
        self.current_node_idx = -1
        self.current_sub_index = -1
        self.current_index = -1
        self.selected_index = -1
        self._update_playlist_display()
        self.player.stop()
        self.status_var.set(i18n.get('status.playlist_cleared'))

    def _update_playlist_display(self):
        """更新播放列表显示并构建索引映射

        Builds hierarchical display with folders and files, while maintaining
        a mapping from display indices to queue nodes for accurate playback.
        """
        from library_manager import _HierarchicalPlaylist, get_library_for_file

        # Clear the display map
        self.display_map.clear()

        # Get libraries for hierarchy building
        libs = self.settings_manager.settings.media_libraries if self.settings_manager else []

        # Build hierarchy with library awareness
        hier = _HierarchicalPlaylist()

        # First, collect all tracks from queue_nodes
        all_tracks = []
        for node in self.queue_nodes:
            all_tracks.extend(node.get_tracks())

        for track in all_tracks:
            lib_config = get_library_for_file(track.path, libs) if libs else None

            if lib_config:
                # Use library name from config or derive from path
                lib_name = lib_config.name or Path(lib_config.path).name
                hier.add_track(
                    full_path=track.path,
                    display_title=self._get_relative_title(track.path),
                    library_path=lib_config.path,
                    library_name=lib_name
                )
            else:
                # Fallback - use standard hierarchy with relative title
                rel_title = self._get_relative_title(track.path)
                hier.add_track(track.path, rel_title)

        display_items = hier.build_display_list()

        self.playlist_box.delete(0, tk.END)

        # Build the display_map from display_items
        for display_idx, (display_text, track_info) in enumerate(display_items):
            self.playlist_box.insert(tk.END, display_text)

            is_folder = track_info.get('is_folder', False)
            path = track_info.get('path', '')
            full_path = track_info.get('full_path', '')

            # Find matching node index in queue_nodes
            matched_node_idx = self._find_node_idx_by_path(path, is_folder, full_path)
            sub_index = -1

            if not is_folder and matched_node_idx >= 0:
                # For files, find the sub_index within the folder node
                node = self.queue_nodes[matched_node_idx]
                if node.is_folder():
                    # Find track index within folder - normalize paths for comparison
                    normalized_full_path = str(Path(full_path).resolve()) if full_path else ""
                    for i, t in enumerate(node.tracks):
                        track_path = str(Path(t.path).resolve())
                        if track_path == normalized_full_path:
                            sub_index = i
                            break
                else:
                    # Single file node - sub_index is always 0
                    sub_index = 0

            self.display_map.add_entry(
                display_idx=display_idx,
                node_idx=matched_node_idx,
                is_folder=is_folder,
                path=path,
                sub_index=sub_index,
                full_path=full_path
            )

        # Restore selection if still valid
        self.playlist_box.selection_clear(0, tk.END)

    def _find_node_idx_by_path(self, path: str, is_folder: bool, full_path: str = "") -> int:
        """Find the index of a queue node by its path.

        Args:
            path: Folder path or file parent directory
            is_folder: Whether looking for a folder node
            full_path: For files, the complete file path

        Returns:
            Node index in queue_nodes, or -1 if not found
        """
        # Normalize paths for comparison
        if path:
            path = str(Path(path).resolve())
        if full_path:
            full_path = str(Path(full_path).resolve())

        for idx, node in enumerate(self.queue_nodes):
            if is_folder:
                if node.is_folder():
                    node_path = str(Path(node.path).resolve())
                    if node_path == path:
                        return idx
            else:
                if node.is_folder():
                    # Check if file is in this folder
                    if full_path:
                        for t in node.tracks:
                            track_path = str(Path(t.path).resolve())
                            if track_path == full_path:
                                return idx
                else:
                    # FileNode - check if path matches
                    node_path = str(Path(node.path).resolve())
                    if node_path == full_path:
                        return idx
        return -1

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

    def _get_track_from_display_idx(self, display_idx: int):
        """通过显示索引获取轨道对象

        Args:
            display_idx: Index in the displayed playlist

        Returns:
            Track object or None if invalid index or folder entry
        """
        entry = self.display_map.get_by_display_idx(display_idx)
        if not entry:
            return None

        node_idx = entry['node_idx']
        if node_idx < 0 or node_idx >= len(self.queue_nodes):
            return None

        node = self.queue_nodes[node_idx]

        if entry['is_folder']:
            # Folders don't have a single track - return None
            return None

        if node.is_folder():
            sub_index = entry.get('sub_index', -1)
            if 0 <= sub_index < len(node.tracks):
                return node.tracks[sub_index]
            return None
        else:
            # FileNode - return the single track
            return node.track

    def _on_double_click(self, event):
        """双击处理：文件夹播放全部内容，文件播放单个

        For folders (marked with [D] or [ML]), triggers batch playback of all files.
        For files (marked with [F]), plays the selected file.
        """
        try:
            selection = self.playlist_box.curselection()
            if not selection or not self.queue_nodes:
                return

            display_idx = selection[0]
            entry = self.display_map.get_by_display_idx(display_idx)
            if not entry:
                return

            node_idx = entry['node_idx']
            is_folder = entry['is_folder']

            if is_folder:
                self._play_folder_node(node_idx)
            else:
                self._play_file_node(node_idx, entry.get('sub_index', 0))

        except (OSError, IOError, AttributeError, RuntimeError) as e:
            self.status_var.set(f"Error on double-click: {e}")

    def _play_folder_node(self, node_idx: int):
        """播放文件夹节点，从第一首开始

        Args:
            node_idx: Index of the FolderNode in queue_nodes
        """
        if node_idx < 0 or node_idx >= len(self.queue_nodes):
            return

        node = self.queue_nodes[node_idx]
        if not node.is_folder() or not node.tracks:
            return

        node.reset()
        node.current_sub_index = 0
        self.current_node_idx = node_idx
        self.current_sub_index = 0

        track = node.get_current_track()
        if track:
            self.player.play(track.path)
            self._update_now_playing_with_art(track.path)
            self.status_var.set(f"Playing folder: {node.display_text}")

    def _play_file_node(self, node_idx: int, sub_index: int = 0):
        """播放文件节点或文件夹内特定文件

        Args:
            node_idx: Index of the node in queue_nodes
            sub_index: For FolderNodes, the track index within the folder
        """
        if node_idx < 0 or node_idx >= len(self.queue_nodes):
            print(f"[DEBUG] Invalid node_idx: {node_idx}, queue_nodes length: {len(self.queue_nodes)}")
            return

        node = self.queue_nodes[node_idx]
        self.current_node_idx = node_idx

        if node.is_folder():
            print(f"[DEBUG] Playing from folder: {node.path}")
            print(f"[DEBUG] sub_index requested: {sub_index}")
            print(f"[DEBUG] tracks in folder: {[t.path for t in node.tracks]}")
            track = node.set_sub_index(sub_index)
            self.current_sub_index = sub_index
        else:
            track = node.track
            self.current_sub_index = 0

        if track:
            print(f"[DEBUG] Actually playing: {track.path}")
            result = self.player.play(track.path)
            if result:
                self._update_now_playing_with_art(track.path)
                self.status_var.set(i18n.get('status.now_playing', title=track.title))

    def _toggle_play_pause(self):
        """Toggle play/pause"""
        if not self.queue_nodes:
            return

        status = self.player.get_status()
        if not status['current_track']:
            # Start playing selected track or first track
            if self.selected_index >= 0:
                entry = self.display_map.get_by_display_idx(self.selected_index)
                if entry:
                    node_idx = entry['node_idx']
                    if entry['is_folder']:
                        self._play_folder_node(node_idx)
                    else:
                        self._play_file_node(node_idx, entry.get('sub_index', 0))
                    return

            # No selection - play first node
            self._play_first_node()
        elif status['paused']:
            self.player.resume()
            self.status_var.set("Playing")
        else:
            self.player.pause()
            self.status_var.set("Paused")

    def _stop(self):
        """Stop playback"""
        self.player.stop()
        self.current_node_idx = -1
        self.current_sub_index = -1
        self.current_index = -1
        self._update_playlist_display()
        self._update_now_playing(None)
        self.current_time_var.set("0:00")
        self.total_time_var.set("0:00")
        self.progress_var.set(0.0)
        self.status_var.set(i18n.get('status.stopped'))

    def _next_track(self):
        """下一首：文件夹内下一首或下一节点

        Navigates to the next track:
        - Within a folder: advance to next track in that folder
        - At folder end: move to next node in queue_nodes
        - At queue end: stop playback (or wrap if in loop-all mode)
        """
        if not self.queue_nodes:
            return

        if self.current_node_idx < 0:
            self._play_first_node()
            return

        node = self.queue_nodes[self.current_node_idx]

        if node.is_folder():
            next_track = node.advance_to_next()
            if next_track:
                self.current_sub_index = node.current_sub_index
                self.player.play(next_track.path)
                self._update_now_playing_with_art(next_track.path)
                self.status_var.set(i18n.get('status.now_playing', title=next_track.title))
                return

        # Folder finished or file node - move to next node
        next_idx = self.current_node_idx + 1
        if next_idx < len(self.queue_nodes):
            next_node = self.queue_nodes[next_idx]
            if next_node.is_folder():
                self._play_folder_node(next_idx)
            else:
                self._play_file_node(next_idx)
        else:
            self.status_var.set("Playback complete")

    def _prev_track(self):
        """上一首：文件夹内上一首或上一节点

        Navigates to the previous track:
        - Within a folder: go back to previous track
        - At folder start: move to previous node
        """
        if not self.queue_nodes or self.current_node_idx < 0:
            return

        node = self.queue_nodes[self.current_node_idx]

        if node.is_folder() and node.current_sub_index > 0:
            prev_track = node.advance_to_prev()
            if prev_track:
                self.current_sub_index = node.current_sub_index
                self.player.play(prev_track.path)
                self._update_now_playing_with_art(prev_track.path)
                self.status_var.set(i18n.get('status.now_playing', title=prev_track.title))
            return

        # Move to previous node
        prev_idx = self.current_node_idx - 1
        if prev_idx >= 0:
            prev_node = self.queue_nodes[prev_idx]
            if prev_node.is_folder() and prev_node.tracks:
                # Start from last track in previous folder
                prev_node.current_sub_index = len(prev_node.tracks) - 1
                self.current_node_idx = prev_idx
                self.current_sub_index = prev_node.current_sub_index
                track = prev_node.get_current_track()
                if track:
                    self.player.play(track.path)
                    self._update_now_playing_with_art(track.path)
                    self.status_var.set(i18n.get('status.now_playing', title=track.title))
            else:
                self._play_file_node(prev_idx)
        else:
            self.status_var.set("Already at first track")

    def _play_first_node(self):
        """播放第一个节点"""
        if not self.queue_nodes:
            return

        first_node = self.queue_nodes[0]
        if first_node.is_folder():
            self._play_folder_node(0)
        else:
            self._play_file_node(0)

    def _set_volume(self, value):
        """Set volume (only effective for audio files)"""
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
        """扫描所有媒体库并更新播放列表"""
        import player as pm
        from library_manager import LibraryManager, FolderNode

        manager = LibraryManager()
        result = manager.scan_all_libraries()

        if not result:
            messagebox.showwarning(
                i18n.dialog('dialog.title.warning'),
                "No media libraries found. Add a library first."
            )
            return

        # 停止当前播放
        self.player.stop()

        # 清空当前队列并重置指针
        self.queue_nodes = []
        self.display_map.clear()
        self.current_node_idx = -1
        self.current_sub_index = -1
        self.current_index = -1
        self.selected_index = -1

        # 收集所有扫描的轨道
        all_tracks = []
        for lib_path, files in result.items():
            try:
                for media_file in files:
                    relative_title = str(Path(media_file.path).relative_to(lib_path))
                    track = pm.Track(path=media_file.path, title=relative_title)
                    all_tracks.append((media_file.path, track))
            except ValueError:
                for media_file in files:
                    track = pm.Track(path=media_file.path, title=Path(media_file.path).name)
                    all_tracks.append((media_file.path, track))

        # 按父目录分组创建 FolderNodes
        folder_groups: dict = {}
        for filepath, track in all_tracks:
            parent = str(Path(filepath).parent)
            if parent not in folder_groups:
                folder_groups[parent] = []
            folder_groups[parent].append(track)

        # 创建 FolderNodes
        for folder_path, tracks in sorted(folder_groups.items()):
            tracks.sort(key=lambda t: t.path)
            node = FolderNode(
                display_text=Path(folder_path).name,
                path=folder_path,
                tracks=tracks
            )
            self.queue_nodes.append(node)

        # 更新播放列表显示
        self._update_playlist_display()

        # 显示统计信息
        total_files = sum(len(files) for files in result.values())
        self.status_var.set(f"Loaded {total_files} files from {len(result)} libraries")


def run_gui():
    """Run the GUI application"""
    root = tk.Tk()
    app = PyPlayerGUI(root)

    # Set up track end callback
    def on_track_end():
        """Callback when a track finishes - auto play next"""
        app._next_track()

    app.player.audio_player.set_track_end_callback(on_track_end)

    # Run periodic status check in a separate thread
    def update_loop():
        while True:
            try:
                time.sleep(0.1)
                if not hasattr(app, 'player') or app.player is None:
                    continue

                # Check for track end (triggers callback if needed)
                app.player.check_track_end()

                status = app.player.get_status()
                if status['current_track'] and app.current_node_idx < 0:
                    # Find the current playing track in queue_nodes
                    for i, node in enumerate(app.queue_nodes):
                        if node.is_folder():
                            for j, track in enumerate(node.tracks):
                                if Path(track.path).name == status['current_track']:
                                    app.current_node_idx = i
                                    app.current_sub_index = j
                                    break
                        else:
                            if Path(node.track.path).name == status['current_track']:
                                app.current_node_idx = i
                                app.current_sub_index = 0
                                break
            except AttributeError:
                pass

    # Start update thread (will be stopped when GUI closes)
    updater_thread = Thread(target=update_loop, daemon=True)
    updater_thread.start()

    root.mainloop()


if __name__ == "__main__":
    run_gui()
