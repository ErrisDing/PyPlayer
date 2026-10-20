#!/usr/bin/env python3
"""
Internationalization (i18n) module for PyPlayer.
Supports zh_CN and en_US with automatic locale detection.

Usage:
    import i18n
    text = i18n.get('keyword', param='value')  # Replaces {param} or {{param}}
"""

import os
import locale
from pathlib import Path


# Global state
_current_locale = None
_initialized = False
_properties_cache = {}  # filename -> dict


def detect_init():
    """Initialize locale detection and set current_locale."""
    global _current_locale, _initialized

    if _initialized:
        return

    _current_locale = detect_locale()
    _initialized = True


def detect_locale() -> str:
    """Auto-detect system language.

    Returns 'zh_CN' if Chinese detected (from environment or OS locale),
    otherwise falls back to 'en_US'.

    Detection priority:
    1. LANG/LC_ALL environment variables
    2. OS default locale via locale.getdefaultlocale()
    """
    # Check environment first
    lang = os.environ.get('LANG', '') or os.environ.get('LC_ALL', '')

    if 'Chinese (Simplified)_China' in lang.lower():
        return 'zh_CN'

    # Fall back to OS default locale
    try:
        # Prefer getlocale() (recommended for Python 3.11+)
        detected = locale.getlocale()[0]

        # If getlocale returns None, try old API for backward compatibility
        if detected is None:
            try:
                detected = locale.getdefaultlocale()[0]
            except AttributeError:
                # getdefaultlocale removed in Python 3.11+
                pass

        if detected and 'Chinese (Simplified)_China' == detected:
            return 'zh_CN'
    except (locale.Error, AttributeError, ValueError):
        pass

    return 'en_US'


def get_current_locale() -> str:
    """Get current locale with lazy initialization."""
    global _current_locale, _initialized

    if not _initialized:
        detect_init()

    return _current_locale or 'en_US'


def load_properties(filename: str) -> dict:
    """Load a .properties file and return as dictionary.

    Args:
        filename: Base name of the properties file (without extension/locale suffix)
                  e.g., 'interface/main' for 'locales/interface/main.zh_CN.properties'

    Returns:
        Dictionary mapping property keys to values, or empty dict on error.
    """
    global _current_locale, _initialized

    # Lazy init locale if needed
    if not _initialized:
        detect_init()

    cache_key = f"{_current_locale}/{filename}"
    if cache_key in _properties_cache:
        return _properties_cache[cache_key]

    from core.resource_utils import get_locales_path
    base_dir = get_locales_path()

    # Try current locale first (e.g., zh_CN)
    filepath = base_dir / f"{filename}.{_current_locale}.properties"

    if not filepath.exists():
        # Fallback to English
        filepath = base_dir / f"{filename}.en_US.properties"

    props = {}

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse key=value format
                if '=' in line:
                    key, value = line.split('=', 1)
                    # Unescape the only sequence the properties files use: a
                    # literal "\n" is a real line break. Multi-line QMessageBox
                    # text (dialog.confirm_delete_media_lib) showed the two
                    # characters as-is until this landed.
                    props[key.strip()] = value.strip().replace('\\n', '\n')
    except (OSError, IOError, UnicodeDecodeError, ValueError) as e:
        print(f"Error loading properties file {filepath}: {e}")

    _properties_cache[cache_key] = props
    return props


def _substitute(value: str, kwargs: dict) -> str:
    """Replace placeholders in a property value with the given parameters.

    Both brace forms are supported, and the order is load-bearing:

    1. ``{{key}}`` (double brace) first;
    2. ``{key}`` (single brace) second.

    Running the single-brace pass first would eat the inner ``{key}`` of a
    double-brace value and leave the outer braces behind as ``{5}``. The repo's
    properties files use only the single form, but the double form predates
    this fix and must keep working.

    With no parameters the value is returned untouched, so keys nobody passes
    kwargs for are byte-identical to the file.
    """
    for key, val in kwargs.items():
        value = value.replace(f"{{{{{key}}}}}", str(val))
    for key, val in kwargs.items():
        value = value.replace(f"{{{key}}}", str(val))
    return value


def get(keyword: str, **kwargs) -> str:
    """Get localized text for a keyword.

    Args:
        keyword: The property key to look up (auto-categorized by position/context)
        **kwargs: Placeholders to replace in the value OR 'default' as fallback string.
                  Values are substituted as {key} or {{key}}, or returned directly
                  if default provided.

    Returns:
        Localized string, "[MISSING: {keyword}]" if not found, or the 'default' value
        if provided and keyword not found.

    Examples:
        get('status.ready') -> "Ready - Press Space to play or click files"
        get('status.now_playing', title='Song Title') -> "Now playing: Song Title"
        get('button.add', default='Add') -> Returns 'Add' if keyword not found in properties
    """
    global _current_locale, _initialized

    # Lazy init locale if needed
    if not _initialized:
        detect_init()

    # Separate default from placeholders (if provided as kwarg)
    default_value = kwargs.pop('default', None)

    props = load_properties(f"interface/main")
    value = props.get(keyword, None)

    if value is None:
        if default_value is not None:
            return default_value
        return f"[MISSING: {keyword}]"

    return _substitute(value, kwargs)


def get_category(category: str, keyword: str, **kwargs) -> str:
    """Get localized text from a specific category file.

    Args:
        category: Category name (e.g., 'console/output', 'dialogs/dialog')
        keyword: The property key to look up
        **kwargs: Placeholders for replacement ({key} or {{key}}) OR 'default'
                  as fallback string.

    Returns:
        Localized string, "[MISSING: {keyword}]" if not found, or the 'default' value
        if provided and keyword not found.
    """
    global _current_locale, _initialized

    # Lazy init locale if needed
    if not _initialized:
        detect_init()

    # Separate default from placeholders (if provided as kwarg)
    default_value = kwargs.pop('default', None)


    props = load_properties(category)
    value = props.get(keyword, None)
    if value is None:
        if default_value is not None:
            return default_value
        return f"[MISSING: {keyword}]"

    return _substitute(value, kwargs)


def set_locale(locale_str: str):
    """Manually set the locale (useful for testing)."""
    global _current_locale, _initialized

    if locale_str not in ('zh_CN', 'en_US'):
        raise ValueError(f"Unsupported locale: {locale_str}. Use zh_CN or en_US.")

    _current_locale = locale_str
    _initialized = True


# Convenience aliases for common usage patterns
interface = get  # For interface/main category
console = lambda kw, **kwds: get_category('console/output', kw, **kwds)
dialog = lambda kw, **kwds: get_category('dialogs/dialog', kw, **kwds)
