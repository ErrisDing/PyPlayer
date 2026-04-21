# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for PyPlayer.
Build command: python .build/build_windows.py
Output directory: .target/
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Project root directory (parent of .build folder)
PROJECT_ROOT = Path(SPECPATH).parent

# Collect all data files
datas = []

# Add resource files
resource_dir = PROJECT_ROOT / 'resource'
if resource_dir.exists():
    datas.append((str(resource_dir), 'resource'))

# Add locales (i18n files)
locales_dir = PROJECT_ROOT / 'locales'
if locales_dir.exists():
    datas.append((str(locales_dir), 'locales'))

# Add QSS stylesheet
qss_file = PROJECT_ROOT / 'view' / 'resources' / 'styles.qss'
if qss_file.exists():
    datas.append((str(qss_file.parent), 'view/resources'))

# PyQt6 specific data files (plugins, translations, etc.)
try:
    pyqt6_datas = collect_data_files('PyQt6', include_py_files=False)
    datas.extend(pyqt6_datas)
except Exception:
    pass

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # PyQt6 modules
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.sip',

    # Audio/video backends
    'soundfile',
    'sounddevice',
    'mutagen',
    'mutagen.id3',
    'mutagen.flac',
    'mutagen.ogg',
    'mutagen.mp4',
    'mutagen.apev2',
    'PIL',
    'PIL.Image',

    # Scientific computing
    'numpy',
    'scipy',
    'scipy.io',
    'scipy.io.wavfile',

    # Video processing
    'cv2',
    'moviepy',
    'moviepy.editor',
    'pygame',

    # Project modules (ensure all are included)
    'core',
    'core.player',
    'core.config',
    'core.i18n',
    'core.metadata',
    'core.library_manager',
    'core.cache_manager',
    'core.resource_utils',
    'view',
    'view.main_window',
    'view.widgets',
    'view.widgets.now_playing_panel',
    'view.widgets.control_panel',
    'view.widgets.playlist_view',
    'view.widgets.progress_slider',
    'view.widgets.library_selector',
    'view.models',
    'view.models.playlist_model',
    'view.dialogs',
    'view.dialogs.library_dialog',
    'presenter',
    'presenter.main_presenter',
    'service',
    'service.playback_service',
    'service.queue_service',
    'service.library_service',
    'service.metadata_service',
    'service.config_service',
    'service.tools',
    'service.tools.base',
    'service.tools.mp3',
    'service.tools.flac',
    'service.tools.m4a',
    'service.tools.ogg',
    'service.tools.diagnostic',
    'tui',
    'tui.tui',
]

# Collect all submodules for key packages
for pkg in ['mutagen', 'PIL', 'scipy']:
    try:
        hiddenimports.extend(collect_submodules(pkg))
    except Exception:
        pass

a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'unittest',
        'test',
        'tests',
        'pydoc',
        'doctest',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PyPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Set to True for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here if available: str(PROJECT_ROOT / 'resource' / 'icon.ico')
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PyPlayer',
)
