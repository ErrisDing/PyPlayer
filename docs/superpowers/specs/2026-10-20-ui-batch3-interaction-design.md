# PyPlayer UI 批次 3：播放列表交互

日期：2026-10-20
状态：待评审
前置：批次 1（主题层，`88096ea`）、批次 2（图标栏外壳，`fb60763`），均已合入 `main`
范围：审计清单 C1（右键菜单）、C2（hover 反馈）、C3（快捷键），外加修批次 2 遗留的浮层坐标假设。

## 1. 目标

让播放列表能被键盘和右键正常操作，并把批次 2 留下的浮层双重偏移坐标假设连测试一起纠正。

可核对的成功判据：

1. 多选行为与 Windows 资源管理器一致：`Ctrl+点击` 切换单项、`Shift+点击` 选区间、`Ctrl+A` 全选。
2. 右键作用于**光标下那行**；该行在选区内则对整批生效。
3. 批量移除 N 行后队列长度正确，且**当前播放曲目不因删除错位而改变**。
4. 两张主题下 hover 均可见，且 hover 不覆盖 playing / selected 的底色。
5. 每个快捷键都有测试覆盖，且 `Up`/`Down` 的列表原生导航未被破坏。
6. 全量 `discover -s tests` 绿（唯一失败为既有的 `test_multiple_libraries_display`）。
7. 浮层展开时与图标栏之间无多余间隙；`_place_panel` 不再双重减去 `RAIL_WIDTH`。

## 2. 边界：为什么只有这些

批次 2 之后仍然只有一条队列写入路径：`service/queue_service.py:127-164` 的 `build_from_tracks/folders/nodes` 是**整体替换**，另有 `clear()` 与 `remove_at_display_index()`。**没有 append、没有 insert、没有 move。**

因此以下三项与 C4 排序、C5 搜索同属队列变更契约改造，一并推到批次 5/6，不在本批次：

- **拖入外部文件**：只能整库重建，会清空用户当前队列——反直觉的数据丢失，不做。
- **拖拽排序**：需要 `move`。
- **加入播放队列**（右键菜单项）：需要 `append`。
- **搜索/过滤**：需要显示索引与队列索引的双向映射，风险最高。

本批次刻意保持纯视图层：不改队列契约、不改缓存格式、不改 `DisplayEntry`。

## 3. 组件

| 文件 | 变化 |
|---|---|
| `view/widgets/playlist_view.py` | `SingleSelection` → `ExtendedSelection`；新增 `contextMenuEvent` 使 `context_menu_requested`（批次 1 起声明、至今无 emit）终于有主；新增 `selected_display_indices() -> list[int]`、`display_index_at(pos: QPoint) -> int`；新信号 `play_requested(list[int])`、`remove_requested(list[int])`、`clear_playlist_requested` |
| **新建** `view/widgets/playlist_context_menu.py` | `build_playlist_menu(target_indices: list[int], target_is_playing: bool, parent: QWidget) -> QMenu` |
| `view/delegates/playlist_delegate.py` | 补 `State_MouseOver` 分支，画 `tokens.hover_bg` |
| `view/main_window.py` | 转发三个新信号为 View 公开 API；新增 `_setup_shortcuts()` |
| `presenter/main_presenter.py` | `_on_remove_tracks`、`_on_play_tracks` |
| `view/widgets/library_sidebar.py` | 修 `_place_panel` 坐标假设（§6） |

`playlist_context_menu` 单独成文件的理由：菜单构建可脱离窗口单测，而 `playlist_view` 要同时扛选择模式、索引语义与事件路由，再加菜单会超出一个职责。

## 4. 四个必须钉死的决策

### 4.1 hover 由 delegate 画，禁止加 QSS 规则

批次 2 终审抓到 `#playlistView::item` 的 padding/分隔线规则**存在但从不渲染**——delegate 覆写 `paint()` 且不咨询 style，QSS 的 item 子控件规则因此无效。若本批次为 hover 加一条 `#playlistView::item:hover` QSS 规则，就是重犯同一个错，还会新增一条零佩戴者的死规则。

所以：hover 只在 delegate 里画，取 `tokens.hover_bg`；`core/theme_qss.py` **不加**任何 item 规则。

绘制优先级（自上而下短路，不得叠加）：`playing_bg` > `selection_bg` > `hover_bg` > 无。播放行即使被悬停也必须仍是播放底色。

### 4.2 批量移除必须按索引降序

`remove_at_display_index(display_idx)` 是单条 API。升序删除时，删掉第 3 行后原第 5 行已成为第 4 行——会删错曲目。

规约：`sorted(set(indices), reverse=True)` 之后逐个删。测试必须覆盖「删 {1,3,5} 后剩下的正好是 {0,2,4,6}」这种交错情形，而不是只删相邻两行。

### 4.3 右键目标行规则

光标下的行若不在当前选区内 → 先把它设为唯一选中项，菜单作用于它；若已在选区内 → 不改选区，菜单作用于整批。这是资源管理器语义，与用户指定的多选行为一致。

`display_index_at()` 对空白区（最后一行以下）返回 `-1`，此时**不弹菜单**。

### 4.4 `Space` 先实测再定

`QListView` 默认可能把 `Space` 用于 item 的 toggle，与「播放/暂停」冲突。实现第一步是写一个探针测试确认默认行为：

- 若 `Space` 在列表里有既有行为 → 播放/暂停改绑 `Ctrl+Space`，并在 spec 与代码注释记录这个退让；
- 若无 → 绑 `Space`。

不假设结论。

## 5. 快捷键

| 键 | 动作 | 备注 |
|---|---|---|
| `Space` 或 `Ctrl+Space` | 播放/暂停 | 见 §4.4 |
| `Delete` | 从播放列表移除选中 | 走 §4.2 降序 |
| `Enter` | 播放选中 | 多行选中时取**显示索引最小**的那一行（不是最后点击的行），与双击语义一致 |
| `Ctrl+A` | 全选 | Qt 原生，仅测试确认 |
| `Ctrl+↑` / `Ctrl+↓` | 上一首 / 下一首 | `↑`/`↓` 保持列表原生导航，**不劫持** |
| `Ctrl+O` / `Ctrl+Q` | 已有，不动 | 批次 2 已钉 |

快捷键的 `QAction` 集中在 `MainWindow._setup_shortcuts()`，与批次 2 的图标栏动作同源；不得在 widget 内部各自绑键，否则快捷键归属再次分散。

## 6. 修批次 2 的浮层坐标假设

批次 2 终审已定位：浮层挂在**已扣除图标栏的** `content_stack` 上，而 `_place_panel` 仍写 `x = RAIL_WIDTH`（`view/widgets/library_sidebar.py:456`），于是双重偏移；宽度 clamp 也双扣一次 `RAIL_WIDTH`（最小尺寸以上无害）。

要一起改的是**被固化成断言的错误前提**：`tests/test_library_sidebar.py:472`（`x >= RAIL_WIDTH`）与 `:975` 的 fixture 注释都假设了父级铺满整窗。只改常数而不改这两处，测试会把错误前提继续锁住。

正确前提：浮层的父级坐标系原点在 `content_stack` 左上角，因此 `x = 0`、宽度上限 = `min(SIDEBAR_WIDTH, parent.width())`。

## 7. 错误处理

- 空白区右键（`display_index_at() == -1`）不弹菜单、不发信号。
- 选区为空时 `Delete` 与右键「移除」不产生调用（不得传空列表给 presenter 再靠循环兜底）。
- 移除**当前正在播放**的曲目：允许，但队列索引变化后必须重新解析播放位置，不得让播放中高亮指向另一首歌。这条是本批次最危险的失败模式，必须有专门测试。
- 移除全部行 → 等价于清空，播放状态与 `NowPlayingStrip` 一并复位。
- 菜单项文案全部走 i18n，中英两份同步；不得出现批次 1 那类硬编码英文。

## 8. 测试

沿用批次 1/2 资产：视图冒烟、objectName 结构测试、`KNOWN_DEAD_SELECTORS` 与反向守卫、渲染矩阵。

新增：

- **选择行为**：`Ctrl+点击` 切换、`Shift+点击` 区间、`Ctrl+A` 全选，断言 `selected_display_indices()` 的实际内容。
- **右键目标解析**：光标行在选区内 / 不在选区内 / 空白区三种，断言菜单作用范围与是否弹出。
- **批量移除**：交错索引 `{1,3,5}`；含当前播放行；全部行；空选区。断言剩余索引集合与播放中曲目。
- **hover 像素**：真实 `PlaylistView` 上把鼠标移到一行，断言该行底色等于 `tokens.hover_bg`；再对播放行与选中行各测一次，断言 hover **不**覆盖它们。双主题。
- **快捷键**：每个键发真实 `QKeyEvent`，断言对应信号或状态变化；`Up`/`Down` 断言列表导航未被劫持。
- **浮层坐标**：断言浮层左边缘与 `content_stack` 左边缘对齐（`x == 0`），并断言父级是 `content_stack` 而非窗口——即纠正 §6 那两个被固化的前提。

**验收口径（批次 2 的教训，写死）**：测试数字必须来自 `python -m unittest discover -s tests -p "test_*.py"` 全量输出。单模块或单子集跑出的绿不作为验收证据——批次 2 曾出现 agent 报「243 跑 1 失败」而全量实为 2 失败（`mock.patch` 用包限定名而 discover 注册为顶层模块，两个模块对象，patch 静默失效）。

环境沿用：解释器 `D:/PROGRAMMES/miniconda3/envs/dev_313/python.exe`（`.venv` 无 PyQt6）、`unittest` 不引 pytest、Qt 测试前置 `QT_QPA_PLATFORM=offscreen`、变异检查前先清 `__pycache__`。

## 9. 非目标

拖入外部文件、拖拽排序、搜索/过滤、加入播放队列、多选自定义播放顺序、队列契约变更。全部归属批次 5（队列变更契约）与批次 6（过滤与索引映射）。

## 10. 风险

| 风险 | 处置 |
|---|---|
| 批量移除删错歌 | §4.2 降序 + 交错索引测试 + 含播放中行的测试 |
| 移除当前播放行导致播放中指向另一首 | §7 专门测试，本批次最危险项 |
| `Space` 与列表默认行为冲突 | §4.4 先实测，不假设 |
| 又加一条不渲染的 QSS 规则 | §4.1 明令禁止，hover 只走 delegate |
| 修坐标时常数改了、错误前提仍被测试锁住 | §6 明确要求同批改 `test_library_sidebar.py:472` 与 `:975` |
| 快捷键归属再次分散到各 widget | §5 集中在 `_setup_shortcuts()` |
