#!/usr/bin/env python3
"""
NCM Proxy Manager - Manages proxy files for NCM encrypted audio format

NCM is NetEase Cloud Music's encrypted format. This module handles:
- Creating and managing proxy directory structure
- Finding/creating proxy files (MP3/FLAC) from NCM files
- Calling ncmdump tool for decryption
- Periodic cleanup of stale proxy files
"""

import hashlib
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional


class NCMProxyManager:
    """Manages proxy files for NCM encrypted audio format."""

    PROXY_DIR_NAME = "proxy"
    CLEANUP_DAYS = 30  # Delete proxies not accessed for 30 days
    NCM_TIMEOUT = 60  # Timeout for ncmdump execution in seconds

    # Supported proxy formats (in order of preference)
    PROXY_EXTENSIONS = ['.mp3', '.flac']

    def __init__(self, app_root: str):
        """
        Initialize the NCM proxy manager.

        Args:
            app_root: Application root directory path
        """
        self.app_root = os.path.abspath(app_root)
        self.proxy_root = os.path.join(self.app_root, self.PROXY_DIR_NAME)

        # Ensure proxy root exists
        os.makedirs(self.proxy_root, exist_ok=True)

    def get_proxy_file(self, ncm_path: str, library_path: str) -> Optional[str]:
        """
        Get proxy file path for an NCM file.
        Creates the proxy if it doesn't exist.

        Args:
            ncm_path: Path to the NCM file
            library_path: Path to the library the file belongs to

        Returns:
            Path to the proxy file, or None if creation failed
        """
        if not os.path.exists(ncm_path):
            return None

        # Get library-specific proxy directory
        library_proxy_dir = self._get_library_proxy_dir(library_path)

        # Try to find existing proxy
        proxy_path = self._find_existing_proxy(ncm_path, library_proxy_dir)
        if proxy_path:
            self._update_access_time(proxy_path)
            return proxy_path

        # Create new proxy
        proxy_path = self._create_proxy(ncm_path, library_proxy_dir)
        if proxy_path:
            self._update_access_time(proxy_path)

        return proxy_path

    def _get_library_proxy_dir(self, library_path: str) -> str:
        """
        Get the proxy directory for a specific library.

        Args:
            library_path: Path to the library

        Returns:
            Path to the library's proxy directory
        """
        # Use first 16 chars of SHA-256 hash as directory name
        lib_hash = hashlib.sha256(
            os.path.normpath(library_path).encode('utf-8')
        ).hexdigest()[:16]

        return os.path.join(self.proxy_root, lib_hash)

    def _find_existing_proxy(self, ncm_path: str, library_proxy_dir: str) -> Optional[str]:
        """
        Find existing proxy file for an NCM file.

        Args:
            ncm_path: Path to the NCM file
            library_proxy_dir: Path to the library's proxy directory

        Returns:
            Path to existing proxy file, or None if not found
        """
        stem = Path(ncm_path).stem  # Filename without extension

        for ext in self.PROXY_EXTENSIONS:
            proxy_path = os.path.join(library_proxy_dir, stem + ext)
            if os.path.exists(proxy_path):
                return proxy_path

        return None

    def _create_proxy(self, ncm_path: str, library_proxy_dir: str) -> Optional[str]:
        """
        Create a proxy file by decrypting the NCM file.

        Args:
            ncm_path: Path to the NCM file
            library_proxy_dir: Path to the library's proxy directory

        Returns:
            Path to created proxy file, or None if creation failed
        """
        # Ensure library proxy directory exists
        os.makedirs(library_proxy_dir, exist_ok=True)

        # Get ncmdump executable path
        try:
            ncmdump_path = self._get_ncmdump_path()
        except FileNotFoundError as e:
            print(f"[NCMProxy] Error: {e}")
            return None

        # Build command
        cmd = [ncmdump_path, ncm_path, '-o', library_proxy_dir]

        try:
            # Execute ncmdump
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.NCM_TIMEOUT
            )

            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace')
                print(f"[NCMProxy] ncmdump failed: {stderr}")
                return None

            # Find the created proxy file
            proxy_path = self._find_existing_proxy(ncm_path, library_proxy_dir)
            if proxy_path:
                print(f"[NCMProxy] Created proxy: {proxy_path}")
                return proxy_path

            print(f"[NCMProxy] Proxy file not found after ncmdump execution")
            return None

        except subprocess.TimeoutExpired:
            print(f"[NCMProxy] ncmdump timeout after {self.NCM_TIMEOUT}s")
            return None
        except Exception as e:
            print(f"[NCMProxy] Error creating proxy: {e}")
            return None

    def _get_ncmdump_path(self) -> str:
        """
        Get the path to ncmdump executable based on current platform.

        Returns:
            Path to ncmdump executable

        Raises:
            FileNotFoundError: If ncmdump is not found
        """
        system = platform.system().lower()
        machine = platform.machine().lower()

        # Normalize architecture names
        arch_map = {
            'amd64': 'amd64',
            'x86_64': 'amd64',
            'x64': 'amd64',
            'arm64': 'arm64',
            'aarch64': 'arm64',
        }
        arch = arch_map.get(machine, machine)

        # Determine executable name
        if system == 'windows':
            exe_name = 'ncmdump.exe'
        else:
            exe_name = 'ncmdump'

        # Build path
        bin_path = os.path.join(
            self.app_root, 'bin', system, arch, exe_name
        )

        if not os.path.exists(bin_path):
            raise FileNotFoundError(
                f"ncmdump not found at: {bin_path}. "
                f"Please ensure the correct binary is installed for {system}/{arch}."
            )

        return bin_path

    def _update_access_time(self, proxy_path: str) -> None:
        """
        Update the access time of a proxy file.

        Args:
            proxy_path: Path to the proxy file
        """
        try:
            os.utime(proxy_path, None)
        except OSError:
            pass  # Ignore errors updating access time

    def cleanup_stale_proxies(self) -> int:
        """
        Clean up proxy files that haven't been accessed for CLEANUP_DAYS.

        Returns:
            Number of files deleted
        """
        if not os.path.exists(self.proxy_root):
            return 0

        deleted = 0
        cutoff_time = time.time() - (self.CLEANUP_DAYS * 86400)

        for library_name in os.listdir(self.proxy_root):
            library_dir = os.path.join(self.proxy_root, library_name)
            if not os.path.isdir(library_dir):
                continue

            for filename in os.listdir(library_dir):
                file_path = os.path.join(library_dir, filename)

                try:
                    if os.path.getatime(file_path) < cutoff_time:
                        os.remove(file_path)
                        deleted += 1
                        print(f"[NCMProxy] Cleaned up stale proxy: {filename}")
                except OSError as e:
                    print(f"[NCMProxy] Error cleaning up {filename}: {e}")

        # Remove empty library directories
        for library_name in os.listdir(self.proxy_root):
            library_dir = os.path.join(self.proxy_root, library_name)
            if os.path.isdir(library_dir) and not os.listdir(library_dir):
                try:
                    os.rmdir(library_dir)
                except OSError:
                    pass

        if deleted > 0:
            print(f"[NCMProxy] Cleaned up {deleted} stale proxy file(s)")

        return deleted

    def get_proxy_for_metadata(self, ncm_path: str, library_path: str) -> Optional[str]:
        """
        Get proxy file path for metadata extraction.
        This is a convenience method that mirrors get_proxy_file.

        Args:
            ncm_path: Path to the NCM file
            library_path: Path to the library the file belongs to

        Returns:
            Path to the proxy file, or None if not available
        """
        return self.get_proxy_file(ncm_path, library_path)

    def clear_library_proxies(self, library_path: str) -> int:
        """
        Clear all proxy files for a specific library.

        Args:
            library_path: Path to the library

        Returns:
            Number of files deleted
        """
        library_proxy_dir = self._get_library_proxy_dir(library_path)

        if not os.path.exists(library_proxy_dir):
            return 0

        deleted = 0
        for filename in os.listdir(library_proxy_dir):
            file_path = os.path.join(library_proxy_dir, filename)
            try:
                os.remove(file_path)
                deleted += 1
            except OSError:
                pass

        # Remove the directory itself
        try:
            os.rmdir(library_proxy_dir)
        except OSError:
            pass

        return deleted


# Singleton instance
_ncm_proxy_instance: Optional[NCMProxyManager] = None


def get_ncm_proxy_manager(app_root: Optional[str] = None) -> NCMProxyManager:
    """
    Get the singleton NCMProxyManager instance.

    Args:
        app_root: Application root directory (required on first call)

    Returns:
        NCMProxyManager singleton instance
    """
    global _ncm_proxy_instance

    if _ncm_proxy_instance is None:
        if app_root is None:
            # Try to determine app root from this file's location
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _ncm_proxy_instance = NCMProxyManager(app_root)

    return _ncm_proxy_instance
