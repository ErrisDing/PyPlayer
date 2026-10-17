#!/usr/bin/env python3
"""Theme mode persistence through the config layer (Task 7: 主题模式持久化).

``ThemeManager`` (Task 6) resolves the mode eagerly and :func:`core.theme.resolve`
raises ``ValueError`` on anything outside ``{auto, light, dark}``, which makes
the persisted ``theme`` preference a startup contract point. Two layers answer
it, deliberately with different policies:

* **Reading is tolerant.** ``_load_json`` funnels every key through
  ``data.get(key, default)`` and the value through ``_normalize_theme``, so a
  missing or hand-edited ``settings.json`` (``"theme": "Auto"``, ``"neon"``)
  yields ``'auto'`` and the app starts. That is why ``CONFIG_VERSION`` is *not*
  bumped here -- the version is only a warning channel, and a missing key
  already has the right fallback; bumping it would add a warning line to every
  existing user's startup for no behavioural gain (test below pins the value).
* **Writing is strict.** ``set_theme`` is an API call, not a user's typo in a
  text file, so an unsupported mode is refused (``False``, nothing written)
  instead of being silently rewritten as ``'auto'``.

``main.build_theme_manager`` keeps the third layer: the ``ValueError`` catch
that degrades an unresolvable mode to ``'auto'`` with one warning line. That
seam is Qt-only, so its tests live in ``tests/test_theme_manager.py``
(``StartupSeamTest``), not here.

Pure Python: no QApplication, and every case writes into a temporary directory
-- the repository-root ``settings.json`` holds the developer's real media
library paths and must never be touched by a test.

Run:
    python -m unittest tests.test_config_theme -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import SettingsManager


class ThemeConfigTest(unittest.TestCase):
    """``theme`` is loaded, defaulted, normalised and saved like the alphas."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / 'settings.json'

    def write(self, data: dict) -> None:
        """Drop a raw settings.json into the temp directory."""
        self.path.write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_missing_theme_key_defaults_to_auto(self):
        """A pre-Task-7 file (no ``theme`` key at all) still says ``'auto'``.

        This is the whole reason ``CONFIG_VERSION`` stays at ``2.0``: the loader
        reads every key with ``data.get(key, default)``, so an absent key is
        already a normal path rather than a migration.
        """
        self.write({'version': SettingsManager.CONFIG_VERSION,
                    'media_libraries': []})
        self.assertNotIn('theme', self.read())

        manager = SettingsManager(str(self.path))
        manager.load()

        self.assertEqual('auto', manager.get_theme())

    def test_config_version_is_not_bumped(self):
        """Pinned so a later "migration is cleaner" edit has to be deliberate."""
        self.assertEqual('2.0', SettingsManager.CONFIG_VERSION)

    def test_theme_round_trip(self):
        """``set_theme`` -> ``save`` -> a fresh instance reads it back."""
        manager = SettingsManager(str(self.path))
        self.assertTrue(manager.set_theme('dark'))
        self.assertEqual('dark', manager.get_theme())
        self.assertEqual('dark', self.read()['theme'])

        reopened = SettingsManager(str(self.path))
        reopened.load()
        self.assertEqual('dark', reopened.get_theme())

    def test_invalid_theme_value_falls_back(self):
        """A hand-edited value becomes ``'auto'``; startup cannot be bricked.

        ``'Auto'`` is the case-sensitivity trap the brief calls out (the
        resolver only accepts the exact lowercase literals), so it is in the
        same net as a nonsense word.
        """
        for bad in ('neon', 'Auto', 'system', '', None, 42, ['dark']):
            with self.subTest(theme=bad):
                self.write({'version': SettingsManager.CONFIG_VERSION,
                            'theme': bad, 'media_libraries': []})
                manager = SettingsManager(str(self.path))
                manager.load()
                self.assertEqual('auto', manager.get_theme())

    def test_all_three_modes_round_trip(self):
        """The allowed set is exactly what the resolver accepts, and all of it persists."""
        manager = SettingsManager(str(self.path))
        for mode in ('auto', 'light', 'dark'):
            with self.subTest(mode=mode):
                self.assertTrue(manager.set_theme(mode))
                self.assertEqual(mode, manager.get_theme())
                self.assertEqual(mode, self.read()['theme'])

    def test_set_theme_refuses_an_unsupported_mode(self):
        """Writing validates instead of rewriting: the file keeps the last good value.

        Deviation from the alpha setters (which clamp) is deliberate: clamping a
        categorical value would persist something nobody asked for, while the
        alpha sliders have an obvious in-range answer.
        """
        manager = SettingsManager(str(self.path))
        self.assertTrue(manager.set_theme('light'))

        self.assertFalse(manager.set_theme('neon'))
        self.assertFalse(manager.set_theme('Auto'))
        self.assertFalse(manager.set_theme(None))

        self.assertEqual('light', manager.get_theme())
        self.assertEqual('light', self.read()['theme'])

    def test_save_always_writes_the_theme_key(self):
        """Even the untouched default is persisted, so the key is never absent on disk."""
        manager = SettingsManager(str(self.path))
        self.assertTrue(manager.save())
        self.assertEqual('auto', self.read()['theme'])


class ConfigServiceThemeTest(unittest.TestCase):
    """The service side of the seam: a wrapper plus one signal."""

    def setUp(self):
        from service.config_service import ConfigService

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # ``config_file`` keeps the service off the developer's real
        # ``~/.pyplayer/cache/settings.json`` (and, transitively, off the
        # tracked repo-root ``settings.json`` that migration copies from).
        self.path = str(Path(self._tmp.name) / 'settings.json')
        self.service = ConfigService(config_file=self.path)
        self.selected = []
        self.service.theme_changed.connect(self.selected.append)

    def test_config_service_emits_theme_changed(self):
        self.assertTrue(self.service.set_theme('dark'))

        self.assertEqual(['dark'], self.selected)
        self.assertEqual('dark', self.service.get_theme())

    def test_theme_changed_not_emitted_when_the_write_is_refused(self):
        self.assertFalse(self.service.set_theme('neon'))

        self.assertEqual([], self.selected)
        self.assertEqual('auto', self.service.get_theme())

    def test_signal_carries_the_string_not_a_token_set(self):
        """``theme_changed(str)`` is the mode -- what ``ThemeManager.set_mode``
        is connected to in ``main.py`` (``ThemeManager.theme_changed``, the same
        name on a different object, is the one that carries ``ThemeTokens``)."""
        self.service.set_theme('light')
        self.service.set_theme('auto')

        self.assertEqual(['light', 'auto'], self.selected)
        self.assertIsInstance(self.selected[-1], str)


class DialogCopyKeysTest(unittest.TestCase):
    """The radio group's four i18n keys exist in both locales.

    ``i18n`` answers a missing key with ``[MISSING: …]`` at runtime instead of
    raising, so the only cheap guard is the properties files themselves.
    """

    KEYS = (
        'appearance.group.theme',
        'appearance.theme_auto',
        'appearance.theme_light',
        'appearance.theme_dark',
    )

    def test_both_dialog_catalogues_have_the_theme_keys(self):
        root = Path(__file__).resolve().parent.parent / 'locales' / 'dialogs'
        files = sorted(root.glob('dialog.*.properties'))
        self.assertEqual(2, len(files), f'expected zh_CN and en_US, got {files}')

        for path in files:
            with self.subTest(catalogue=path.name):
                keys = {}
                for line in path.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        keys[key.strip()] = value.strip()
                missing = [key for key in self.KEYS if key not in keys]
                self.assertEqual([], missing, f'{path.name}: {missing}')
                for key in self.KEYS:
                    self.assertTrue(keys[key], f'{key} is empty in {path.name}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
