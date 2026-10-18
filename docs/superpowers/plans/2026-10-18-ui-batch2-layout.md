# PyPlayer UI 批次 2（图标栏外壳与曲库浮层）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「左栏 + 播放列表」换成「图标栏 + 全宽列表 + 浮层切库」，并让状态反馈按进度/反馈/错误三类归位，不再改写窗口标题。

**Architecture:** 新增四个各守一职的视图单元——`ActionRail`（56px 图标栏，承载原菜单全部动作与曲库入口）、`LibrarySidebar`（浮层曲库面板）、`NowPlayingStrip`（封面 + 曲名/艺人单行）、`Toast`（限时反馈）；`MainWindow` 的布局从 `QSplitter` 改为 `QHBoxLayout[rail | 列表]` 并删除 `menuBar()`；`BottomPanel` 顶部加一行放 strip。presenter 的状态调用点按语义分流到 rail 进行态、`show_toast` 与既有弹窗。

**Tech Stack:** Python 3.13、PyQt6（Qt 6.11 验证）、unittest、QtSvg、PyInstaller。

**Spec:** [docs/superpowers/specs/2026-10-18-ui-batch2-layout-design.md](../specs/2026-10-18-ui-batch2-layout-design.md)

## Global Constraints

- 解释器固定 `D:/PROGRAMMES/miniconda3/envs/dev_313/python.exe`（仓库 `.venv` **无 PyQt6**）。不安装任何包。
- 测试框架 `unittest`，不引入 pytest。命令：`cd /d/Codes/Python/PyPlayer && QT_QPA_PLATFORM=offscreen /d/PROGRAMMES/miniconda3/envs/dev_313/python.exe -m unittest ...`
- 不新增第三方依赖。
- 基线：`Ran 129 tests, FAILED (failures=1)`，唯一失败是 main 上既有的 `test_player.TestHierarchicalPlaylist.test_multiple_libraries_display`。每个任务的验收是**不新增失败**。
- 全仓 `setStyleSheet` 终态仍**只有一处**：`view/theme_manager.py`。新控件样式一律 objectName + `core/theme_qss.py`。
- 新控件的 objectName 必须进 `core/theme_qss.py` 的 `REQUIRED_OBJECT_NAMES`，与它的 QSS 规则同一任务落地。
- 文案改动同步写 `locales/interface/main.{zh_CN,en_US}.properties` 与 `locales/dialogs/dialog.{zh_CN,en_US}.properties`。
- offscreen 下 `QStyleHints.colorScheme()` 返回 `Unknown`；不要写依赖 offscreen 报告真实配色的测试。
- offscreen 渲染中文为方框（harness 假象）；文字正确性需真实 Windows。
- 变异测试前**必须先清 `__pycache__`**（`find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`）——批次 1 曾因等长替换 + 同秒还原让陈旧 .pyc 继续运行，把正确代码测成红。
- 每任务一次提交；只 commit，**不 push**。

## Review Focus

规格未写但真实使用会撞上的输入，逐条给出钉住它的测试所在任务：

1. **零媒体库首启**：图标栏库图标仍可点，浮层显示空态与「添加媒体库」，不崩、不出现 `[MISSING:`。→ Task 4 `test_sidebar_with_zero_libraries_shows_empty_state_and_add_entry`。
2. **30 个库**：浮层内部滚动、不超窗、不裁切库名。→ Task 4 `test_sidebar_with_thirty_libraries_stays_within_window`。
3. **刷新进行中再次触发刷新**：不并发进入同一条库加载路径。→ Task 3 `test_refresh_all_blocks_refresh_current`。
4. **移除菜单后快捷键是否还生效**：`Ctrl+O` / `Ctrl+Q` 必须仍触发原动作。→ Task 7 `test_shortcuts_survive_menu_removal`。
5. **窗口标题不再被任何运行状态改写**：播放、暂停、刷新、切库全程标题恒为应用名。→ Task 8 `test_title_never_changes_across_states`。

---

## 文件结构

**新建**

| 文件 | 职责 |
|---|---|
| `view/widgets/action_rail.py` | `ActionRail`：56px 图标栏，动作与曲库入口，进行态 |
| `view/widgets/library_sidebar.py` | `LibrarySidebar`：浮层曲库面板，选库与添加库 |
| `view/widgets/now_playing_strip.py` | `NowPlayingStrip`：48px 封面 + 曲名/艺人单行 |
| `view/widgets/toast.py` | `Toast`：限时反馈浮层，同时最多一条 |
| `tests/test_i18n_substitution.py` | i18n 括号与 `\n` 修复的守护 |
| `tests/test_action_rail.py`、`tests/test_library_sidebar.py`、`tests/test_now_playing_strip.py`、`tests/test_toast.py` | 各新控件的单元/像素测试 |
| `resource/icons/{folder,refresh,refresh_all,settings,info,add}.svg` | 图标栏与浮层需要的 6 个新图标 |

**修改**：`core/i18n.py`、`core/theme.py`、`core/theme_qss.py`、`view/main_window.py`、`view/widgets/bottom_panel.py`、`view/widgets/__init__.py`、`presenter/main_presenter.py`、两份 interface properties、`tests/test_view_structure.py`、`tests/test_dead_code_removed.py`、`tests/tools/render_matrix.py`、`README.md`、`docs/superpowers/specs/2026-10-18-ui-batch2-layout-design.md`（§5 的一处订正，见 Task 8）。

**删除**：`view/widgets/now_playing_panel.py`、`view/widgets/library_selector.py`。

---

## Task 1: i18n 占位符与换行修复（前置）

Spec §7 把这条从批次 1 的「暂缓」改判为「必修」，因为 §5 的新反馈文案必须带参数。

**Files:**
- Modify: `core/i18n.py:130-208`
- Create: `tests/test_i18n_substitution.py`

**Interfaces:**
- Consumes: 无
- Produces: `core.i18n.get(keyword, **kwargs)` 与 `get_category(category, keyword, **kwargs)` 同时支持 `{key}` 与 `{{key}}`；properties 值里的 `\n` 在加载时解转义为真实换行；新增模块级私有 `_substitute(value: str, kwargs: dict) -> str`（两处调用共用，消除现有逐字重复）。

- [ ] **Step 1: 写失败的测试**

`tests/test_i18n_substitution.py`（纯 Python，不建 QApplication）：
- `test_single_brace_is_substituted`：`i18n.set_locale('zh_CN')` 后 `i18n.get('status.library_removed', name='Rock') == '媒体库已移除：Rock'`。
- `test_double_brace_still_substituted`：临时写入一条值为 `已加载 {{n}} 个` 的 key，断言 `get(key, n=5) == '已加载 5 个'`，且结果不含 `{`。
- `test_double_brace_not_broken_by_single_pass`：值为 `{{n}}` 时结果必须是 `5`，不得剩成 `{5}` 或 `}` —— 这条决定替换顺序（先双括号后单括号）。
- `test_no_param_keys_are_unchanged`：对 `main.zh_CN.properties` 与 `dialog.zh_CN.properties` 的**全部** key，断言无 kwargs 调用 `get`/`get_category` 的返回值与文件里 `=` 右侧逐字节相同（`\n` 除外，见下一条）。
- `test_newline_is_unescaped`：`i18n.dialog('dialog.confirm_delete_media_lib', path='D:/x')` 的结果含真实 `'\n'` 且不含字面 `'\\n'`。
- `test_missing_key_still_returns_marker`：`i18n.get('no.such.key') == '[MISSING: no.such.key]'`（不得被本次改动破坏）。

Run: `PY -m unittest tests.test_i18n_substitution -v` → Expected: FAIL（单括号与 `\n` 四条红）。

- [ ] **Step 2: 实现**

在 `core/i18n.py` 加 `_substitute(value, kwargs)`：先替换 `{{key}}`，再替换 `{key}`。`get()` 与 `get_category()` 末尾那段逐字重复的循环都改为调用它。在 `load_properties()` 解析值时把 `\n` 解为换行（仅此一种转义，别自造更多）。

- [ ] **Step 3: 运行确认通过**

Run: `PY -m unittest tests.test_i18n_substitution -v` → Expected: PASS（6 tests）。

- [ ] **Step 4: 全量确认不新增失败**

Run: `PY -m unittest discover -s tests -p "test_*.py"` → Expected: `Ran 135 tests`，`FAILED (failures=1)`，仍是既有的那条。

- [ ] **Step 5: 变异验证**

清 `__pycache__` 后，把 `_substitute` 的两次替换顺序调换，确认 `test_double_brace_not_broken_by_single_pass` 变红，还原后全绿。把两次运行的命令与输出记进报告。

- [ ] **Step 6: Commit**

```bash
git add core/i18n.py tests/test_i18n_substitution.py
git commit -m "fix(i18n): 支持单括号占位符并解转义换行"
```

---

## Task 2: 尺寸 token 调整

**Files:**
- Modify: `core/theme.py`（删 `ART_SIZE`，加三个常量）
- Modify: `tests/test_theme.py`（常量清单同步）

**Interfaces:**
- Consumes: 无
- Produces: `STRIP_ART_SIZE = 48`、`RAIL_WIDTH = 56`、`SIDEBAR_WIDTH = 240`；`ART_SIZE` 不再存在。

- [ ] **Step 1: 写失败的测试**

`tests/test_theme.py` 追加 `class Batch2GeometryTest`：断言三个新常量等于 48 / 56 / 240；断言 `not hasattr(theme, 'ART_SIZE')`。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL。

- [ ] **Step 3: 改 `core/theme.py`**

删 `ART_SIZE`，加三个常量。此时 `now_playing_panel.py` 仍引用 `ART_SIZE` —— 用 `from core.theme import STRIP_ART_SIZE` 之外，本任务先让 `NowPlayingPanel.ART_SIZE` 改为字面量 `200` 并加一行注释「Task 9 随本文件一并删除」，以保持每个任务结束时测试全绿。

- [ ] **Step 4: 运行确认通过** → Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add core/theme.py tests/test_theme.py view/widgets/now_playing_panel.py
git commit -m "refactor(theme): 以 STRIP/RAIL/SIDEBAR 尺寸替换 ART_SIZE"
```

---

## Task 3: `ActionRail`

**Files:**
- Create: `view/widgets/action_rail.py`、`tests/test_action_rail.py`
- Create: `resource/icons/{file,folder,refresh,refresh_all,settings,info,add}.svg`（7 个）
- Modify: `core/theme_qss.py`（`#actionRail`、`#railButton` 规则 + `REQUIRED_OBJECT_NAMES`）
- Modify: `view/widgets/__init__.py`

**Interfaces:**
- Consumes: `view.icons.icon(name, color, size, dpr)`；`core.theme.RAIL_WIDTH`、`TRANSPORT_SIZE`；`ThemeManager.tokens`
- Produces:
  - `ACTION_LIBRARY, ACTION_OPEN_FILE, ACTION_OPEN_FOLDER, ACTION_REFRESH, ACTION_REFRESH_ALL, ACTION_APPEARANCE, ACTION_ABOUT` 七个模块级字符串常量，值同名的蛇形串
  - `ActionRail(manager: ThemeManager, parent=None)`，方法 `set_progress(action_id: str, running: bool)`、`recolor(tokens)`；信号 `action_triggered(str)`、`library_panel_requested`
  - `ACTION_IDS: tuple[str, ...]`（七个常量，供测试与 presenter 对账）

- [ ] **Step 1: 写失败的测试**

`tests/test_action_rail.py`，offscreen：
- `test_every_action_has_a_nonempty_tooltip`：遍历 `ACTION_IDS` 找到对应按钮，断言 `tooltip` 非空、不以 `[MISSING` 开头、不含 `{`。
- `test_click_emits_action_triggered`：点每个按钮都发出对应 `action_id`；库图标发 `library_panel_requested` 而**不是** `action_triggered`。
- `test_action_ids_are_unique_and_complete`：`len(set(ACTION_IDS)) == len(ACTION_IDS) == 7`。
- `test_set_progress_disables_and_restores`：`set_progress(ACTION_REFRESH, True)` 后该按钮 `not isEnabled()` 且图标为进行态；`False` 后恢复。
- `test_refresh_all_blocks_refresh_current`：`set_progress(ACTION_REFRESH_ALL, True)` 时 `ACTION_REFRESH` 也禁用（共用库加载路径）；解除后恢复。
- `test_unknown_action_id_raises`：`set_progress('nope', True)` 抛 `ValueError`。
- `test_rail_width_is_the_token_value`：`rail.width()`/`fixedWidth == RAIL_WIDTH`。
- `test_rail_icons_are_recolored`：`set_mode('dark')` 后按钮图标主色等于 `DARK.icon`（复用批次 1 的 `_dominant_colour` 手法）。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL（模块不存在）。

- [ ] **Step 3: 画 7 个新 SVG**

沿用批次 1 约定：`viewBox="0 0 24 24"`、`fill="currentColor"`、单/少路径、手写。`file`（打开文件）、`folder`（打开文件夹）、`refresh`（刷新当前库）、`refresh_all`（双箭头）、`settings`（外观）、`info`（关于）、`add`（添加媒体库，供 Task 4 浮层底部用）。进行态复用 `refresh`，不新画第八个。

- [ ] **Step 4: 实现 `view/widgets/action_rail.py`**

`QVBoxLayout` + 七个 `QToolButton`（`setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)`、`setObjectName('railButton')`、`setCursor(PointingHandCursor)`）。库图标排第一，`addStretch()` 后是外观与关于。每个按钮持一个 `QAction`，`QAction` 同时 `self.addAction(...)` 挂到自己身上以携带快捷键：`ACTION_OPEN_FILE` → `QKeySequence.StandardKey.Open`。tooltip 走 `i18n.get('rail.<id>')`（Task 3 一并补 7 个 key，中英两份）。进行态：保存原图标，`set_progress` 时换成 `refresh` 图标并禁用；`_blocked_pair` 字典声明 `{'refresh_all': ['refresh'], 'refresh': ['refresh_all']}` 实现互斥禁用。

- [ ] **Step 5: 补 QSS 与 objectName**

`core/theme_qss.py`：`#actionRail { background-color: surface_alt; border-right: 1px solid divider }`；`#railButton { background: transparent; border: none; border-radius: RADIUS_MD; width/height: TRANSPORT_SIZE }` 及 `:hover`/`:pressed`/`:disabled`/`:focus`/`[running="true"]`。两个名字进 `REQUIRED_OBJECT_NAMES`。

- [ ] **Step 6: 运行确认通过** → Expected: PASS（8 tests）。

- [ ] **Step 7: 全量 + `setStyleSheet` 计数** → Expected: `FAILED (failures=1)` 且仅既有那条；grep 仍 1 处。

- [ ] **Step 8: Commit**

```bash
git add view/widgets/action_rail.py resource/icons/ core/theme_qss.py tests/test_action_rail.py view/widgets/__init__.py locales/
git commit -m "feat(view): 图标栏 ActionRail 与七个动作"
```

---

## Task 4: `LibrarySidebar`

**Files:**
- Create: `view/widgets/library_sidebar.py`、`tests/test_library_sidebar.py`
- Modify: `core/theme_qss.py`（`#librarySidebar`、`#sidebarTitle`、`#libraryRow`、`#sidebarEmpty` 规则 + `REQUIRED_OBJECT_NAMES`）
- Modify: `view/widgets/__init__.py`

**Interfaces:**
- Consumes: `core.theme.SIDEBAR_WIDTH`、`SPACE_*`、`ROW_HEIGHT`；`view.icons.icon('add'|'folder', ...)`；`service.queue_service.DisplayEntry` 无关；`LibraryConfig`（`.name`、`.path`）
- Produces: `LibrarySidebar(manager: ThemeManager, parent=None)`，方法 `set_libraries(list)`、`set_current(path)`、`show_panel()`、`hide_panel()`、`toggle()`、`is_panel_open() -> bool`、`recolor(tokens)`；信号 `library_selected(str)`、`add_library_requested(str)`

- [ ] **Step 1: 写失败的测试**

`tests/test_library_sidebar.py`，offscreen：
- `test_zero_libraries_shows_empty_state_and_add_entry`：灌 `[]`，断言 `#sidebarEmpty` 文本非空、不以 `[MISSING` 开头，且「添加媒体库」入口可见。
- `test_thirty_libraries_stays_within_window`：灌 30 个库、父窗宽 820，断言 `sidebar.width() <= min(SIDEBAR_WIDTH, 820 - RAIL_WIDTH)`、垂直滚动条可用、无水平滚动条。
- `test_long_library_name_is_elided_not_clipped`：一个 80 字符库名，断言渲染文本带省略号且控件宽度未超。
- `test_clicking_current_library_does_not_reemit`：当前库为 A，点 A 不发 `library_selected`；点 B 发一次且值为 B。
- `test_toggle_is_idempotent`：`toggle()` 两次回到初始可见态。
- `test_escape_closes_panel`：`keyPress(Escape)` 后 `not is_panel_open()`。
- `test_click_outside_closes_panel`：向父窗内容区发一次鼠标按下事件后收起。
- `test_add_entry_emits_path`：走「添加」入口（stub 掉 `QFileDialog.getExistingDirectory`）发出 `add_library_requested`。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL。

- [ ] **Step 3: 实现**

`QFrame` + `QVBoxLayout`：标题行（`playlist.header` 风格的小号 `#sidebarTitle`）、`QScrollArea` 装库行、底部「添加媒体库」行。库行 = `#libraryRow` 的可点控件，显示 `name` + 曲目数（**曲目数本批次不可得**——扫描不读元数据，故只显示名称，见报告说明，别造一个假 0）。当前行用动态属性 `[current="true"]` 标记，样式来自 token。浮层定位：`raise_()` + `setGeometry` 贴父窗内容区左上，宽 `min(SIDEBAR_WIDTH, parent.width() - RAIL_WIDTH)`。Esc 走 `keyPressEvent`；点外部走父窗 `eventFilter` 的 `MouseButtonPress`。

- [ ] **Step 4: 补 QSS + objectName**，三个名字进 `REQUIRED_OBJECT_NAMES`。

- [ ] **Step 5: 运行确认通过** → Expected: PASS（8 tests）。

- [ ] **Step 6: Commit**

```bash
git add view/widgets/library_sidebar.py core/theme_qss.py tests/test_library_sidebar.py view/widgets/__init__.py locales/
git commit -m "feat(view): 曲库浮层 LibrarySidebar"
```

---

## Task 5: `NowPlayingStrip`

**Files:**
- Create: `view/widgets/now_playing_strip.py`、`tests/test_now_playing_strip.py`
- Modify: `core/theme_qss.py`（`#nowPlayingStrip`、`#stripArt`、`#stripTitle`、`#stripArtist`）
- Modify: `view/widgets/__init__.py`

**Interfaces:**
- Consumes: `core.theme.STRIP_ART_SIZE`、`FONT_SIZE_*`；`NowPlayingPanel` 现有的默认封面加载与 PIL→QImage 转换逻辑（迁移而非重写）
- Produces: `NowPlayingStrip(parent=None)`，方法 `update_track_info(title: str, artist: str = "", album: str = "")`、`update_album_art(art_data: Optional[bytes])`、`clear()`、`recolor(tokens)`

- [ ] **Step 1: 写失败的测试**

`tests/test_now_playing_strip.py`，offscreen：
- `test_initial_state_shows_default_cover_not_text`：新建后 `#stripArt` 的 pixmap 非空且等于默认封面（复用批次 1 Task 9 的像素手法）。
- `test_album_art_replaces_default`：喂一张纯色临时 PNG 字节，断言封面主色等于该色且 ≠ 默认封面主色。
- `test_clear_falls_back_to_default_cover`：喂过后 `clear()`，断言回到默认封面。
- `test_title_and_artist_render_and_elide`：80 字符标题 + 艺人在 320px 宽下，断言标题带省略号、未裁出控件外、艺人仍可见。
- `test_empty_artist_stays_empty`：`update_track_info('T', '', '')` 断言艺人文本为空——**不加占位**（批次 1 的 R3 裁定延续）。
- `test_no_english_literals`：源码扫描断言无 `"No Track Playing"` / `"No Art"` / `"Unknown Title"` 字面量。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL。

- [ ] **Step 3: 实现**

`QWidget` + `QHBoxLayout`：`#stripArt`（`STRIP_ART_SIZE` 见方）+ 一个竖排 `QVBoxLayout`（`#stripTitle`、`#stripArtist`）。封面数据转换从 `now_playing_panel.py` 整段搬来（含 PIL 优先、Qt 兜底、异常回落默认封面），**不要重写**这段逻辑。`album` 参数保留在签名里但单行不显示专辑——底部条放三行会挤，且专辑在批次 4 的列结构里才有位置；在代码里写明这个取舍。

- [ ] **Step 4: 补 QSS + objectName**，四个名字进 `REQUIRED_OBJECT_NAMES`。

- [ ] **Step 5: 运行确认通过** → Expected: PASS（6 tests）。

- [ ] **Step 6: Commit**

```bash
git add view/widgets/now_playing_strip.py core/theme_qss.py tests/test_now_playing_strip.py view/widgets/__init__.py
git commit -m "feat(view): 底部正在播放条 NowPlayingStrip"
```

---

## Task 6: `Toast`

**Files:**
- Create: `view/widgets/toast.py`、`tests/test_toast.py`
- Modify: `core/theme_qss.py`（`#toast`、`#toastText`）
- Modify: `view/widgets/__init__.py`

**Interfaces:**
- Consumes: `core.theme` 的 `SPACE_*`、`RADIUS_MD`、token 色
- Produces: `Toast(parent: QWidget)`，方法 `show_toast(message: str, msec: int = 2500)`、`dismiss()`、`current_message() -> str`；无信号

- [ ] **Step 1: 写失败的测试**

`tests/test_toast.py`，offscreen：
- `test_show_toast_sets_text_and_visible`。
- `test_second_toast_replaces_first`：连发两条，断言 `current_message()` 是第二条，且可见 toast 实例数为 1。
- `test_toast_auto_dismisses`：用可注入的假时钟（`Toast` 构造接受可选 `timer_factory`）推进时间后断言 `not isVisible()`；**不要**在测试里 `QTest.qWait` 真等 2.5 秒。
- `test_dismiss_is_idempotent`：连续 `dismiss()` 两次不抛。
- `test_toast_does_not_steal_focus`：显示后 `focusWidget()` 不是 toast 内控件。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL。

- [ ] **Step 3: 实现**

`QFrame` 作为父窗的子控件（不是独立窗口，避免多显示器与 macOS 层级问题），`WA_ShowWithoutActivating` + `Qt.WidgetAttribute.WA_TransparentForMouseEvents`，`QLabel#toastText` 持文本，`QTimer` 单次触发 `dismiss()`。定位：父窗底部内容区居中、控制条上方 `SPACE_3`。`show_toast` 复用同一实例（只改文本 + 重起计时器），这就是「同时最多一条」的实现方式，不要造队列。

- [ ] **Step 4: 补 QSS + objectName**（底色用 `tooltip_bg`/`tooltip_text`，与批次 1 的浮层语言一致）。

- [ ] **Step 5: 运行确认通过** → Expected: PASS（5 tests）。

- [ ] **Step 6: Commit**

```bash
git add view/widgets/toast.py core/theme_qss.py tests/test_toast.py view/widgets/__init__.py
git commit -m "feat(view): 限时反馈浮层 Toast"
```

---

## Task 7: `MainWindow` 重排

本任务是不可拆的一次换壳：装进 rail + 浮层 + strip，删掉 `menuBar()` 与左栏。中间态没有意义，故单提交。

**Files:**
- Modify: `view/main_window.py`（删 `_setup_menu`、`_on_*` 菜单 handler 改接 rail；`_setup_ui` 重写；删 `set_status_message`）
- Modify: `view/widgets/bottom_panel.py`（顶部插入 `NowPlayingStrip` 一行；`update_track_info`/`update_album_art`/`clear` 转发）
- Modify: `tests/test_view_smoke.py`、`tests/test_view_structure.py`
- Modify: `core/theme_qss.py`（`#nowPlayingStrip` 等 strip 规则的宿主容器无需新规则——`#playlistContainer` 只是布局容器，保持透明继承窗口底色，**不要**为它加规则或塞进 `REQUIRED_OBJECT_NAMES`）

**Interfaces:**
- Consumes: Task 3-6 的全部产出（确切签名见各任务 Interfaces 块）
- Produces: `MainWindow(theme_manager, parent=None)` 签名不变；新增 `show_toast(message, msec=2500)`、`set_action_progress(action_id, running)`、`toggle_library_panel()`、`is_library_panel_open() -> bool`；**删除** `set_status_message`；保留 `update_track_info` / `update_album_art` / `clear_now_playing` / `set_libraries` / `set_current_library` / `library_selected` / `manage_libraries_requested` / `manage_appearance_requested` / `refresh_library_requested` / `refresh_all_requested` / `scan_folder_requested` / `add_library_requested`（新，来自浮层的添加）

- [ ] **Step 1: 写失败的测试**

`tests/test_view_structure.py` 追加：
- `test_no_menu_bar`：`main_window.menuBar()` 未创建任何动作（`menuBar().actions() == []` 或不存在可见菜单条）。
- `test_shortcuts_survive_menu_removal`（Review Focus 4）：向主窗口发送 `Ctrl+O` 与 `Ctrl+Q` 的 `QKeyEvent`，断言 `scan_folder_requested` / `close` 被触发。**先确认这条在改动前是绿的**（菜单还在时快捷键本就生效），它的作用是防止删菜单时把它弄丢。
- `test_rail_and_sidebar_in_tree`：`REQUIRED_OBJECT_NAMES` 覆盖到 `#actionRail`、`#librarySidebar`。

`tests/test_view_smoke.py` 追加：
- `test_empty_app_launches`：不灌任何库与条目，构造 + `grab()` 不抛。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL。

- [ ] **Step 3: 重写 `_setup_ui`**

```
central → QHBoxLayout[ ActionRail | contentStack ]
contentStack → QWidget#playlistContainer（含 PlaylistView），LibrarySidebar 作为其兄弟浮层叠加
main_layout → QVBoxLayout[ contentRow, BottomPanel ]
```
删除 `QSplitter` 与 `NowPlayingPanel`；浮层用 `addWidget` 之外的父子叠加方式（不设 layout），靠 `resizeEvent` 重定位。

- [ ] **Step 4: 删 `_setup_menu`，动作改接 rail**

`_setup_menu()` 整段删除。`_setup_connections()` 里改为：`rail.action_triggered` → 一个 `match`/字典分派到 `_on_open_file`、`_on_open_folder`、`_on_refresh_library`、`_on_refresh_all`、`manage_appearance_requested.emit`、`_on_about`；`rail.library_panel_requested` → `toggle_library_panel()`；`sidebar.library_selected` → `_on_library_selected`；`sidebar.add_library_requested` → 新信号 `add_library_requested`。`_on_open_file` 的多文件行为**不改**（spec §6 记为已知缺陷）。

- [ ] **Step 5: 加 `show_toast` / `set_action_progress`，暂留 `set_status_message` 转发**

新增 `show_toast(message, msec=2500)` → `self._toast.show_toast(...)`，`set_action_progress(action_id, running)` → `self._rail.set_progress(...)`，`toggle_library_panel()` / `is_library_panel_open()` → sidebar。
`set_status_message` 本任务**不删**，改为一行转发到 `show_toast`，并加注释 `# Task 8 分流后删除`。理由：presenter 的 14 个调用点在 Task 8 才改，若此处直接删掉，Task 7 的提交会让全量测试变红，违反「每任务不新增失败」的全局约束；留着 presenter 写窗口标题又违反判据 3。一行转发是让两个约束都能满足的最短路径，Task 8 的 `test_no_status_message_calls_left` 负责确保它不会变成永久接口。
`_base_title` 与 `setWindowTitle` 只在 `_setup_window` 发生一次。

- [ ] **Step 6: `BottomPanel` 加 strip 行**

`_setup_ui` 的 `main_layout` 最前面 `addWidget(NowPlayingStrip())`；`update_track_info`/`update_album_art`/`clear_now_playing` 转发给它；`recolor(tokens)` 内调用 strip 的 `recolor`。

- [ ] **Step 7: 运行视图层测试**

Run: `PY -m unittest tests.test_view_smoke tests.test_view_structure tests.test_action_rail tests.test_library_sidebar tests.test_now_playing_strip tests.test_toast -v` → Expected: PASS。
本步骤**不跑全量**：presenter 仍在调用已被移除的 `set_status_message`，全量在 Task 8 之前必然是红的，这是预期的中间态。

- [ ] **Step 7b: macOS 回退方案不在本任务实现**

spec §8 要求真机验证「移除 `QMenuBar` 后 Qt 是否仍合成最小应用菜单」。本机是 Windows，**无法验证**，因此不预先实现隐形 `menuBar()` 回退——那会引入一段没有消费者的代码。改为：在 `view/main_window.py` 的 `_setup_connections` 上方留一行注释指向 spec §8，并在 Task 10 的收尾报告里把该项列为「未验证，macOS 用户合入前必须确认」。

- [ ] **Step 8: Commit**

```bash
git add view/ tests/ core/theme_qss.py
git commit -m "feat(view): 主窗口换为图标栏 + 全宽列表 + 浮层切库外壳"
```

---

## Task 8: presenter 状态分流

**Files:**
- Modify: `presenter/main_presenter.py`（14 个 `set_status_message` 调用点，确切行号见下）
- Modify: `locales/interface/main.{zh_CN,en_US}.properties`
- Create: `tests/test_presenter_status.py`
- Modify: `docs/superpowers/specs/2026-10-18-ui-batch2-layout-design.md`（§5 订正一处）

**Interfaces:**
- Consumes: Task 7 的 `show_toast` / `set_action_progress`
- Produces: presenter 不再调用任何 `set_status_message`；新增 i18n key `status.refreshed_files`（`已刷新 {count} 个文件，来自 {libs} 个媒体库`）、`status.library_switched`（`已切换到媒体库：{name}`）、`status.tracks_loaded`（`已加载 {count} 首曲目`）、`rail.*` 七个（Task 3 已加则复用）

- [ ] **Step 1: 订正 spec §5**

spec 把 `status.theme_save_failed` 归到「错误 → 保持 QMessageBox」，但它**当前就不是**弹窗而是状态文本；改成弹窗是把一次写盘失败升级成模态打断。裁定：归入「反馈」走 toast。改 spec §5 表格那一行并在提交说明里写明这是 spec 订正。

- [ ] **Step 2: 写失败的测试**

`tests/test_presenter_status.py`（用真 `MainWindow` + 假服务，沿用 `tests/test_dead_code_removed.py` 的装配手法）：
- `test_title_never_changes_across_states`（Review Focus 5）：依次触发播放、暂停、切库、刷新开始/结束、加载完成，断言 `windowTitle()` 全程等于 `i18n.get('window.title')`。
- `test_refresh_progress_round_trips`：刷新开始时 `set_action_progress('refresh', True)`，结束时 `False`。
- `test_refresh_result_is_a_toast`：刷新完成后 `show_toast` 被调用一次，且文本含真实数字、不含 `{`。
- `test_no_status_message_calls_left`：源码扫描 `presenter/` 与 `view/`，断言无 `set_status_message`。
- `test_playing_paused_status_removed`：播放/暂停不再产生任何 toast 或进度态调用。
- `test_theme_save_failure_is_toasted`：`set_theme` 返回 False 时 toast 一条、且不调 `show_error`。

- [ ] **Step 3: 运行确认失败** → Expected: FAIL。

- [ ] **Step 4: 改 14 个调用点**

进度态：`:226` refreshing、`:245` refresh_all → `set_action_progress`。
反馈 toast：`:229` library_refreshed、`:248`、`:270`、`:302` library_removed、`:362` theme_save_failed、`:369`、`:373`、`:461` completed、`:536`。
删除：`:402` playing、`:405` paused、`:439` Now playing —— 三者与传输按钮状态和 `NowPlayingStrip` 重复，且都违反判据 3。
`:248`、`:270`、`:536`、`:439` 是硬编码英文，一并换成新 key。
最后删掉 Task 7 留下的 `MainWindow.set_status_message` 一行转发——`test_no_status_message_calls_left` 同时扫 `view/`，会抓住任何残留。

- [ ] **Step 5: 运行确认通过**

Run: `PY -m unittest tests.test_presenter_status tests.test_view_smoke -v` → Expected: PASS。

- [ ] **Step 6: 全量确认不新增失败** → Expected: `FAILED (failures=1)`，仅既有那条。

- [ ] **Step 7: Commit**

```bash
git add presenter/ locales/ tests/test_presenter_status.py docs/superpowers/specs/
git commit -m "refactor(presenter): 状态反馈按进度/反馈/错误三类归位"
```

---

## Task 9: 删除旧面板与结构对账

**Files:**
- Delete: `view/widgets/now_playing_panel.py`、`view/widgets/library_selector.py`
- Modify: `view/widgets/__init__.py`、`view/main_window.py`（残留 import）
- Modify: `tests/test_view_structure.py`、`tests/test_dead_code_removed.py`

**Interfaces:**
- Consumes: Task 7/8 已让两文件无引用
- Produces: `view.widgets` 不再导出 `NowPlayingPanel`、`LibrarySelector`

- [ ] **Step 1: 写失败的测试**

`tests/test_dead_code_removed.py` 追加：
- `test_superseded_panels_are_gone`：`importlib.util.find_spec` 对两个模块均为 `None`，且 `view.widgets` 无这两个属性。
- `test_no_reference_to_superseded_panels`：全仓 `*.py` 扫描无 `NowPlayingPanel` / `LibrarySelector` 字样（测试文件与注释也一并清掉）。

- [ ] **Step 2: 运行确认失败** → Expected: FAIL。

- [ ] **Step 3: 删文件并清引用**

- [ ] **Step 4: 运行确认通过** → Expected: PASS。

- [ ] **Step 5: 全量 + `setStyleSheet` 计数** → Expected: 仅既有 1 失败；grep 1 处。

- [ ] **Step 6: Commit**

```bash
git add -A view/ tests/
git commit -m "refactor(view): 移除被图标栏与浮层取代的左栏组件"
```

---

## Task 10: 渲染矩阵补用例与文档

**Files:**
- Modify: `tests/tools/render_matrix.py`
- Modify: `README.md`
- Create: `docs/superpowers/plans/` 无需改动

**Interfaces:**
- Consumes: 前九个任务的全部产物
- Produces: `render_matrix.py` 输出 **12** 张 PNG：`light|dark` × `empty|populated|thirty-libraries` × `820x520|1100x720`；`--sidebar-open` 额外一张浮层展开态。

- [ ] **Step 1: 扩脚本**

假数据补 30 个库的一组（库名含 80 字符长名与中英混排），浮层展开态一张。`--out` 缺省 `tempfile.mkdtemp()` 并打印路径。

- [ ] **Step 2: 跑并逐张目视**

Run: `QT_QPA_PLATFORM=offscreen PY tests/tools/render_matrix.py --out /tmp/pyplayer-b2`
Expected（逐条核对）：列表宽度 = 窗口宽 − 56；图标栏 7 个图标对齐且无重叠；浮层 30 库可滚、不超窗、长名省略；窄窗 820×520 下 strip 的曲名与艺人不裁出控件；toast 出现时不遮挡列表当前行；两主题均无残留白底/黑底。
再用真实 `windows` QPA 抓一组（批次 1 Task 10 已证明 offscreen 的 `grab()` 会漏掉底色问题）。

- [ ] **Step 3: 真实运行确认**

Run: `PY main.py`。Expected: 正常启动；无菜单栏；`Ctrl+O` 打开文件；图标栏点库图标浮层弹出、选库生效、Esc 收起；刷新时按钮进入进行态；反馈以 toast 出现且中文正确、含真实数字。

- [ ] **Step 4: 更新 README**

「特性」一节删掉 GUI 两栏描述，改述图标栏 + 浮层切库 + 三类状态；目录结构一节同步四个新控件与两个删除项。

- [ ] **Step 5: 全量测试与终态核对**

Run: `PY -m unittest discover -s tests -p "test_*.py"` → Expected: 失败项仅 `test_multiple_libraries_display`。
Run: `grep -rn "setStyleSheet" --include=*.py . | grep -v "^./.venv" | grep -v theme_manager.py` → Expected: 无输出。

- [ ] **Step 6: Commit**

```bash
git add tests/tools/render_matrix.py README.md
git commit -m "test(ui): 批次 2 渲染矩阵补例与文档更新"
```
