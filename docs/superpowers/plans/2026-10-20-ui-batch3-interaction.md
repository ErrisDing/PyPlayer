# PyPlayer UI 批次 3（播放列表交互）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让播放列表支持资源管理器式的多选、右键菜单与键盘操作，并纠正批次 2 遗留的浮层双重偏移坐标假设。

**Architecture:** 选择与索引解析留在 `PlaylistView`（它拥有 `QListView` 与显示索引语义）；菜单构建抽成纯函数模块 `view/widgets/playlist_context_menu.py` 以便脱离窗口单测；hover 由 `PlaylistItemDelegate` 直接绘制（QSS 的 item 子控件规则在本项目从不生效）；动作经三个新信号上抛到 `MainWindow`，再由 presenter 落到队列层已有的 `remove_at_display_index`。本批次不改队列契约。

**Tech Stack:** Python 3.13、PyQt6（Qt 6.11 验证）、unittest。

**Spec:** [docs/superpowers/specs/2026-10-20-ui-batch3-interaction-design.md](../specs/2026-10-20-ui-batch3-interaction-design.md)

## Global Constraints

- 解释器固定 `D:/PROGRAMMES/miniconda3/envs/dev_313/python.exe`（仓库 `.venv` **无 PyQt6**）。不安装任何包。
- 测试框架 `unittest`，不引入 pytest。Qt 测试前置 `QT_QPA_PLATFORM=offscreen`。
- **验收数字一律来自全量**：`cd /d/Codes/Python/PyPlayer && QT_QPA_PLATFORM=offscreen /d/PROGRAMMES/miniconda3/envs/dev_313/python.exe -m unittest discover -s tests -p "test_*.py"`。单模块或单子集跑出的绿**不作为验收证据**。批次 2 曾出现 agent 报「243 跑 1 失败」而全量实为 2 失败（`mock.patch` 用包限定名，discover 把测试文件注册成顶层模块，两个模块对象，patch 静默失效）。
- 基线：批次 3 开工时 `Ran 244 tests, FAILED (failures=1)`，唯一失败是 main 上既有的 `test_player.TestHierarchicalPlaylist.test_multiple_libraries_display`。每任务验收 = **不新增失败**。**该数字随任务推进会变**：Task 1 后 250、Task 1 修复轮后 254、Task 2 后 260——派发词里以「不新增失败」为准，不要把这里写死的数字当作当前实测值。
- 变异检查前先清陈旧字节码：`find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`。
- **不得为 hover 或任何 item 状态新增 QSS 规则**。`PlaylistItemDelegate` 覆写 `paint()` 且不咨询 style，QSS 的 `::item` 规则从不渲染——批次 2 终审已因此抓到一条死规则。item 状态一律走 delegate。
- 全仓 `setStyleSheet` 保持**恰好一处**：`view/theme_manager.py`。
- 新文案同时写 `locales/interface/main.zh_CN.properties` 与 `main.en_US.properties`；不得引入硬编码英文字面量。
- patch 自身模块必须用 `f'{__name__}.attr'` 或 `mock.patch.object`，禁止 `'tests.test_x.attr'` 点号名（已有 AST 守卫 `SelfReferentialPatchTest` 强制）。
- 不使用 `QAction.ActionEvent` 除非 `getattr(QAction, 'ActionEvent', QAction.Activation)` 兜住（Qt 6.9+ vs 声明下限 6.5）。
- 不新增第三方依赖。每任务一次提交；只 commit，**不 push**。
- 本批次**不改队列契约**：只用已有的 `remove_at_display_index`、`clear`、`set_position_by_display_index`。

## Review Focus

规格未写但真实使用会撞上的输入，逐条给出钉住它的测试所在任务：

1. **移除当前正在播放的那一行** —— 队列索引塌缩后播放中曲目不得改变，高亮不得指向另一首歌。→ Task 5 `test_removing_the_playing_track_does_not_silently_point_at_another_song`。
2. **交错索引批量移除**（删 {1,3,5}）—— 若按升序删，删完剩下的是 {0,2,4} 而非 {0,4,6}，等于删错歌。→ Task 5 `test_interleaved_batch_removal_leaves_exactly_the_complement`。
3. **hover 覆盖 playing / selected** —— 悬停在播放行上时底色必须仍是 `playing_bg`。→ Task 4 `test_hover_never_overrides_playing_or_selected`。
4. **`Space` 与 `QListView` 默认行为冲突** —— 若 Space 已被 item toggle 占用，绑播放/暂停会吞掉列表操作。→ Task 1 `test_space_default_behaviour_probe` 决定绑法，Task 6 落实。
5. **右键落在空白区（最后一行以下）** —— 不得弹菜单、不得改动选区、不得对整批操作。→ Task 3 `test_right_click_on_empty_area_does_not_open_menu`。

---

## 文件结构

**新建**

| 文件 | 职责 |
|---|---|
| `view/widgets/playlist_context_menu.py` | 纯函数构建右键 `QMenu`，返回动作与其目标索引；不依赖窗口，可独立单测 |
| `tests/test_playlist_selection.py` | 选择模式、索引解析、右键目标规则 |
| `tests/test_playlist_context_menu.py` | 菜单项构成、文案、i18n key |
| `tests/test_playlist_hover.py` | hover 像素与三层优先级 |
| `tests/test_playlist_actions.py` | 批量移除（含交错、含播放行）、播放选中 |
| `tests/test_playlist_shortcuts.py` | 每个快捷键发真实按键事件断言效果 |

**修改**：`view/widgets/playlist_view.py`、`view/delegates/playlist_delegate.py`、`view/main_window.py`、`presenter/main_presenter.py`、`view/widgets/library_sidebar.py`、`tests/test_library_sidebar.py`、`tests/tools/render_matrix.py`、`README.md`、两份 interface properties。

---

## Task 1: 选择模式升级与索引解析

**Files:**
- Modify: `view/widgets/playlist_view.py:70`（选择模式）、新增 `selected_display_indices()`、`display_index_at()`
- Modify: `view/widgets/playlist_view.py:32-39`（新信号声明）
- Create: `tests/test_playlist_selection.py`

**Interfaces:**
- Consumes: 既有 `PlaylistModel`、`DisplayEntry`
- Produces: `PlaylistView` 上 `SelectionMode.ExtendedSelection`；`selected_display_indices() -> list[int]`（升序去重）；`display_index_at(pos: QPoint, widget: QWidget) -> int`（`pos` 按 `widget` 的坐标空间解释，见裁定 R6；无行时 `-1`）；信号 `play_requested(list[int])`、`remove_requested(list[int])`、`clear_playlist_requested`（本任务只声明，Task 3 才发）

- [ ] **Step 1: 写 Space 默认行为探针测试**

`tests/test_playlist_selection.py` 的 `test_space_default_behaviour_probe`：构造 `PlaylistView`、灌 3 条、把焦点与当前索引设到第 0 行，发一个 `QKeyEvent(KeyPress, Key_Space)`，然后断言并**记录**两件事：`selected_display_indices()` 是否变化、`currentRow()` 是否变化。测试本身不断言期望值，而是把观测结果写进报告，并 `self.assertTrue(True)` 之外的形式记录——目的是决定 Task 6 绑 `Space` 还是 `Ctrl+Space`。

Run: `QT_QPA_PLATFORM=offscreen PY -m unittest tests.test_playlist_selection -v` → Expected: 通过并在输出里打印观测结果。

- [ ] **Step 2: 依据探针结果记录决定**

在报告里写明：`Space` 在 `QListView` 上是否有既有行为；有 → 播放/暂停绑 `Ctrl+Space`；无 → 绑 `Space`。把这个决定连同证据写进 spec §4.4 那一节的下方（追加一行「实测结论」）。

- [ ] **Step 3: 写失败的测试**

同文件追加 `class SelectionTest`：
- `test_selection_mode_is_extended`：`view._list_view.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection`。
- `test_ctrl_click_toggles_individual_rows`：模拟 Ctrl+点击第 0、2 行，断言 `selected_display_indices() == [0, 2]`；再 Ctrl+点击第 2 行，断言 `[0]`。
- `test_shift_click_selects_a_contiguous_range`：点击第 1 行后 Shift+点击第 4 行，断言 `[1, 2, 3, 4]`。
- `test_selected_display_indices_is_sorted_and_deduplicated`：乱序多选后断言返回值升序且无重复。
- `test_display_index_at_returns_minus_one_on_empty_area`：在最后一行以下 200px 与仍在 viewport 内的空白带各取一点，断言返回 `-1`；在第 2 行中点取一点，断言返回 `2`。三点均传 `viewport()` 作坐标来源。

Run: `PY -m unittest tests.test_playlist_selection -v` → Expected: FAIL（仍是 SingleSelection、方法不存在）。

- [ ] **Step 4: 实现**

`view/widgets/playlist_view.py:70` 改 `ExtendedSelection`。`selected_display_indices()` 从 `self._list_view.selectionModel().selectedRows()` 取行号排序去重。`display_index_at(pos, widget)` 先 `self._list_view.viewport().mapFrom(widget, pos)` 再 `indexAt(...)`，无效索引返回 `-1`，否则返回 `index.row()`（R6：坐标来源必须是参数，不能假定成 viewport）。声明三个新信号。

- [ ] **Step 5: 运行确认通过** → Expected: PASS（6 tests）。

- [ ] **Step 6: 全量确认不新增失败** → Expected: `FAILED (failures=1)`，仅既有那条。

- [ ] **Step 7: Commit**

```bash
git add view/widgets/playlist_view.py tests/test_playlist_selection.py docs/superpowers/specs/
git commit -m "feat(view): 播放列表升级为资源管理器式多选并暴露显示索引"
```

---

## Task 2: `playlist_context_menu` 纯函数

**Files:**
- Create: `view/widgets/playlist_context_menu.py`、`tests/test_playlist_context_menu.py`
- Modify: `locales/interface/main.{zh_CN,en_US}.properties`
- Modify: `view/widgets/__init__.py`

**Interfaces:**
- Consumes: `core.i18n.get`
- Produces: `MENU_PLAY, MENU_REMOVE, MENU_CLEAR` 三个字符串常量；`MENU_IDS: tuple[str, ...]`；`build_playlist_menu(target_indices: list[int], target_is_playing: bool, parent: QWidget) -> Optional[QMenu]`——空目标返回 `None`；每个 `QAction` 的 `setData(menu_id)`，且 `objectName('menuItem')`

- [ ] **Step 1: 写失败的测试**

`tests/test_playlist_context_menu.py`：
- `test_returns_none_for_no_target`：`build_playlist_menu([], False, parent)` 返回 `None`。
- `test_menu_actions_and_labels`：目标 `[3]` 且未播放 → 动作顺序为 播放、移除、清空，文案分别等于 `i18n.get('ctx.play')`、`i18n.get('ctx.remove')`、`i18n.get('ctx.clear_playlist')`，且都不含子串 `MISSING`、不含 `{`。（控制器一度以为标记是 `[[MISSING: key]]` 双括号、故判定 `startswith('[MISSING')` 是空守卫——**错了**：`core/i18n.py:190`/`:223` 返回单括号 `[MISSING: key]`，全仓 20 处测试也都按单括号写。双括号只存在于 i18n 的两条 docstring，已一并改正。子串断言比仓库既有的 `assertNotIn('[MISSING', ...)` 更宽，仍然保留。）
- `test_playing_target_shows_pause_instead_of_play`：`target_is_playing=True` 时第一项文案用 `ctx.pause`。
- `test_batch_labels_show_count`：目标 `[1,2,3]` 时移除项文案含 `3`（参数化文案走 `i18n.get('ctx.remove_count', count=3)`）。
- `test_every_action_carries_its_menu_id`：所有动作的 `data()` 集合恰为 `set(MENU_IDS)`。
- `test_no_hardcoded_english_labels`：源码扫描该文件无 `"Play"`/`"Remove"`/`"Clear"` 字面量。

Run: `PY -m unittest tests.test_playlist_context_menu -v` → Expected: FAIL（模块不存在）。

- [ ] **Step 2: 补 i18n key**

两份 locale 各加 `ctx.play`、`ctx.pause`、`ctx.remove`、`ctx.remove_count`（`移除 {count} 项` / `Remove {count} items`）、`ctx.clear_playlist`。

裁定 R5（2026-10-20，控制器核查后定，本步即计划 Step 2 预留的「改用 `ctx.` 前缀」分支）：不用 `menu.*`。`menu.` 是批次 2 拆掉 `QMenuBar` 后遗留的菜单栏文案块（`main.zh_CN.properties:63-75` 共 13 键），全仓只剩 `menu.exit` 一个消费者（`view/main_window.py:232`，批次 3 的行号，撰写本裁定时是 :147），其余 12 键是待清理的死文案。把新的右键文案塞进同一前缀，会让批次 2 遗留的退役键清理从「整块删除」退化成「逐键甄别」；`ctx.` 也与既有的按控件命名前缀（`rail.*`、`sidebar.*`）一致。测试里的 key 同步用 `ctx.`。

- [ ] **Step 3: 实现 `build_playlist_menu`**

单行目标用 `ctx.remove`，多行用 `ctx.remove_count` 带 count。`清空播放列表` 始终追加在最后，与目标之间放一个 separator。

- [ ] **Step 4: 运行确认通过** → Expected: PASS（6 tests）。

- [ ] **Step 5: Commit**

```bash
git add view/widgets/playlist_context_menu.py tests/test_playlist_context_menu.py locales/ view/widgets/__init__.py
git commit -m "feat(view): 播放列表右键菜单构建"
```

---

## Task 3: 右键接线与目标行规则

**Files:**
- Modify: `view/widgets/playlist_view.py`（`contextMenuEvent`、消费 `build_playlist_menu`）
- Modify: `tests/test_playlist_selection.py`

**Interfaces:**
- Consumes: Task 1 的 `selected_display_indices()`、`display_index_at()`、三个信号；Task 2 的 `build_playlist_menu`、`MENU_*`
- Produces: `context_menu_requested` 首次真正 emit；菜单动作 → 信号的映射

- [ ] **Step 1: 写失败的测试**

追加 `class ContextMenuTargetTest`：
- `test_right_click_on_unselected_row_narrows_selection_to_it`：先多选 `[0,1,2]`，右键第 5 行 → 选区变为 `[5]`，菜单目标为 `[5]`。
- `test_right_click_inside_selection_keeps_the_batch`：多选 `[0,1,2]`，右键第 1 行 → 选区仍是 `[0,1,2]`，菜单目标为 `[0,1,2]`。
- `test_right_click_on_empty_area_does_not_open_menu`（Review Focus 5）：右键空白区 → 未弹菜单、选区不变、`context_menu_requested` 未触发。
- `test_menu_play_emits_play_requested` / `..._remove_emits_remove_requested` / `..._clear_emits_clear_playlist_requested`：触发对应动作后，断言收到的索引列表与目标一致。
- `test_context_menu_requested_emitted`：`context_menu_requested` 至少 emit 一次（批次 1 起声明、从未 emit 的那个信号）。
- `test_repeated_right_clicks_leave_no_menu_behind`（裁定 R7，**这条是 Task 2 唯一没能钉住的东西**）：对同一视图连开两次菜单后，断言 `view.findChildren(QMenu)` 不含仍在世的菜单（`0`，或至少计数不随开合增长）。`build_playlist_menu` 把菜单挂到调用方给的 parent 上（Task 2 已用 `assertIs(menu.parent(), parent)` 钉住），所以**每次右键新建就必须弹完即弃**；不建这条测试，「弹一次漏一个 `QMenu`」在批次 2 的守卫下是静默的。

Run: `PY -m unittest tests.test_playlist_selection -v` → Expected: FAIL。

- [ ] **Step 2: 实现 `contextMenuEvent`**

顺序：`display_index_at(event.pos(), self)` → `-1` 则直接返回不发信号；否则按目标规则调整选区；`targets = selected_display_indices()`；`menu = build_playlist_menu(targets, self._is_playing_index_in(targets), self)`；**先 emit `context_menu_requested(targets[0], event)`，再** `menu.exec(...)`；最后按 `action.data()` 分派到三个信号。

emit 在弹窗**之前**、分派之后（与本页原稿「分派后 emit」相反，Task 3 实施时按语义纠正并已用 `_names()` 顺序断言锁死）：`context_menu_requested` 播报的是「用户请求了这个目标的菜单」，其载荷 `targets[0]` 只在没有任何动作跑过之前才保证仍描述用户指的那一行；一旦动作信号触发 Task 5 的移除，行可能已不存在。

`display_index_at` 在 Task 1 修复轮改为**必须显式给出坐标来源控件**（`display_index_at(pos, widget)`，内部 `viewport().mapFrom(widget, pos)`）。理由：`_list_view` 上方还有一个 header，两个坐标空间差一个 header 高度；按 `event.pos()` 的原样传进去会让每个目标行整体上移一行，并把 header 当成真行弹菜单。**本任务不得省略第二个参数。**

菜单生命周期（R7）：`exec()` 返回后必须让本次菜单消亡。生产写法是 `try/finally` 里 `menu.deleteLater()`，**不要**在事件处理器内补 `processEvents()`——计划原稿那句「deleteLater 后补一次 processEvents」经 Task 3 实测**不成立**：本机 Qt 的 `processEvents()`（以及不带事件类型的 `sendPostedEvents()`）不处理 `DeferredDelete`，只有事件循环展开时的定向 flush `sendPostedEvents(None, QEvent.Type.DeferredDelete)` 才真的删掉。测试自己做那次定向 flush 来观察回收结果；生产路径绝不为了测试而跑 `processEvents()`（重入隐患）。

策略取「每次构建 + 弹完即弃」而非「一次性构建并复用」：复用也能让计数不增长，但它会在两次右键之间把一个 `QMenu` 常驻在窗口活树里，正顶撞 R7 要求 `:414` 继续为真的那条。所以残留用例的断言取 **0**，而不是「不增长」——一条断言同时区分两种策略。

别指望 `tests/test_view_structure.py:414` 那条「主窗口活树内无 `QMenu`」兜底：它只构造一个全新 `MainWindow`、从不触发右键，因此看不见「每次右键挂一个、常驻不删」这种泄漏（Task 2 审查推断、Task 3 变异实测：删掉 `deleteLater()` 后只有新用例红，`:414` 全绿）。

先探针、后实现（本仓库不允许假设 Qt 行为）：`QAbstractItemView` 自己实现了 `contextMenuEvent`，右键落在列表上时**事件是否真的传到外层 `PlaylistView`** 取决于它 accept 还是 ignore。写一个临时脚本，对 `_list_view.viewport()` 与外层 `PlaylistView` 各打一次右键，打印两处 `contextMenuEvent` 是否被调用；据此决定钩子挂在哪一层（若子级吃掉，改挂 `_list_view` 并传 `viewport()` 作坐标来源）。脚本用完即删，不进仓库。

`globalPosition()` 在 Qt 6.1 才有，沿用批次 2 已确立的兜底写法。

- [ ] **Step 3: 运行确认通过** → Expected: PASS。

- [ ] **Step 4: 全量确认不新增失败** → Expected: 仅既有 1 失败。

- [ ] **Step 5: Commit**

```bash
git add view/widgets/playlist_view.py tests/test_playlist_selection.py
git commit -m "feat(view): 右键菜单接线，目标行遵循资源管理器规则"
```

---

## Task 4: delegate 的 hover 分支

**Files:**
- Modify: `view/delegates/playlist_delegate.py`（`paint` 的底色分支）
- Modify: `view/widgets/playlist_view.py`（`viewport()` 上的 `WA_Hover`）
- Create: `tests/test_playlist_hover.py`

第三个文件是 Task 4 实施时经实测取得的**必要偏差**（审查已认可）：没有这个属性，`option.state` 永远不带 `State_MouseOver`，Step 2 那条 `elif` 就是够不着的死代码。属性归 View 而非 delegate——delegate 伸手去改自己所属视图是层次倒置。

**Interfaces:**
- Consumes: `ThemeManager.tokens.hover_bg`、既有 `playing_bg`/`selection_bg`/`playing_bar`
- Produces: 底色优先级 `playing_bg > selection_bg > hover_bg > 无`

**不得新增任何 QSS item 规则**（全局约束）。

- [ ] **Step 1: 写失败的测试**

`tests/test_playlist_hover.py`，offscreen，真实 `PlaylistView` + `ThemeManager('light')`，`grab()` 后取像素：
- `test_hovered_plain_row_paints_hover_bg`：把鼠标移到某普通行（`QTest.mouseMove`），断言该行中段像素等于 `tokens.hover_bg`。
- `test_hover_never_overrides_playing_or_selected`（Review Focus 3）：分别悬停在播放行与选中行上，断言像素仍是 `playing_bg` / `selection_bg`。
- `test_hover_applies_in_both_themes`：`light` 与 `dark` 各测一次第一条。
- `test_no_item_qss_rule_was_added`：`build_qss(LIGHT, ...)` 的输出中，`hover_bg` 只出现在非 `#playlistView::item` 的规则里——防止有人用 QSS 实现 hover。

Run: `PY -m unittest tests.test_playlist_hover -v` → Expected: FAIL（第一条红）。

- [ ] **Step 2: 实现**

在 `paint` 的底色分支链尾加 `elif option.state & QStyle.StateFlag.State_MouseOver:` 画 `t.hover_bg`，位置必须在 playing 与 selected 之后。

- [ ] **Step 3: 运行确认通过** → Expected: PASS（4 tests）。

- [ ] **Step 4: 变异验证**：把 hover 分支挪到 playing 之前，确认第二条测试红；还原。

- [ ] **Step 5: Commit**

```bash
git add view/delegates/playlist_delegate.py tests/test_playlist_hover.py
git commit -m "feat(view): 列表行 hover 反馈，优先级低于播放与选中"
```

---

## Task 5: presenter 的批量动作

**Files:**
- Modify: `presenter/main_presenter.py`（`_on_remove_tracks`、`_on_play_tracks`）
- Create: `tests/test_playlist_actions.py`

**Interfaces:**
- Consumes: 队列已有的 `remove_at_display_index(int) -> bool`、`set_position_by_display_index(int)`、`clear()`；`MainWindow` 转发信号（Task 6 接线，本任务先测 presenter）

**裁定 R8（2026-10-20，控制器实测）：`remove_at_display_index` 不维护播放位置，队列的 `PlaybackPosition` 在删除后是陈旧值。** 实测（5 条扁平队列、播 T2）：删掉 **T2 本身** → `get_current_track()` 返回 **T3**；删掉 **T0（播放行上方的任意行）** → 同样返回 **T3**，且 `_position.display_index` 也停旧。`clear()` 会重置 `_position`，而按行删除不会（`service/queue_service.py:486-513` 只 `_rebuild_display_entries()`）。全仓 `remove_at_display_index` **零调用方、零测试**——本任务它是第一个调用者，也是第一个把这个隐患变成活路径的人。

后果与要求：
1. **不得改队列**（本批次范围线）。所以 presenter 必须**以曲目身份**重解析：删除前先 `get_current_track()` 取路径，删完后在 `get_display_entries()` 里按路径找它的新显示索引——找到就 `set_position_by_display_index(new_idx)` 把位置钉回去，找不到（播的那首被删了）就 `clear_now_playing()` 并保持停止态。绝不能把 `get_current_track()` 的删除后读数当作真相。
2. 交错用例（Review Focus 2）之外，**必须各有专测**：「删掉播放行本身」与「删掉播放行上方一行」，两条都断言现在播的仍是原来那首（或按语义清空）——上面实测过，这两条正是原实现会静默播错歌的形状。
3. 另加一条**特征化测试**（characterization）直接打在队列上，把「删除后 `get_current_track()` 指向另一首」这个事实钉住并写明是队列层的待修债，交给批次 5（队列变更契约）。没有它，后来人只会在 presenter 里看到一段解释不清的补偿逻辑。
- Produces: `MainPresenter._on_remove_tracks(indices: list[int]) -> None`、`_on_play_tracks(indices: list[int]) -> None`

- [ ] **Step 1: 写失败的测试**

`tests/test_playlist_actions.py`（真 `MainWindow` + 真 `QueueService` + 假播放服务，沿用 `tests/test_presenter_status.py` 的装配）：
- `test_interleaved_batch_removal_leaves_exactly_the_complement`（Review Focus 2）：7 条，移除 `[1,3,5]`，断言剩余显示索引对应原 `{0,2,4,6}` 的曲目路径。
- `test_removing_the_playing_track_does_not_silently_point_at_another_song`（Review Focus 1）：播放索引 3，移除含 3 的 `[2,3,4]`，断言 `NowPlayingStrip` **已清空**且无任何行带播放高亮。原稿此处写「断言标题未变」，与 R8 互斥：歌已被删，唯一能让标题「未变」的实现就是继续标题着一首不存在的曲目，正是 spec:110 点名的最危险形状（Task 5 审查裁定，`tests/test_playlist_actions.py` 的用例文档已把这层理由写进测试自身）。「标题未变」这条语义归 `test_removing_a_row_above_the_playing_row_keeps_the_same_song_playing`——那里歌确实还在。
- `test_removal_is_descending_order`：用一个记录调用顺序的假队列，断言传给 `remove_at_display_index` 的索引严格递减。
- `test_empty_selection_does_not_call_the_queue`：`_on_remove_tracks([])` → 队列方法零调用。
- `test_play_tracks_uses_lowest_display_index`：`_on_play_tracks([4,1,2])` → 播的是索引 1。
- `test_removing_every_row_resets_playback_state`：全删后 `clear_now_playing` 被调、播放态复位。

Run: `PY -m unittest tests.test_playlist_actions -v` → Expected: FAIL。

- [ ] **Step 2: 实现**

`_on_remove_tracks`：`for idx in sorted(set(indices), reverse=True): self._queue.remove_at_display_index(idx)`；随后刷新显示列表并重新解析播放位置（用队列现有的位置查询，**不要**新增队列 API）。`_on_play_tracks`：空列表直接返回；否则取 `min(indices)` 走既有的双击播放路径。

- [ ] **Step 3: 运行确认通过** → Expected: PASS（6 tests）。

- [ ] **Step 4: 变异验证**：把 `reverse=True` 去掉，确认交错测试与降序测试双双变红；还原。

- [ ] **Step 5: Commit**

```bash
git add presenter/main_presenter.py tests/test_playlist_actions.py
git commit -m "feat(presenter): 批量移除按索引降序执行，播放取选区最小索引"
```

---

## Task 6: MainWindow 转发与快捷键

**Files:**
- Modify: `view/main_window.py`（转发三个信号、新增 `_setup_shortcuts()`）
- Create: `tests/test_playlist_shortcuts.py`
- Modify: `locales/interface/main.{zh_CN,en_US}.properties`（快捷键 tooltip/文案，若需）

**Interfaces:**
- Consumes: Task 1/3 的三个信号、Task 5 的两个 presenter handler、Task 1 Step 2 关于 `Space` 的结论
- Produces: View API `play_tracks_requested(list[int])`、`remove_tracks_requested(list[int])`、`clear_playlist_requested`；`MainWindow._setup_shortcuts()`

- [ ] **Step 1: 写失败的测试**

`tests/test_playlist_shortcuts.py`，offscreen，向真实 `MainWindow` 发 `QKeyEvent`：
- `test_play_pause_shortcut`：按 Task 1 决定的键，断言 `play_pause_requested` emit 一次。
- `test_delete_removes_selection`：多选后按 `Delete` → `remove_tracks_requested` 收到升序索引列表。
- `test_enter_plays_selection`：多选后按 `Enter` → `play_tracks_requested` 收到 `[最小索引]`。
- ~~`test_ctrl_a_selects_all`~~ → 实作为 `test_ctrl_a_is_left_to_qt_native_select_all`（R11 附带要求 8：仓库没实现 Ctrl+A，是 Qt 原生 `selectAll`）。
- `test_ctrl_up_down_trigger_prev_next`：`Ctrl+↑` → `prev_track_requested`，`Ctrl+↓` → `next_track_requested`。
- `test_plain_up_down_still_navigates_the_list`（判据 5）：裸 `↑`/`↓` 改变 `currentRow`，且**不**触发 prev/next。
- `test_shortcuts_are_owned_by_the_main_window`：**裁定 R10（2026-10-20，源自 Task 1 审查的遗留洞）：必须有一条测试证明快捷键**抢在焦点控件之前**消费了按键。** Task 1 实测裸 `Space` 会推进当前行、把选区替换成那一行，而 `Ctrl+Space` 命中同一个内置 handler；它**对 Task 6 绑什么键、是否消费按键毫无约束力**，原因不是投递方式——Task 6 修复轮推翻并纠正了控制器原先写的那句「`app.sendEvent` 直投会绕开窗口级 shortcut 派发」：实测投给焦点控件的 `QKeyEvent` **照样**命中窗口级 QAction（本批的 R10 用例与 `tests/test_view_structure.py::_press_shortcut` 走的都是这条路）。真正的原因是**当时仓库里根本没有任何绑定**，所以那次探针只能证明列表自己吃不吃这个键。红线因此目前只活在 spec 的文字里。要求：向 `PlaylistView` 的**焦点控件**投按键（不是投给 MainWindow，也不是直接调 QAction），断言 ① 播放/暂停信号 emit 恰好一次，② `selected_display_indices()` 与当前行**一字未动**。少了 ②，「快捷键与列表导航双触发」这个形状在本仓测不出来，而它正是 R4 当初要避免的事。

`test_shortcuts_are_owned_by_the_main_window`：
Run: `PY -m unittest tests.test_playlist_shortcuts -v` → Expected: FAIL。

- [ ] **Step 2: 实现**

**裁定 R9（2026-10-20，控制器核查 Task 5 交付时立）：`clear_playlist_requested` 必须有 presenter 落点，本任务不得让它变成「发射了但没人接」的路线。** 现状：`PlaylistView` 自 Task 3 起真会发射它，MainWindow 按计划把它转发成 View API，而 Task 5 的 Produces 只给了 `_on_remove_tracks` / `_on_play_tracks` 两个槽——也就是说接完线之后，点「清空播放列表」会一路发信号然后**什么也不发生**。批次 2 就抓过一次同形状缺陷（rail 只连 `clicked`、`Ctrl+O` 按下去毫无反应），那条的教训是：**信号被发射且被连接，但末端没有落点，仍然全绿**。要求：新增 presenter 槽（复用既有 `_queue.clear()` 路径，`presenter/main_presenter.py:341` 附近已有一次调用），清空队列并复位播放态与 `NowPlayingStrip`，并加一条**贯穿全链**的测试：从 View 发射 → presenter → 队列空 + now playing 复位。断言必须落在末端效果上，不能只断「槽被连上了」。

**裁定 R11（2026-10-20，Task 6 审查 Important 1 的修复回合立）：`Delete` 与 `Enter` 由 `PlaylistView.keyPressEvent` 承接，其余快捷键（`Ctrl+Space`/`Ctrl+↑`/`Ctrl+↓`/`Ctrl+Q`）仍集中在 `MainWindow._setup_shortcuts()`。** 本段取代上面 Step 2 原来那两句，因为那两句里有两个错，而按它们实现的 `3356222` 把整扇窗口的 Enter 与 Delete 按死了。

1. **枚举名写错**：`Qt.Context.WidgetWithChildrenShortcut` 在 PyQt6 6.11 上不存在（`AttributeError`），正确全名是 `Qt.ShortcutContext.WidgetWithChildrenShortcut`。
2. **`WidgetWithChildrenShortcut` 给不了「避免在列表外误触发」**（原话的第二半）：挂在**窗口**上的该 context 匹配窗口子树内**任意**焦点——Task 6 实测音量滑块有焦点时按 `Delete` 照样整批删除（`tests/test_playlist_shortcuts.py::OutsideTheListTest` 当初就是抓这个红的）。它真正保住的是另一件事：parented `QDialog` 是**另一个窗口**，而 `isAncestorOf` 止于窗口边界（批次 2 实测），所以对话框里的 Enter/Delete 不被窗口抢。
3. **审查建议的机制在本绑定上不存在**：`QAction.setShortcutWidget` 是 Qt C++ 的 API，PyQt6 6.11 没有包装它——`hasattr(QAction, 'setShortcutWidget')` 为 `False`，调用即 `AttributeError`（修复回合探针 v1 实测）。退一步用「窗口建的 action 挂到视图上」（`playlist_view.addAction(action)` + 同一个 context）实测**可以**做到子树限定，但它违反本节原本的归属要求，也要改写 `test_the_widgets_bind_no_shortcuts_of_their_own`，因此不取。
4. **在槽里加焦点闸不是范围控制，而是把缺陷藏起来**：窗口级快捷键一旦匹配，Qt 已经**消费**了这次按键，槽里 `return` 不会把它还给焦点控件。实测（焦点在 `#playButton`，代码为 `3356222`）：按钮自己的 `keyPressEvent` 对 `Enter`/`Delete` 计数 **0**，而一个**完全没有绑定**的同款按钮计数 **1**。代价是控制条五个 `QPushButton`、每一个 `LibraryRow`、以及批次 6 要加的搜索 `QLineEdit` 全部失去 Enter——并且全绿。
5. **把 context 收窄成 `WidgetShortcut` 会把功能一起关掉**：探针 v3 config B 实测，列表内按 `Enter`/`Delete` 也不再触发（`ACTION_FIRED=0`，落回列表原生 handler）。窗口层的 context 只有「窗口」这一档，往下收不会换来子树限定。
6. **`PlaylistView.keyPressEvent` 为什么是自愈的**（探针 v7，焦点真在内部 `QListView` 上）：没有窗口绑定后，`Delete`/`Enter`/小键盘 `Key_Enter` 都会**冒泡到外层视图**（`reached_outer_view=1`，且列表自身的行/选区纹丝不动 `row 4->4 sel [4]->[4]`），而裸 `Space` 与裸 `↑↓` **根本到不了**外层（`reached_outer_view=0`，它们在内部被 accept 并移动光标）。也就是：**能进这个方法按键，定义上就是列表此刻没在用的按键**——不需要焦点账本，也不可能抢焦点控件的键。`Ctrl+Space`/`Ctrl+↑`/`Ctrl+↓` 三条实测仍恰好一次、且列表当前行不动（R10 的消费的半边照旧由窗口 action 提供）。
7. **offscreen 测不到「Enter 激活按钮」，谁也不准照这条写断言**：对照实验（裸窗口、一个 `QPushButton`、**任何地方都没有绑定**）下 `QTest.keyClick`、`QTest.keyPress+keyRelease`、裸 `sendEvent` 三种投法对 `Key_Return` 与 `Key_Enter` 全都给出 `pressed=0 clicked=0`，而同一个按钮对 `Key_Space` 给出 `pressed=1 clicked=1`。所以「按键回到焦点控件」的可证观测只有两件：接收方 `KeyPress` 计数器（被吞 0 / 未被吞 1，配 `Space` 作阳性对照），以及 `QLineEdit` 的 `returnPressed`/文本变化（`abcXdef` → Delete → `abcdef`）。
8. 两个附带要求：**小键盘 `Enter` 必须一起接**（spec §5 写的是 `Enter`，Qt 给主键盘 `Key_Return` 与小键盘 `Key_Enter` 两个码，只绑一个等于 keypad 死掉——实测 `Key_Enter` 在只绑 `'Return'` 时无人应答），且这一步同时改写 Step 1 里 `test_ctrl_a_selects_all` 的名字为 `test_ctrl_a_is_left_to_qt_native_select_all`（仓库**没有**实现 Ctrl+A，它是 Qt 原生 `selectAll`，旧名字读起来像我们自己做的）。
9. **R11 是 spec §5「快捷键的 QAction 集中在 `MainWindow._setup_shortcuts()`」的第二个例外**——第一个是批次 2 刻意钉在 `ActionRail` 上的 `Ctrl+O`（`view/widgets/action_rail.py:223` 真的 `setShortcut`）；这条由 Task 6 修复轮复审更正，原文说「第一个」会把读者引向「rail 那处不合规」的误判。，并且给批次 4 划了一条边界：进度条与音量滑块**不得**自带按键绑定，否则窗口/视图两层都会 answers 同一个键。
10. **「`QListWidget` 的 `Delete` 会删行，所以拿它作对照」是假的，别再照这个前提写探针或结论**（修复回合实测，PyQt 6.11 / offscreen，`tests/test_playlist_shortcuts.py::NativeDeleteModelProbeTest` 每次跑都打印）：3 行、选中第 1 行的 `QListWidget` 收到 `Key_Delete` → `accepted=False`、`count 3 -> 3`、`widget.actions()` 里**没有任何带 shortcut 的 action**（`[]`）、`model().removeRows(1, 0)` → **False** 且行数仍 3；`PlaylistModel` 同样 `removeRows(1,0)=False`、且没 override 该方法。同一个探针里，`PlaylistView` 的外层 `keyPressEvent` 对 `Delete`/`Return`/`Key_Enter` 三个都 `seen=[该键]`、当前行 `1 -> 1`，对裸 `Space`/裸 `↓` 是 `seen=[]`、`1 -> 2`（列表自己吃掉）。结论要说准：R11 靠的是「**view 不吃这三个键**」这一条 Qt 事实，不是「`PlaylistModel` 不会删行」——两者这次实测**都是**真的，但前者才是承重的那根，`QListWidget` 在这一点上并不构成差异，因此探针改测「同一按键在下层是否被消费」，并显式钉住 `Down` 的边界条件（光标在最后一行时下层不消费，按键会上浮，探针每次先把光标放回第 1 行）。

本步其余部分不变：`_setup_shortcuts()` 建 `QAction` 并 `self.addAction(...)`（现在只剩三条播放/切歌 action，加批次 2 的 `Ctrl+Q`），三个信号从 `PlaylistView` 转发为 View API，presenter 在 `_setup_view_connections` 里接到 Task 5 的两个 handler。

- [ ] **Step 3: 运行确认通过** → Expected: PASS。原稿写「7 tests」是派发前的用例数；实作为 22 条（R9/R10/R11 与探针各占一批），以全量 discover 不新增失败为准。

- [ ] **Step 4: 全量确认不新增失败** → Expected: 仅既有 1 失败。

- [ ] **Step 5: Commit**

```bash
git add view/main_window.py presenter/main_presenter.py tests/test_playlist_shortcuts.py locales/
git commit -m "feat(view): 播放列表快捷键集中到主窗口并接上批量动作"
```

---

## Task 7: 修浮层双重偏移坐标假设

**Files:**
- Modify: `view/widgets/library_sidebar.py:456`（`_place_panel`）
- Modify: `tests/test_library_sidebar.py:472`、`:975`（被固化的错误前提）

**Interfaces:**
- Consumes: 批次 2 的事实——浮层父级是已扣除图标栏的 `content_stack`
- Produces: `_place_panel` 以父级原点定位，`x = 0`，宽度上限 `min(SIDEBAR_WIDTH, parent.width())`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_library_sidebar.py` 追加：
- `test_panel_is_parented_to_the_content_stack_not_the_window`：断言浮层的 `parentWidget()` 是内容容器而非 `MainWindow` 本身（把批次 2 终审定位的事实钉住）。
- `test_panel_left_edge_aligns_with_its_parent`：展开后断言 `panel.x() == 0`（父级坐标系），且映射到窗口坐标后 `panel.mapTo(window, QPoint(0,0)).x() == RAIL_WIDTH`——即**没有**双重偏移。
- 改写既有的 `:472`（原 `x >= RAIL_WIDTH`）与 `:975` 的 fixture 注释，使它们陈述正确前提而不是固化错误前提。

Run: `PY -m unittest tests.test_library_sidebar -v` → Expected: FAIL（新断言红）。

- [ ] **Step 2: 实现**

`x = 0`；宽度 `min(SIDEBAR_WIDTH, self.parentWidget().width())`；y 与高度沿用现有算术但不再双扣 `RAIL_WIDTH`。

- [ ] **Step 3: 运行确认通过** → Expected: PASS。

- [ ] **Step 4: 目视复核**：跑 `tests/tools/render_matrix.py --out /tmp/b3`，看浮层展开帧确认图标栏与面板之间无多余间隙、面板未溢出窗口。

- [ ] **Step 5: Commit**

```bash
git add view/widgets/library_sidebar.py tests/test_library_sidebar.py
git commit -m "fix(view): 浮层以内容容器为坐标原点，消除双重 RAIL_WIDTH 偏移"
```

---

## Task 8: 渲染矩阵补例与收尾验证

**Files:**
- Modify: `tests/tools/render_matrix.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: 前七个任务的全部产物
- Produces: 矩阵新增 `hover`、`multi-selected`、`context-menu` 三种状态帧

- [ ] **Step 1: 扩脚本**：在既有 12 帧基础上新增三帧（悬停某行、多选 3 行、右键菜单展开），菜单帧需真实弹出，注意 offscreen 下 `QMenu.exec` 阻塞——改用 `menu.grab()` 而非弹出。

- [ ] **Step 2: 跑并逐张目视**：hover 可见且不与 playing/selected 抢色；多选高亮可辨；菜单文案中英正确、无 `[MISSING`、无 `{`；批次 2 遗留的间隙已消失。

Run: `QT_QPA_PLATFORM=offscreen PY tests/tools/render_matrix.py --out /tmp/b3`

- [ ] **Step 3: 真实运行确认**：`PY main.py`。逐项手测：Ctrl/Shift 多选、右键批量移除（含删掉正在播放那首）、`Delete`、`Enter`、`Space` 或 `Ctrl+Space`、`Ctrl+A`、`Ctrl+↑/↓`、裸 `↑/↓` 仍正常导航。

- [ ] **Step 4: 更新 README**：交互一节写明多选语义、右键菜单项、快捷键表；并保留批次 2 的 macOS 未验证声明（本批次未触及）。

- [ ] **Step 5: 全量与终态核对**

Run: 全量 discover → Expected: 失败项仅 `test_multiple_libraries_display`。
Run: `grep -rn "setStyleSheet" --include=*.py . | grep -v "^./.venv" | grep -v theme_manager.py` → Expected: 无输出。

- [ ] **Step 6: Commit**

```bash
git add tests/tools/render_matrix.py README.md
git commit -m "test(ui): 批次 3 渲染矩阵补 hover、多选与右键菜单帧"
```
