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

裁定 R5（2026-10-20，控制器核查后定，本步即计划 Step 2 预留的「改用 `ctx.` 前缀」分支）：不用 `menu.*`。`menu.` 是批次 2 拆掉 `QMenuBar` 后遗留的菜单栏文案块（`main.zh_CN.properties:63-75` 共 13 键），全仓只剩 `menu.exit` 一个消费者（`view/main_window.py:147`），其余 12 键是待清理的死文案。把新的右键文案塞进同一前缀，会让批次 2 遗留的退役键清理从「整块删除」退化成「逐键甄别」；`ctx.` 也与既有的按控件命名前缀（`rail.*`、`sidebar.*`）一致。测试里的 key 同步用 `ctx.`。

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
- Create: `tests/test_playlist_hover.py`

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
- `test_removing_the_playing_track_does_not_silently_point_at_another_song`（Review Focus 1）：播放索引 3，移除含 3 的 `[2,3,4]`，断言 `NowPlayingStrip` 的标题未变、且后续高亮不指向任何已删曲目。
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
- `test_ctrl_a_selects_all`。
- `test_ctrl_up_down_trigger_prev_next`：`Ctrl+↑` → `prev_track_requested`，`Ctrl+↓` → `next_track_requested`。
- `test_plain_up_down_still_navigates_the_list`（判据 5）：裸 `↑`/`↓` 改变 `currentRow`，且**不**触发 prev/next。
- `test_shortcuts_are_owned_by_the_main_window`：`MainWindow` 上 addAction 的快捷键集合含上述全部，且 `PlaylistView`/`BottomPanel` 内部没有各自绑键（防归属分散）。

Run: `PY -m unittest tests.test_playlist_shortcuts -v` → Expected: FAIL。

- [ ] **Step 2: 实现**

`_setup_shortcuts()` 建 `QAction` 并 `self.addAction(...)`；`Delete`/`Enter` 的 context 用 `Qt.Context.WidgetWithChildrenShortcut`，避免在列表外误触发。三个信号从 `PlaylistView` 转发为 View API，presenter 在 `_setup_view_connections` 里接到 Task 5 的两个 handler。

- [ ] **Step 3: 运行确认通过** → Expected: PASS（7 tests）。

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
