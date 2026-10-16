# PyPlayer UI 批次 1（设计 token 与主题层）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让颜色、字号、间距、圆角、图标只有一个来源，并让暗色模式成为一等公民（跟随系统 + 可手动覆盖）。

**Architecture:** `core/theme.py` 定义纯 Python 的语义 token 与解析函数（不 import Qt，可无显示环境单测）；`core/theme_qss.py` 由 token 生成唯一的应用级样式表；`view/theme_manager.py` 是持有 `QApplication` 的 QObject，负责 palette + stylesheet 下发与 `theme_changed` 广播；各 widget 不再自带样式，只在收到 `recolor(tokens)` 时重绘图标与背景。

**Tech Stack:** Python 3.13、PyQt6（Qt 6.11 验证）、unittest、QtSvg、PyInstaller。

**Spec:** [docs/superpowers/specs/2026-10-16-ui-batch1-theme-tokens-design.md](../specs/2026-10-16-ui-batch1-theme-tokens-design.md)

## Global Constraints

- 解释器固定 `D:\PROGRAMMES\miniconda3\envs\dev_313\python.exe`（仓库内 `.venv` **没有 PyQt6**，不能用于 GUI 验证）。下文命令里的 `PY` 指它。
- 测试框架是 `unittest`，**不引入 pytest**。运行：`PY -m unittest discover -s tests -p "test_*.py" -v`。
- 任何触碰 Qt widgets 的测试前置 `QT_QPA_PLATFORM=offscreen`（本仓库在 Windows + Git Bash 下执行）。
- 不新增第三方依赖。所需 API（`QStyleHints.colorScheme`、`QtSvg`）在 `PyQt6>=6.5.0` 内可用。
- 基线：`PY -m unittest discover -s tests` 当前 **10 用例、1 个已失败**（`test_player.TestHierarchicalPlaylist.test_multiple_libraries_display`，期待已被 a5da9a8 移除的 `[ML]` 标记）。本计划不修它；每个任务的验收是**不新增失败**。
- 文案改动必须同步写 `locales/interface/main.zh_CN.properties` + `main.en_US.properties`，弹窗文案写 `locales/dialogs/dialog.zh_CN.properties` + `dialog.en_US.properties`。
- 终态：全仓 `setStyleSheet` 只剩 `view/theme_manager.py` 一处（起点 32 处）。
- 颜色进 token 一律 `#rrggbb` 字符串，不用 `QColor`。
- 每个任务结束时提交一次。**只 commit，不 push。**

## Review Focus

规格未写但真实使用中会撞上的输入，逐条给出钉住它的测试所在任务：

1. **auto 模式下系统主题运行中翻转**（亮切暗），界面须不重启即翻转；旧 Qt 无 `colorSchemeChanged` 时须不崩。→ Task 6 的 `test_auto_mode_follows_system_flip` / `test_missing_color_scheme_signal_is_tolerated`。
2. **老 `settings.json` 没有 `theme` 键**，须落 `auto` 而非 KeyError 或崩溃。→ Task 7 的 `test_missing_theme_key_defaults_to_auto`。
3. **图标 SVG 缺失或打包漏收**，须退化为空图标而非异常或整窗打不开。→ Task 8 的 `test_missing_icon_degrades_to_null_icon`。
4. **设了背景图后切暗色**，叠加层须变深（`scrim`），不能仍是白雾。→ Task 6 的 `test_scrim_color_tracks_theme`。
5. **首次启动（无媒体库、空播放列表）**，界面任何位置不得出现 `[MISSING: key]`。→ Task 9 的 `test_no_missing_i18n_keys_in_view`。

---

## 文件结构

**新建**

| 文件 | 职责 |
|---|---|
| `core/theme.py` | `ThemeTokens`、`LIGHT`/`DARK`、几何与排印常量、`AlphaSettings`、`resolve()`。不 import Qt |
| `core/theme_qss.py` | `build_qss(tokens, alphas)` 生成唯一样式表；导出 `REQUIRED_OBJECT_NAMES` / `REQUIRED_DYN_PROPERTIES` 供结构测试比对 |
| `view/theme_manager.py` | `ThemeManager`：palette + stylesheet 下发、系统配色监听、`theme_changed` |
| `view/icons.py` | `icon(name, color, size, dpr)`：读 SVG → 替换 `currentColor` → 按 dpr 渲染 → 缓存 |
| `resource/icons/*.svg` | 12 个 24×24 图标 |
| `tests/test_theme.py` | token 完整性、`resolve` 真值表、对比度不变量 |
| `tests/test_theme_qss.py` | 生成结果的结构与 alpha 合成 |
| `tests/test_view_structure.py` | objectName / 动态属性与 QSS 选择器一致 |
| `tests/test_theme_manager.py` | palette/QSS 下发、模式与 alpha 变更 |
| `tests/test_config_theme.py` | `theme` 读写与缺省 |
| `tests/test_icons.py` | SVG 合法性、缓存、缺失退化 |
| `tests/test_i18n_coverage.py` | 视图用到的 key 在两份语言里都存在 |
| `tests/tools/render_matrix.py` | 离屏渲染 8 张对比图（本批次与后续批次共用） |

**修改**：`view/main_window.py`、`view/widgets/bottom_panel.py`、`view/widgets/now_playing_panel.py`、`view/widgets/playlist_view.py`、`view/widgets/library_selector.py`、`view/delegates/playlist_delegate.py`、`view/models/playlist_model.py`、`view/dialogs/appearance_dialog.py`、`view/widgets/__init__.py`、`main.py`、`core/config.py`、`service/config_service.py`、`presenter/main_presenter.py`、`.build/pyplayer.spec`、两份 properties。

**删除**：`view/widgets/control_panel.py`、`view/widgets/progress_slider.py`、`view/resources/styles.qss`。

---

## Task 1: 修复启动崩溃并建立视图冒烟测试

`view/main_window.py:81` 使用 `QApplication` 但模块未导入它，`MainWindow()` 构造即抛 `NameError`（来自 43bbfd8）。本任务先用测试复现，再修。

**Files:**
- Modify: `view/main_window.py:8-12`（导入列表）
- Create: `tests/test_view_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: `tests/test_view_smoke.py` 里的 `class ViewSmokeTest(unittest.TestCase)`，含模块级 `make_app()` 与 `QT_AVAILABLE` 跳过标记，Task 5/6/8 复用同一套导入方式。

- [ ] **Step 1: 写失败的测试**

`tests/test_view_smoke.py`：在 offscreen 下构造 `MainWindow` 并断言 `grab()` 返回非空 pixmap。要求：
- 顶部 `QT_AVAILABLE` 由 `try: from PyQt6.QtWidgets import QApplication ... except ImportError` 决定，类上挂 `@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')`。
- `make_app()` 返回 `QApplication.instance() or QApplication([])`，供后续任务共用。
- 测试 `test_main_window_constructs_and_paints`：`w = MainWindow(); w.resize(900, 600); w.show(); app.processEvents(); pm = w.grab()`，断言 `not pm.isNull()` 且 `pm.width() > 0`。

- [ ] **Step 2: 运行，确认因 NameError 失败**

Run: `PY -m unittest tests.test_view_smoke -v`（前置 `QT_QPA_PLATFORM=offscreen`）
Expected: FAIL / ERROR，报 `NameError: name 'QApplication' is not defined`，位置 `view/main_window.py` 的 `_setup_window`。

- [ ] **Step 3: 修导入**

把 `QApplication` 加进 `view/main_window.py:8` 的 `PyQt6.QtWidgets` 导入括号内，同时删掉该括号里未被使用的 `QToolBar` 与 `QHBoxLayout`（本文件确认无引用）。

- [ ] **Step 4: 运行，确认通过**

Run: `PY -m unittest tests.test_view_smoke -v` → Expected: PASS（1 test）。

- [ ] **Step 5: 确认未新增回归**

Run: `PY -m unittest discover -s tests -p "test_*.py"`
Expected: `Ran 11 tests`，`FAILED (failures=1)`，且失败项仍是 `test_multiple_libraries_display`。

- [ ] **Step 6: Commit**

```bash
git add view/main_window.py tests/test_view_smoke.py
git commit -m "fix(view): 补 QApplication 导入，修复启动崩溃"
```

---

## Task 2: 删除僵尸 widget、不可达信号与重复 DTO

先把 461 行僵尸代码和三条死信号清掉，后续任务就不必再给它们改样式。

**Files:**
- Delete: `view/widgets/control_panel.py`、`view/widgets/progress_slider.py`
- Modify: `view/widgets/__init__.py`、`view/main_window.py`（信号与 `_on_add_library`、`_on_set_background`、`_on_clear_background`）、`presenter/main_presenter.py:94`、`presenter/main_presenter.py:224-232`、`view/widgets/playlist_view.py`（`track_selected` 与 `_on_click`）、`view/models/playlist_model.py:22-32`
- Create: `tests/test_dead_code_removed.py`

**Interfaces:**
- Consumes: Task 1 的 `tests/test_view_smoke.py`（作为回归门）
- Produces: `view.models.DisplayEntry` 成为 `service.queue_service.DisplayEntry` 的别名（同一对象）。Task 6 之后 delegate 依赖此单一类型。

- [ ] **Step 1: 写失败的测试**

`tests/test_dead_code_removed.py`，纯 Python（不需要 QApplication，但 import `view.models` 会拉起 PyQt6 的 QtCore，故仍加 `skipUnless`）：
- `test_display_entry_is_single_type`：`from view.models import DisplayEntry as V; from service.queue_service import DisplayEntry as Q; assert V is Q`。
- `test_dead_widgets_are_gone`：`importlib.util.find_spec('view.widgets.control_panel')` 与 `...progress_slider` 均为 `None`。
- `test_dead_signals_are_gone`：`MainWindow` 类上不存在 `add_library_requested`、`remove_library_requested`；`PlaylistView` 类上不存在 `track_selected`。用 `hasattr(MainWindow, name) is False`。
- `test_context_menu_signal_survives`：`hasattr(PlaylistView, 'context_menu_requested')` 为真（批次 3 的接口，不得顺手删）。

- [ ] **Step 2: 运行，确认失败**

Run: `PY -m unittest tests.test_dead_code_removed -v`
Expected: 4 个测试全部 FAIL。

- [ ] **Step 3: 执行删除**

- 删两个文件；`view/widgets/__init__.py` 去掉对应 import 与 `__all__` 条目。
- `view/main_window.py`：删 `add_library_requested`、`remove_library_requested` 两行信号声明；删 `_on_add_library`（原 240-247）与 `_on_set_background`、`_on_clear_background`（原 272-287）。
- `presenter/main_presenter.py`：删 `:94` 的 `self._view.add_library_requested.connect(self._on_add_library)`；删 `_on_add_library`（`:224` 起整个方法）。**保留** `:294` 与 `_handle_add_library_dialog` —— 那是 `LibraryManagementDialog` 自己的同名信号，不是 `MainWindow` 的。
- `view/widgets/playlist_view.py`：删 `track_selected` 信号、`_on_click` 方法与 `self._list_view.clicked.connect(...)`；给 `context_menu_requested` 加一行注释 `# 批次 3：右键菜单接口，尚未 emit`。
- `view/models/playlist_model.py`：删本地 `@dataclass DisplayEntry`（22-32 行）与 `dataclass` 导入，改 `from service.queue_service import DisplayEntry`。

- [ ] **Step 4: 运行测试确认通过**

Run: `PY -m unittest tests.test_dead_code_removed tests.test_view_smoke -v` → Expected: 全部 PASS。

- [ ] **Step 5: 全量确认不新增失败**

Run: `PY -m unittest discover -s tests -p "test_*.py"`
Expected: `Ran 15 tests`，`FAILED (failures=1)`，失败项仍是 `test_multiple_libraries_display`。

- [ ] **Step 6: Commit**

```bash
git add -A view/ presenter/ tests/test_dead_code_removed.py
git commit -m "refactor(view): 移除僵尸 widget、不可达信号与重复 DisplayEntry"
```

---

## Task 3: `core/theme.py` —— token 与解析

**Files:**
- Create: `core/theme.py`
- Create: `tests/test_theme.py`

**Interfaces:**
- Consumes: `core.constants.AppearanceDefaults`（三个 alpha 默认值）
- Produces:
  - `ThemeTokens`（frozen dataclass，**34 个 `str` 字段**，名字与 spec §4.1 表格逐一对应）
  - `LIGHT: ThemeTokens`、`DARK: ThemeTokens`
  - `AlphaSettings(overlay: float, playlist: float, controls: float)` frozen dataclass，默认取 `AppearanceDefaults` 的三个常量
  - `resolve(mode: str, system_scheme: str) -> ThemeTokens`，`mode ∈ {'auto','light','dark'}`，`system_scheme ∈ {'Dark','Light','Unknown'}`
  - 常量：`RADIUS_SM=4` `RADIUS_MD=6` `RADIUS_PILL=999` `SPACE_1=4` `SPACE_2=8` `SPACE_3=12` `SPACE_4=16` `ROW_HEIGHT=28` `TRANSPORT_SIZE=40` `PLAY_SIZE=50` `ART_SIZE=200` `FONT_SIZE_SM=12` `FONT_SIZE_MD=13` `FONT_SIZE_LG=15` `FONT_SIZE_XL=18`
  - `TOKEN_FIELDS: tuple[str, ...]`（由 `dataclasses.fields` 得出，供测试与 QSS 生成器比对）

- [ ] **Step 1: 写失败的测试**

`tests/test_theme.py`，`class ThemeTokensTest`：
- `test_light_and_dark_define_identical_fields`：`_fields(LIGHT) == _fields(DARK) == set(TOKEN_FIELDS)`，且每个值匹配 `^#[0-9a-f]{6}$`。
- `test_resolve_truth_table`：9 组输入断言返回 `LIGHT` 或 `DARK` 对象本身（`is`）。断言 `resolve('auto','Unknown') is LIGHT`、`resolve('auto','Dark') is DARK`、`resolve('light','Dark') is LIGHT`、`resolve('dark','Light') is DARK`。
- `test_resolve_rejects_unknown_mode`：`resolve('neon','Dark')` 抛 `ValueError`。

Run: `PY -m unittest tests.test_theme -v` → Expected: FAIL（`ModuleNotFoundError: No module named 'core.theme'`）。

- [ ] **Step 2: 实现 `core/theme.py`**

按 spec §4.1 的两张色表逐字填 `LIGHT` / `DARK`（34 字段），实现 `resolve` 与常量。`resolve` 用显式分支，非法 `mode` 抛 `ValueError`。不 import 任何 Qt 模块。

- [ ] **Step 3: 运行确认通过**

Run: `PY -m unittest tests.test_theme -v` → Expected: PASS（3 tests）。

- [ ] **Step 4: 加对比度不变量测试并确认其通过**

同文件追加 `class ThemeContrastTest`。在本测试文件内实现 `_rel_lum(hex) -> float` 与 `contrast(fg, bg) -> float`（WCAG 2.1 相对亮度公式），断言：
- 每套主题：`text_primary`、`text_secondary`、`text_muted` 对 `surface`、`surface_alt`、`selection_bg`、`playing_bg` 均 ≥ 4.5。
- `text_on_accent` 对 `accent` ≥ 4.5；`playing_text` 对 `playing_bg` ≥ 4.5。
- `icon` 对 `surface` ≥ 3.0；`icon_on_accent` 对 `accent` ≥ 3.0。
- `tooltip_text` 对 `tooltip_bg` ≥ 4.5。

Run: `PY -m unittest tests.test_theme -v` → Expected: PASS（4 tests）。若 spec 的某个色值不达标，**改色值并同步改 spec 的 §4.1 表**，不要放宽阈值。

- [ ] **Step 5: Commit**

```bash
git add core/theme.py tests/test_theme.py
git commit -m "feat(theme): 语义 token 定义、解析与对比度不变量"
```

---

## Task 4: `core/theme_qss.py` —— 唯一样式表来源

**Files:**
- Create: `core/theme_qss.py`
- Create: `tests/test_theme_qss.py`

**Interfaces:**
- Consumes: Task 3 的 `ThemeTokens`、`AlphaSettings`、几何常量
- Produces:
  - `build_qss(tokens: ThemeTokens, alphas: AlphaSettings) -> str`
  - `REQUIRED_OBJECT_NAMES: tuple[str, ...]` = `('nowPlayingPanel','albumArt','trackTitle','trackArtist','trackAlbum','playlistHeader','playlistView','bottomPanel','progressSlider','volumeSlider','playButton','loopButton','timeLabel','appearanceDialog','bgPathLabel')`
  - `REQUIRED_DYN_PROPERTIES: tuple[tuple[str, str], ...]` = `(('chip','true'), ('role','transport'))`
  - `hex_to_rgba(hex_color: str, alpha: float) -> str`（`'rgba(r, g, b, a)'`，a 保留两位）

- [ ] **Step 1: 写失败的测试**

`tests/test_theme_qss.py`，`class BuildQssTest`：
- `test_output_is_complete_and_substituted`：对 `LIGHT`/`DARK` × 三组 alpha 断言结果里不含 `'{' + 'alpha'` 之类的残留花括号（用正则 `r'\{[a-z_]+\}'` 断言 `re.search` 为 `None`），且花括号成对。
- `test_no_bare_widget_rules`：结果中不存在 `re.search(r'^\s*(QPushButton|QSlider|QListView|QLabel)\s*\{', qss, re.M)` —— 一切规则必须带 `#objectName` 或 `[prop=...]` 作用域。
- `test_declares_every_required_selector`：`REQUIRED_OBJECT_NAMES` 每一项都以 `#name` 形式出现在 QSS 中；`REQUIRED_DYN_PROPERTIES` 每项以 `[prop="value"]` 出现。
- `test_alpha_is_applied`：`alphas.playlist=0.5` 时 QSS 含 `#playlistView` 规则块内出现 `rgba(` 且该块含 `, 0.5)`；`controls=0.25` 同理落在 `#bottomPanel` 块。
- `test_alpha_is_clamped`：`AlphaSettings(overlay=-1, playlist=2, controls=0.5)` 不抛异常，且输出里对应 alpha 落在 `0.0`/`1.0`。
- `test_hex_to_rgba`：`hex_to_rgba('#1976d2', 0.5) == 'rgba(25, 118, 210, 0.5)'`。

Run: `PY -m unittest tests.test_theme_qss -v` → Expected: FAIL（模块不存在）。

- [ ] **Step 2: 实现 `build_qss`**

把 `view/resources/styles.qss` 的规则迁过来并按 token + objectName 重写，映射关系（**这是本任务的设计核心，逐条实现**）：

| 选择器 | 关键属性 → token |
|---|---|
| `QMainWindow, #nowPlayingPanel` | 背景透明（scrim 由 `paintEvent` 画） |
| `QMenuBar` / `QMenuBar::item:selected` | `surface` / `hover_bg` |
| `QMenu` / `QMenu::item:selected` / `QMenu::separator` | `surface` / `accent_soft` / `divider` |
| `#playlistHeader` | `background: surface_header; color: text_primary; font-size: FONT_SIZE_LG; font-weight: 600; padding: SPACE_2 SPACE_3`（**深灰条 A3 就此消失**） |
| `#playlistView` | `background: hex_to_rgba(surface, playlist_alpha); border: 1px solid border` |
| `#playlistView::item` | `padding: 0 SPACE_2; border-bottom: 1px solid divider`（行高由 delegate `sizeHint` 给 `ROW_HEIGHT`，不在此设 height） |
| `#progressSlider` / `#volumeSlider` | groove `hex_to_rgba(border_strong, 0.5)`、height 6、radius 3；sub-page `accent`；handle `accent`、14×14、margin -4、radius 7；`:hover` `accent_hover`；`:pressed` `accent_pressed`（**两个滑块自此同色**） |
| `QPushButton[role="transport"]`, `#loopButton` | `button_bg` / `button_hover` / `button_pressed` / `border` / `radius_md` / `TRANSPORT_SIZE` 固定宽高 |
| `#playButton` | `background: accent; color: text_on_accent; border: none; radius: PLAY_SIZE/2` |
| `QPushButton[chip="true"]` | `button_bg`、`radius_pill`、`padding: SPACE_1 SPACE_3`；`:selected`→`[selected="true"]` 用 `accent_soft` + `accent` 文字 |
| `#trackTitle` / `#trackArtist` / `#trackAlbum` | `FONT_SIZE_XL`+bold / `FONT_SIZE_MD`+`text_secondary` / `FONT_SIZE_MD`+`text_muted` |
| `#timeLabel` | `FONT_SIZE_SM` + `text_secondary` |
| `#albumArt` | `border: 1px solid border; border-radius: RADIUS_MD; background: surface_alt` |
| `QScrollBar`（垂直/水平，含 `:horizontal` 全套） | `scrollbar_thumb` / `scrollbar_thumb_hover`，宽 10，`add-line`/`sub-line` 高度 0 |
| `QToolTip` | `tooltip_bg` / `tooltip_text` |
| `QSplitter::handle` | `divider`，宽 1 |
| `*:focus` 之外的焦点环 | `#playlistView:focus`, `QPushButton[role="transport"]:focus`, `#playButton:focus`, `#loopButton:focus`, `QPushButton[chip="true"]:focus` → `border: 2px solid focus_ring` |
| 禁用态 | 上述按钮 `:disabled` → `button_disabled_bg` / `button_disabled_text` |
| `#bgPathLabel` / `#bgPathLabel[empty="true"]` | `text_primary` / `text_muted` + italic |
| `QDialog#appearanceDialog`, `QGroupBox` | `window_bg` / `surface` / `border`（A4：弹窗自此与主窗口同调） |

`REQUIRED_OBJECT_NAMES` / `REQUIRED_DYN_PROPERTIES` 必须与本表实际用到的名字一致 —— 测试会拿它对账。

- [ ] **Step 3: 运行确认通过**

Run: `PY -m unittest tests.test_theme_qss tests.test_theme -v` → Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add core/theme_qss.py tests/test_theme_qss.py
git commit -m "feat(theme): 由 token 生成唯一应用样式表"
```

---

## Task 5: 给控件挂 objectName 与动态属性

只加标识，不改样式，视觉零变化；加完之后 Task 6 换样式来源时才有稳定的作用域。

**Files:**
- Modify: `view/widgets/now_playing_panel.py`、`view/widgets/playlist_view.py`、`view/widgets/bottom_panel.py`、`view/widgets/library_selector.py`、`view/dialogs/appearance_dialog.py`
- Create: `tests/test_view_structure.py`

**Interfaces:**
- Consumes: Task 4 的 `REQUIRED_OBJECT_NAMES`、`REQUIRED_DYN_PROPERTIES`
- Produces: 控件树里存在 `#progressSlider`、`#playButton`、`#loopButton`、`#timeLabel`（×2）、`#albumArt`、`#trackTitle`、`#trackArtist`、`#trackAlbum`、`#playlistHeader`、`#playlistView`、`#bottomPanel`、`#nowPlayingPanel`、`#volumeSlider`、`#appearanceDialog`、`#bgPathLabel`；transport 按钮带 `property('role') == 'transport'`；媒体库按钮带 `property('chip') == 'true'` 与 `property('selected')`。

- [ ] **Step 1: 写失败的测试**

`tests/test_view_structure.py`，`class ViewStructureTest(unittest.TestCase)`，offscreen + `skipUnless(QT_AVAILABLE)`：
- `test_every_required_object_name_exists`：构造 `MainWindow`，收集 `{o.objectName() for o in w.findChildren(QObject)} | {w.objectName()}`，断言 `set(REQUIRED_OBJECT_NAMES) <= collected`，失败信息里列出缺失项。
- `test_transport_and_chip_properties`：`[b for b in w.findChildren(QPushButton) if b.property('role') == 'transport']` 长度 ≥ 3；`set_libraries` 灌 2 个假库后 `property('chip') == 'true'` 的按钮长度为 2。
- `test_object_names_are_unique_per_scope`：`#timeLabel` 恰好 2 个（当前位置与总时长），其余 objectName 各 ≤ 1。

Run: `PY -m unittest tests.test_view_structure -v` → Expected: FAIL（objectName 全为空串）。

- [ ] **Step 2: 挂标识**

各 `_setup_ui` 里对既有控件实例调用 `setObjectName(...)`；`bottom_panel` 的三个方向按钮 `setProperty('role', 'transport')`；`library_selector._rebuild_buttons` 里 `setProperty('chip', 'true')`（字符串 `'true'`，QSS 属性选择器按字符串匹配）。`appearance_dialog` 设 `setObjectName('appearanceDialog')` 与 `self._bg_path_label.setObjectName('bgPathLabel')`。

- [ ] **Step 3: 运行确认通过**

Run: `PY -m unittest tests.test_view_structure tests.test_view_smoke -v` → Expected: PASS。

- [ ] **Step 4: 全量确认不新增失败**

Run: `PY -m unittest discover -s tests -p "test_*.py"` → Expected: `FAILED (failures=1)`，仍是既有的那一个。

- [ ] **Step 5: Commit**

```bash
git add view/ tests/test_view_structure.py
git commit -m "refactor(view): 为控件挂 objectName 与动态属性作用域"
```

---

## Task 6: 切换样式来源（ThemeManager 上线，删 styles.qss 与全部内联样式）

本任务是不可拆的一次换血：样式来源从「全局 QSS + 32 处内联」变为「ThemeManager 下发一份」。中间态没有样式，故不拆提交。

**Files:**
- Create: `view/theme_manager.py`、`tests/test_theme_manager.py`
- Modify: `main.py:19-124`、`view/main_window.py`（构造签名、`recolor`、`scrim_color`、`paintEvent`）、`view/widgets/bottom_panel.py`、`view/widgets/now_playing_panel.py`、`view/widgets/playlist_view.py`、`view/widgets/library_selector.py`、`view/delegates/playlist_delegate.py`、`view/models/playlist_model.py`、`view/dialogs/appearance_dialog.py`、`tests/test_view_smoke.py`（构造签名变更）、`.build/pyplayer.spec:31-33`
- Delete: `view/resources/styles.qss`

**Interfaces:**
- Consumes: Task 3 `resolve`/`LIGHT`/`DARK`/`AlphaSettings`/`ROW_HEIGHT`；Task 4 `build_qss`；Task 5 的 objectName 树
- Produces:
  - `ThemeManager(mode: str = 'auto', alphas: AlphaSettings | None = None, parent=None)`，方法 `apply_to(app)`、`set_mode(mode)`、`set_alpha(which: str, value: float)`（`which ∈ {'overlay','playlist','controls'}`），属性 `tokens -> ThemeTokens`、`alphas -> AlphaSettings`、`mode -> str`，信号 `theme_changed = pyqtSignal(object)`
  - `MainWindow(theme_manager: ThemeManager, parent=None)`（**必填位置参数**），方法 `recolor(tokens)`、`scrim_color() -> QColor`、`set_overlay_alpha(float)`、`set_playlist_alpha(float)`、`set_controls_alpha(float)`
  - `BottomPanel(manager: ThemeManager, parent=None)` + `BottomPanel.recolor(tokens: ThemeTokens) -> None`
  - `PlaylistView(manager: ThemeManager, parent=None)` + `PlaylistView.recolor() -> None`
  - `PlaylistItemDelegate(manager: ThemeManager, parent=None)`；`PlaylistModel` 不再返回任何颜色或字体
  - `LibrarySelector` 签名不变；`AppearanceDialog` 签名不变（`theme_mode` 参数由 Task 7 引入）

- [ ] **Step 1: 写 ThemeManager 的失败测试**

`tests/test_theme_manager.py`，offscreen：
- `test_apply_to_sets_stylesheet_and_palette`：`ThemeManager('light').apply_to(app)` 后 `app.styleSheet()` 含 `#bottomPanel`，`app.palette().color(QPalette.ColorRole.Base)` 等于 `LIGHT.surface`。
- `test_set_mode_swaps_tokens`：`set_mode('dark')` 触发一次 `theme_changed`，`mgr.tokens is DARK`。
- `test_set_alpha_rebuilds_qss`：`set_alpha('playlist', 0.5)` 后 `app.styleSheet()` 的 `#playlistView` 块含 `, 0.5)`。
- `test_set_alpha_rejects_unknown_key`：`set_alpha('nope', 0.5)` 抛 `KeyError`。
- `test_auto_mode_follows_system_flip`（Review Focus 1）：`ThemeManager('auto')`，直接调 `mgr._on_system_scheme_changed('Dark')`，断言 `mgr.tokens is DARK`；再调 `('Light')` 回到 `LIGHT`。
- `test_missing_color_scheme_signal_is_tolerated`（Review Focus 1）：用一个 `styleHints()` 无 `colorSchemeChanged` 的替身（`unittest.mock.patch.object(QApplication, 'styleHints')`）调 `apply_to`，断言不抛异常且 stylesheet 已设置。
- `test_scrim_color_tracks_theme`（Review Focus 4）：`mgr = ThemeManager('light')`，`w = MainWindow(mgr)`，`w.set_background_image(<临时 png>)`，断言 `w.scrim_color().name().lower() == LIGHT.scrim`；`mgr.set_mode('dark')` 后断言等于 `DARK.scrim`。

Run: `PY -m unittest tests.test_theme_manager -v` → Expected: FAIL（模块不存在）。

- [ ] **Step 2: 实现 `view/theme_manager.py`**

`apply_to(app)` 存 `self._app`，`_system_scheme()` 读 `app.styleHints().colorScheme().name`，`resolve(self._mode, scheme)` 得 tokens，然后 `app.setPalette(self._build_palette(tokens))` + `app.setStyleSheet(build_qss(tokens, self._alphas))`，最后若 `hasattr(app.styleHints(), 'colorSchemeChanged')` 则连接到 `_on_system_scheme_changed`（`mode != 'auto'` 时该槽直接 return）。`_build_palette` 至少映射 `Window←window_bg`、`WindowText/Text←text_primary`、`Base←surface`、`AlternateBase←surface_alt`、`Button←button_bg`、`ButtonText←text_primary`、`Highlight←accent`、`HighlightedText←text_on_accent`、`ToolTipBase←tooltip_bg`、`ToolTipText←tooltip_text`、`PlaceholderText←text_muted`、`Disabled` 组←`button_disabled_*`。`set_alpha` 用 `dataclasses.replace` 造新 `AlphaSettings` 并重发 QSS（`overlay` 不发 QSS，只 `theme_changed` 让窗口重绘 scrim）。

- [ ] **Step 3: 改 `MainWindow` 的构造、recolor 与 scrim**

`MainWindow.__init__(self, theme_manager, parent=None)`：存 `self._theme`，把 manager 传给 `BottomPanel` 与 `PlaylistView`；`theme_manager.theme_changed.connect(self.recolor)`，`__init__` 末尾调一次 `self.recolor(theme_manager.tokens)`。`recolor(tokens)` 转发 `self._bottom_panel.recolor(tokens)`、`self._playlist_view.recolor()`、`self.update()`。`scrim_color()` 返回带 `self._overlay_alpha` 的 `QColor(self._theme.tokens.scrim)`；`paintEvent` 用它替换 `main_window.py:365` 写死的 `QColor(255,255,255,alpha_int)`。`_overlay_alpha` 初值改取 `theme_manager.alphas.overlay`，删掉对 `AppearanceDefaults.BACKGROUND_OVERLAY_ALPHA` 的导入。三个 `set_*_alpha` 改为转发 `self._theme.set_alpha('overlay'|'playlist'|'controls', v)`。同步把 `tests/test_view_smoke.py` 的 `MainWindow()` 改为 `MainWindow(ThemeManager('light'))`。

Run: `PY -m unittest tests.test_view_smoke -v` → Expected: PASS。

- [ ] **Step 4: 把列表表现从 model 移到 delegate**

`PlaylistModel`：删 `PLAYING_BG_COLOR`、`FOLDER_COLOR`、`BackgroundRole`/`ForegroundRole`/`FontRole` 三个分支及 `QColor`/`QFont` 导入。`PlaylistItemDelegate`：构造收 `manager` 并传给 `super().__init__(parent)`；`paint` 开头 `t = self._manager.tokens`，取色改为 `playing_bg`/`selection_bg`/`text_primary`/`text_muted`；新增 `sizeHint() -> QSize` 返回 `QSize(0, ROW_HEIGHT)`；`PlaylistView.recolor()` 调 `self._list_view.viewport().update()`。

本步**只做取色迁移**，视觉与改动前等价：hover 分支属批次 3（C2），`playing_bar` 左侧条与 muted 路径色属 Task 9。

- [ ] **Step 5: 删各 widget 的内联样式**

`bottom_panel.py`：删 7 处 `setStyleSheet`、`_update_stylesheet`、`BOTTOM_PANEL_*_ALPHA` 实例字段与 `_loop_btn` 的字符串样式；`set_bg_alpha` 转发 manager；`recolor(tokens)` 把 `icon_color` 换成 `tokens.icon`、播放键换成 `tokens.icon_on_accent` 后重新生成图标（仍是手绘多边形，SVG 在 Task 8 换）。`now_playing_panel.py`：删 6 处 `setStyleSheet`，`ART_SIZE` 改用 `core.theme.ART_SIZE`。`library_selector.py`：删内联表，`setProperty('selected', 'true'/'false')` 用字符串。`appearance_dialog.py`：删 7 处 `setStyleSheet`，`_bg_path_label` 改 `setProperty('empty', 'true'/'false')` + `unpolish/polish`。

- [ ] **Step 6: 换 `main.py` 的样式来源并删旧文件**

`main.py`：删 `:40-60`（darwin-only palette）与 `:62-81`（读 qss 文件）；在 services 构造之后、`MainWindow` 之前插入 `theme_manager = ThemeManager(mode='auto', alphas=AlphaSettings(overlay=config_service.get_overlay_alpha(), playlist=config_service.get_playlist_alpha(), controls=config_service.get_controls_alpha()))` → `theme_manager.apply_to(app)` → `view = MainWindow(theme_manager)`。`app.setStyle("Fusion")` 与 `setHighDpiScaleFactorRoundingPolicy` 保持在 `apply_to` 之前。`mode='auto'` 是硬编码，Task 7 才改成读 config。删 `view/resources/styles.qss` 与 `.build/pyplayer.spec:31-33` 的 `view/resources` 收录块。

- [ ] **Step 7: 运行确认通过**

Run: `PY -m unittest tests.test_theme_manager tests.test_view_structure tests.test_view_smoke tests.test_theme tests.test_theme_qss -v` → Expected: PASS。

- [ ] **Step 8: 确认全仓只剩一处 `setStyleSheet`**

Run: `grep -rn "setStyleSheet" --include=*.py . | grep -v "^./.venv"`
Expected: 只有 `./view/theme_manager.py` 一行（`app.setStyleSheet(...)`）。

- [ ] **Step 9: 全量确认不新增失败**

Run: `PY -m unittest discover -s tests -p "test_*.py"` → Expected: `FAILED (failures=1)`，仍是既有的那一个。

- [ ] **Step 10: Commit**

```bash
git add -A view/ main.py tests/ .build/pyplayer.spec
git commit -m "feat(theme): ThemeManager 接管样式来源，移除内联样式与 styles.qss"
```

---

## Task 7: 主题模式持久化、跟随系统与弹窗开关

**Files:**
- Modify: `core/config.py`（`Settings.theme`、`_load`、`_save`、`get_theme`/`set_theme`）、`service/config_service.py`、`presenter/main_presenter.py`、`view/dialogs/appearance_dialog.py`、`main.py`（Task 6 硬编码的 `mode='auto'` 改读 config）、两份 `locales/dialogs/dialog.*.properties`
- Create: `tests/test_config_theme.py`

**Interfaces:**
- Consumes: Task 6 的 `ThemeManager.set_mode`、`MainWindow`；`ConfigService`
- Produces: `Settings.theme: str = 'auto'`；`SettingsManager.get_theme()/set_theme(mode) -> bool`；`ConfigService.get_theme()/set_theme(mode)` 与 `theme_changed = pyqtSignal(str)`；`AppearanceDialog.theme_selected = pyqtSignal(str)`；`MainPresenter.__init__(..., theme_manager: ThemeManager)`。

- [ ] **Step 1: 写失败的测试**

`tests/test_config_theme.py`（纯 Python，不建 QApplication）：
- `test_missing_theme_key_defaults_to_auto`（Review Focus 2）：往临时目录写一份**不含 `theme` 键**的 settings.json，`SettingsManager(path).load()` 后 `get_theme() == 'auto'`。
- `test_theme_round_trip`：`set_theme('dark')` → `save()` → 新实例 `load()` → `get_theme() == 'dark'`。
- `test_invalid_theme_value_falls_back`：文件里 `"theme": "neon"` → `get_theme() == 'auto'`。
- `test_config_service_emits_theme_changed`：`ConfigService.set_theme('dark')` 触发一次信号且值为 `'dark'`。

Run: `PY -m unittest tests.test_config_theme -v` → Expected: FAIL。

- [ ] **Step 2: 实现配置侧**

`Settings` 加 `theme: str = 'auto'`；`_load` 用 `data.get('theme', 'auto')` 并经 `_normalize_theme`（非 `{auto,light,dark}` → `'auto'`）；`_save` 写入；**不 bump `CONFIG_VERSION`**（读取侧全是 `data.get(key, default)`）。`SettingsManager.get_theme/set_theme` 与 `ConfigService` 同名包装 + `theme_changed` 信号。

- [ ] **Step 3: 加弹窗三态与 presenter 接线**

`appearance_dialog._setup_ui` 在「背景图片」组之前插入 `QGroupBox(i18n.dialog('appearance.group.theme'))`，内含三个 `QRadioButton`（objectName `themeAuto`/`themeLight`/`themeDark`，文案 `appearance.theme_auto/light/dark`），当前值由构造参数 `theme_mode: str` 决定；点击即 `theme_selected.emit('auto'|'light'|'dark')`。`MainPresenter.__init__` 增末位关键字参数 `theme_manager: Optional[ThemeManager] = None`，`_on_manage_appearance` 里把 `theme_mode=self._config.get_theme()` 传入并把 `dialog.theme_selected` 接到 `lambda mode: (self._config.set_theme(mode), self._theme.set_mode(mode))`。`main.py`：Task 6 留下的 `ThemeManager(mode='auto', ...)` 改为 `mode=config_service.get_theme()`，并给 `MainPresenter(...)` 传 `theme_manager=theme_manager`。properties 两份各加 4 个 key（`appearance.group.theme`、`appearance.theme_auto`、`appearance.theme_light`、`appearance.theme_dark`）。

- [ ] **Step 4: 运行确认通过**

Run: `PY -m unittest tests.test_config_theme tests.test_theme_manager -v` → Expected: PASS。

- [ ] **Step 5: 手动验证 auto 的真实行为**

Run: `PY main.py`（真实 Windows，非 offscreen）
Expected: 系统为暗色时启动即暗色；弹窗切「浅色」后立即变浅且 `settings.json` 出现 `"theme": "light"`；重启后保持。

- [ ] **Step 6: Commit**

```bash
git add core/config.py service/config_service.py presenter/ view/dialogs/ locales/ tests/test_config_theme.py
git commit -m "feat(theme): 主题模式持久化、跟随系统切换与弹窗开关"
```

---

## Task 8: SVG 图标集与着色管线

**Files:**
- Create: `view/icons.py`、`resource/icons/{play,pause,prev,next,stop,loop_off,loop_all,loop_one,volume_mute,volume_low,volume_mid,volume_high}.svg`、`tests/test_icons.py`
- Modify: `view/widgets/bottom_panel.py`（删 `draw_*_icon` 五个函数、`create_vector_icon`、`create_colored_icon`，改用 `view.icons.icon`；loop 与音量改用图标）

**Interfaces:**
- Consumes: Task 6 的 `ThemeManager.tokens`（`icon`、`icon_muted`、`icon_on_accent`、`accent_soft`）
- Produces: `icon(name: str, color: str, size: int, dpr: float = 1.0) -> QIcon`；`clear_cache() -> None`。SVG 约定：`viewBox="0 0 24 24"`、`fill="currentColor"`、无外部引用。

- [ ] **Step 1: 写失败的测试**

`tests/test_icons.py`，offscreen：
- `test_all_icons_present_and_well_formed`：12 个文件存在，`xml.etree` 可解析，根属性含 `viewBox="0 0 24 24"`，序列化文本含 `currentColor`。
- `test_icon_renders_at_1x_and_2x`：`ic = icon('play', '#1976d2', 24, dpr)`，断言 `not ic.pixmap(QSize(24,24)).isNull()`，且 `ic.availableSizes()` 含 24。
- `test_cache_returns_same_object`：同参数两次 `icon(...)` 返回同一 `QIcon` 实例（`is`）。
- `test_missing_icon_degrades_to_null_icon`（Review Focus 3）：`icon('does_not_exist', '#000', 24)` 不抛异常，返回 `QIcon().isNull()` 为真的图标。

Run: `PY -m unittest tests.test_icons -v` → Expected: FAIL。

- [ ] **Step 2: 手写 12 个 SVG**

统一 24×24、单或双 `<path>`、`fill="currentColor"`。形状取 Material Icons 的几何（播放三角、暂停双竖条、上一/下一曲为「竖条 + 三角」、停止方块、`loop_off` 为循环箭头加斜杠、`loop_one` 在循环中心加"1"字形、四个音量档为喇叭加 0/1/2/3 段弧线）。不引入图标库、不下载资源。

- [ ] **Step 3: 实现 `view/icons.py` 并接入 `bottom_panel`**

`icon()`：`get_resource_path(f'resource/icons/{name}.svg')` 读文本 → `svg.replace('currentColor', color)` → `QSvgRenderer(QByteArray(...))` 渲染进 `QPixmap(size*dpr, size*dpr)`（先 `fill(Qt.GlobalColor.transparent)`，再 `setDevicePixelRatio(dpr)`）→ 加入 `QIcon`；文件缺失或 renderer 无效时返回空 `QIcon` 并 `print` 一行警告。缓存 `dict[(name,color,size,dpr)] -> QIcon`。

`bottom_panel`：`prev/next/stop` 用 `tokens.icon`，`play/pause` 用 `tokens.icon_on_accent`，`loop_*` 用 `tokens.accent`/`tokens.icon_muted`，音量四档用 `tokens.icon`；`recolor(tokens)` 重建全部图标；`_update_loop_button` 与 `_update_volume_icon` 改为换 `QIcon` + 换 tooltip，不再有字符串样式表。尺寸常量用 Task 3 的 `TRANSPORT_SIZE`/`PLAY_SIZE`。

- [ ] **Step 4: 运行确认通过**

Run: `PY -m unittest tests.test_icons tests.test_theme_manager tests.test_view_smoke -v` → Expected: PASS。

- [ ] **Step 5: 确认字符图标已消失**

Run: `grep -n "↺\|♪\|draw_play_icon\|create_vector_icon" view/widgets/bottom_panel.py`
Expected: 无输出。

- [ ] **Step 6: Commit**

```bash
git add view/icons.py resource/icons/ view/widgets/bottom_panel.py tests/test_icons.py
git commit -m "feat(icons): SVG 图标集与按 token 着色管线"
```

---

## Task 9: 文案 i18n、封面占位统一与状态色区分

**Files:**
- Modify: `view/widgets/now_playing_panel.py`、`view/widgets/playlist_view.py`、`view/widgets/bottom_panel.py`、`view/widgets/library_selector.py`、`view/delegates/playlist_delegate.py`、两份 `locales/interface/main.*.properties`
- Create: `tests/test_i18n_coverage.py`

**Interfaces:**
- Consumes: Task 6 的 delegate/manager；Task 8 的图标
- Produces: i18n key `metadata.unknown_title`、`now_playing.no_art`、`playlist.header`、`loop.mode_off`、`loop.mode_one`、`loop.mode_all`、`button.stop_track`、`library.tooltip`（zh/en 各一份）。

- [ ] **Step 1: 写失败的测试**

`tests/test_i18n_coverage.py`（不需要 QApplication，但 `i18n` 会读 locales 目录）：
- `test_view_keys_exist_in_both_locales`：对上面 8 个 key，`i18n.set_locale('zh_CN')` 与 `'en_US'` 下 `i18n.get(k)` 均不等于 `f'[MISSING: {k}]'`。
- `test_no_missing_keys_in_empty_state`（Review Focus 5）：offscreen 构造 `MainWindow(ThemeManager('light'))`，不调任何 `update_*`，遍历 `findChildren(QLabel)` 收集文本，断言没有任何文本含 `'[MISSING'` 或 `'No Track'`、`'No Art'`、`'Unknown Title'` 英文字面量。
- `test_no_hardcoded_english_literals_left`：对 `view/` 下五个被改文件做源码扫描，断言不再出现 `"No Track Playing"`、`"Unknown Title"`、`"No Art"`、`"Playlist"`、`"Loop: ` 字面量。

Run: `PY -m unittest tests.test_i18n_coverage -v` → Expected: FAIL。

- [ ] **Step 2: 补 properties**

zh 与 en 各加 8 个 key。中文：`未知标题`、`暂无封面`、`播放列表`、`循环：关闭`、`单曲循环`、`列表循环`、`停止`、`媒体库：{path}`；英文对应 `Unknown Title`、`No Artwork`、`Playlist`、`Loop: Off`、`Loop: One`、`Loop: All`、`Stop`、`Library: {path}`。

- [ ] **Step 3: 用 key 替换字面量**

`now_playing_panel`：`"No Track Playing"` → `i18n.get('metadata.no_track')`，`"Unknown Title"` → `metadata.unknown_title`，有标题但无艺人/专辑时空值改为占位（`metadata.unknown_artist` / `metadata.unknown_album`）。`_clear_art` 的兜底文本 → `now_playing.no_art`。`playlist_view` 表头 → `playlist.header`。`bottom_panel`：三个 tooltip → `button.prev_track` / `button.play_pause` / `button.next_track`，停止键新增 `button.stop_track`；loop tooltip → `loop.mode_off` / `loop.mode_one` / `loop.mode_all`；删 `hasattr(i18n,'get')` 防御。`library_selector` 按钮 tooltip → `library.tooltip` 带 `path=` 参数。

- [ ] **Step 4: 统一封面占位（A7）**

`_setup_ui` 初始即调用 `_clear_art()`，不再 `setText("No Art")`；`_clear_art` 优先级：默认封面 → 无封面时才用 `now_playing.no_art` 文本。`clear()` 与初始态走同一路径。

- [ ] **Step 5: delegate 状态区分（A5）与 muted 色（D1）**

delegate 绘制顺序改为：`playing_bg` → `selection_bg`（选中非播放）→ 左侧 `playing_bar` 3px 竖条（仅播放行）→ 文本（播放行 `playing_text`，文件夹 `text_primary` + bold，普通 `text_primary`）→ 右侧 `[relative_position]` 用 `text_muted`（**取代 `QColor(136,136,136,160)`**）。曲名可用宽度须先减去 `position_width + SPACE_2` 再 elide，避免窄窗口下压字。hover 背景属批次 3（C2），本任务不做。

- [ ] **Step 6: 运行确认通过**

Run: `PY -m unittest tests.test_i18n_coverage tests.test_view_smoke tests.test_view_structure -v` → Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add view/ locales/ tests/test_i18n_coverage.py
git commit -m "fix(ui): 文案 i18n、封面占位统一与播放状态色彩区分"
```

---

## Task 10: 渲染矩阵与收尾验证

**Files:**
- Create: `tests/tools/render_matrix.py`
- Modify: `README.md`（外观设置一节：主题三态 + 图标说明）

**Interfaces:**
- Consumes: 前九个任务的全部产物
- Produces: `tests/tools/render_matrix.py` CLI：`--out DIR`，输出 8 张 PNG（`light|dark` × `empty|populated` × `820x520|1100x720`），退出码 0。

- [ ] **Step 1: 实现脚本**

脚本内：`QT_QPA_PLATFORM=offscreen`、`app.setStyle('Fusion')`、构造 `ConfigService` + `ThemeManager` + `MainWindow`，灌入假数据（3 个媒体库、16 条含文件夹与相对路径的 `DisplayEntry`、播放中索引 3、进度 125.5/355.0、音量 0.6、loop ALL），按 8 种组合 `grab().save()`。`--out` 缺省用 `tempfile.mkdtemp()` 并打印路径。假数据构造复用 `tests/test_view_smoke.py` 的 `make_app()`。

- [ ] **Step 2: 跑脚本并逐张目视**

Run: `QT_QPA_PLATFORM=offscreen PY tests/tools/render_matrix.py --out /tmp/pyplayer-ui`
Expected（逐条核对）：两个滑块同色；播放列表头不再是深灰条；播放行与选中行一眼可分且播放行有左侧色条；空状态显示默认封面而非英文字面量；dark 两张图无残留白底（专看菜单、滚动条、弹窗底色）；`820x520` 下曲名省略号收尾、不压右侧路径。
注意：offscreen harness 的中文字形会退化为方框，**文字正确性必须再用 `PY main.py` 在真实 Windows 下确认**。

- [ ] **Step 3: 真实运行确认**

Run: `PY main.py`
Expected: 正常启动；中文正常；系统暗色下为暗色；弹窗切主题即时生效并持久化；无控制台异常输出。

- [ ] **Step 4: 全量测试与终态核对**

Run: `PY -m unittest discover -s tests -p "test_*.py"`
Expected: 失败项**仅** `test_multiple_libraries_display`。
Run: `grep -rn "setStyleSheet" --include=*.py . | grep -v "^./.venv" | grep -v theme_manager.py`
Expected: 无输出。

- [ ] **Step 5: Commit**

```bash
git add tests/tools/render_matrix.py README.md
git commit -m "test(ui): 主题渲染矩阵脚本与文档更新"
```
