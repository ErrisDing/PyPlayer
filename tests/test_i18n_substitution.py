#!/usr/bin/env python3
"""i18n placeholder substitution and ``\\n`` unescaping (batch 2, task 1).

Two defects in ``core/i18n.py`` block every parameterised status message the
batch needs (spec §7, §5):

* the substitution loop in ``get()`` / ``get_category()`` only matched the
  *double*-brace form ``{{key}}``, while **no value in any properties file uses
  double braces** -- every parameterised copy in the repo uses single braces
  (``status.library_removed=媒体库已移除：{name}``). Parameters therefore reached
  users wrapped in literal braces, and three call sites worked around it by
  hand-calling ``str.format()``.
* ``load_properties()`` never unescaped ``\\n``, so multi-line ``QMessageBox``
  text (``dialog.confirm_delete_media_lib``) rendered a literal ``\\n\\n``.

Six guards, no ``QApplication`` (pure string logic):

* ``test_single_brace_is_substituted`` -- the headline fix, on the real copy.
* ``test_double_brace_still_substituted`` /
  ``test_double_brace_not_broken_by_single_pass`` -- the old form keeps working,
  and the second one *pins the replacement order*: the double-brace pass must
  run first, or ``{{n}}`` degrades to ``{5}`` with a stray brace.
* ``test_no_param_keys_are_unchanged`` -- the blast-radius guard. Every key of
  ``main.zh_CN.properties`` and ``dialog.zh_CN.properties`` is fetched with no
  kwargs and must come back byte-identical to the right-hand side of ``=`` in
  the file (modulo ``\\n`` unescaping, the next test). Substitution is a
  kwargs-driven pass, so an empty kwargs must be a no-op for *any* value shape:
  braces, ``{0}``-like text, percent signs, quotes.
* ``test_newline_is_unescaped`` -- the second defect.
* ``test_missing_key_still_returns_marker`` -- the ``[MISSING: ...]`` contract
  other tests (``tests/test_i18n_coverage.py``) rely on must survive.

The double-brace tests write a throwaway ``interface/main.zh_CN.properties``
into a temp dir and point ``core.resource_utils.get_locales_path`` at it, so no
shipped copy is touched and the ``{{key}}`` form is still exercised even though
the repo stopped using it.

Run:
    python -m unittest tests.test_i18n_substitution -v
"""
import contextlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n

ZH_MAIN = ROOT / 'locales' / 'interface' / 'main.zh_CN.properties'
ZH_DIALOG = ROOT / 'locales' / 'dialogs' / 'dialog.zh_CN.properties'

DIALOG_CATEGORY = 'dialogs/dialog'


def raw_properties(path: Path) -> dict:
    """Parse a properties file into ``{key: raw right-hand side of '='}``.

    Deliberately not ``load_properties``: the guard has to read the file the way
    a reviewer would, so a change to the loader cannot make the assertion
    tautological. Later duplicates win, exactly as the loader builds its dict.
    Values come back *unstripped* -- neither zh_CN file pads a value today, so
    the guard asserts true byte identity with the file instead of quietly
    absorbing the loader's ``strip()``.
    """
    props = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        props[key.strip()] = value
    return props


@contextlib.contextmanager
def temp_main_properties(values: dict):
    """Install a throwaway ``interface/main.zh_CN.properties`` for one test.

    ``load_properties`` caches per locale *and* file name, so the real
    ``zh_CN/interface/main`` entry is moved aside for the duration and dropped
    again on exit: the whole suite shares one process, and a leftover probe
    entry would make a later test read the temp file.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    (tmp_dir / 'interface').mkdir()
    (tmp_dir / 'interface' / 'main.zh_CN.properties').write_text(
        '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n',
        encoding='utf-8',
    )
    cache_key = 'zh_CN/interface/main'
    saved = i18n._properties_cache.pop(cache_key, None)
    previous_locale = i18n.get_current_locale()

    try:
        i18n.set_locale('zh_CN')
        with mock.patch('core.resource_utils.get_locales_path',
                        return_value=tmp_dir):
            yield
    finally:
        i18n._properties_cache.pop(cache_key, None)
        if saved is not None:
            i18n._properties_cache[cache_key] = saved
        i18n.set_locale(previous_locale)
        shutil.rmtree(tmp_dir, ignore_errors=True)


class I18nSubstitutionTest(unittest.TestCase):
    """``{key}`` and ``{{key}}`` both substitute; no-param copy is untouched."""

    def setUp(self):
        self._previous_locale = i18n.get_current_locale()
        i18n.set_locale('zh_CN')

    def tearDown(self):
        i18n.set_locale(self._previous_locale)

    def test_single_brace_is_substituted(self):
        self.assertEqual(
            i18n.get('status.library_removed', name='Rock'),
            '媒体库已移除：Rock',
        )

    def test_double_brace_still_substituted(self):
        with temp_main_properties({'probe.loaded': '已加载 {{n}} 个'}):
            result = i18n.get('probe.loaded', n=5)
            self.assertEqual(result, '已加载 5 个')
            self.assertNotIn('{', result)

    def test_double_brace_not_broken_by_single_pass(self):
        with temp_main_properties({'probe.count': '{{n}}'}):
            result = i18n.get('probe.count', n=5)
            self.assertEqual(result, '5')
            self.assertNotIn('{', result)
            self.assertNotIn('}', result)

    def test_no_param_keys_are_unchanged(self):
        for path, fetch in ((ZH_MAIN, lambda key: i18n.get(key)),
                            (ZH_DIALOG,
                             lambda key: i18n.get_category(DIALOG_CATEGORY, key))):
            props = raw_properties(path)
            self.assertTrue(props, f'{path.name} must not be empty')
            for key, raw_value in props.items():
                with self.subTest(file=path.name, key=key):
                    self.assertEqual(
                        fetch(key),
                        raw_value.replace('\\n', '\n'),
                    )

    def test_newline_is_unescaped(self):
        text = i18n.dialog('dialog.confirm_delete_media_lib', path='D:/x')
        self.assertIn('\n', text)
        self.assertNotIn('\\n', text)

    def test_missing_key_still_returns_marker(self):
        self.assertEqual(i18n.get('no.such.key'), '[MISSING: no.such.key]')


if __name__ == '__main__':
    unittest.main(verbosity=2)
