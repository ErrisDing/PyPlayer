#!/usr/bin/env python3
"""
PyPlayer Windows Build Script
Automates PyInstaller packaging process.

Usage:
    python .build/build_windows.py           # Build to .target/
    python .build/build_windows.py --clean   # Clean build artifacts first
    python .build/build_windows.py --onefile # Single file bundle (slower startup)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def clean_build_artifacts(project_root: Path) -> None:
    """Remove build artifacts and previous distribution."""
    dirs_to_remove = ['build', 'dist', '.target']

    for dir_name in dirs_to_remove:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"Removing {dir_path}...")
            shutil.rmtree(dir_path, ignore_errors=True)


def check_pyinstaller() -> bool:
    """Check if PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("ERROR: PyInstaller is not installed.")
        print("Install with: pip install pyinstaller")
        return False


def check_dependencies() -> bool:
    """Check if all required dependencies are installed."""
    required = [
        ('PyQt6', 'PyQt6'),
        ('soundfile', 'soundfile'),
        ('sounddevice', 'sounddevice'),
        ('mutagen', 'mutagen'),
        ('PIL', 'Pillow'),
        ('numpy', 'numpy'),
        ('scipy', 'scipy'),
        ('cv2', 'opencv-python'),
    ]

    missing = []
    for import_name, pip_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"WARNING: Missing dependencies: {', '.join(missing)}")
        print("Some features may not work correctly.")
        print(f"Install with: pip install {' '.join(missing)}")
        return False

    return True


def build_directory_mode(project_root: Path) -> int:
    """Build as directory bundle (recommended for faster startup)."""
    print("\n" + "=" * 50)
    print("Building PyPlayer (Directory Mode)")
    print("=" * 50 + "\n")

    spec_file = project_root / '.build' / 'pyplayer.spec'

    if not spec_file.exists():
        print(f"ERROR: Spec file not found: {spec_file}")
        return 1

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        '--distpath', str(project_root / '.target'),
        '--workpath', str(project_root / 'build'),
        str(spec_file)
    ]

    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(project_root))

    return result.returncode


def build_onefile_mode(project_root: Path) -> int:
    """Build as single executable file."""
    print("\n" + "=" * 50)
    print("Building PyPlayer (Single File Mode)")
    print("=" * 50 + "\n")

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        '--onefile',
        '--windowed',
        '--name', 'PyPlayer',
        '--distpath', str(project_root / '.target'),
        '--workpath', str(project_root / 'build'),
    ]

    # Add data files
    resource_dir = project_root / 'resource'
    if resource_dir.exists():
        cmd.extend(['--add-data', f"{resource_dir};resource"])

    locales_dir = project_root / 'locales'
    if locales_dir.exists():
        cmd.extend(['--add-data', f"{locales_dir};locales"])

    qss_file = project_root / 'view' / 'resources' / 'styles.qss'
    if qss_file.exists():
        cmd.extend(['--add-data', f"{qss_file.parent};view/resources"])

    # Add hidden imports
    hidden_imports = [
        'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.sip',
        'soundfile', 'sounddevice', 'mutagen', 'PIL', 'numpy', 'scipy', 'cv2',
        'core', 'view', 'presenter', 'service', 'tui',
        'core.resource_utils',
    ]
    for imp in hidden_imports:
        cmd.extend(['--hidden-import', imp])

    cmd.append('main.py')

    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(project_root))

    return result.returncode


def main():
    parser = argparse.ArgumentParser(description='Build PyPlayer for Windows')
    parser.add_argument('--clean', action='store_true',
                        help='Clean build artifacts before building')
    parser.add_argument('--onefile', action='store_true',
                        help='Build as single executable file (slower startup)')
    args = parser.parse_args()

    # Project root is parent of .build directory
    project_root = Path(__file__).parent.parent.resolve()

    print(f"Project root: {project_root}")
    print(f"Python: {sys.executable}")
    print(f"Python version: {sys.version}")

    # Check prerequisites
    if not check_pyinstaller():
        return 1

    deps_ok = check_dependencies()

    # Clean if requested
    if args.clean:
        print("\nCleaning build artifacts...")
        clean_build_artifacts(project_root)

    # Build
    if args.onefile:
        result = build_onefile_mode(project_root)
    else:
        result = build_directory_mode(project_root)

    if result == 0:
        if args.onefile:
            output_file = project_root / '.target' / 'PyPlayer.exe'
            print("\n" + "=" * 50)
            print("BUILD SUCCESSFUL!")
            print("=" * 50)
            print(f"\nExecutable: {output_file}")
            print("\nYou can distribute the single .exe file.")
        else:
            output_dir = project_root / '.target' / 'PyPlayer'
            print("\n" + "=" * 50)
            print("BUILD SUCCESSFUL!")
            print("=" * 50)
            print(f"\nOutput directory: {output_dir}")
            print(f"Executable: {output_dir / 'PyPlayer.exe'}")

            # Copy Python DLLs to exe directory (fixes "Failed to load Python DLL" error)
            import shutil
            for dll_name in ['python313.dll', 'python3.dll']:
                python_dll = output_dir / '_internal' / dll_name
                if python_dll.exists():
                    dest_dll = output_dir / dll_name
                    shutil.copy2(python_dll, dest_dll)
                    print(f"Copied {dll_name} to: {dest_dll}")

            print("\nYou can distribute the entire 'PyPlayer' folder.")
    else:
        print("\nBUILD FAILED!")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
