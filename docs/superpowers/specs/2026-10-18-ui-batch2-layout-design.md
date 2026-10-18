# PyPlayer UI 批次 2：图标栏外壳与曲库浮层

日期：2026-10-18
状态：待评审
前置：批次 1（设计 token 与主题层），已合入 `main`（合并提交 `88096ea`）
范围：审计清单 B1（左栏空置）、B3（媒体库切换器溢出）、B4（无状态栏）。B2 已在批次 1 修掉。B5（播放列表列结构）因属数据层改造，拆为批次 4。

## 1. 目标

把「左栏 + 播放列表」的两栏结构换成「图标栏 + 全宽列表 + 浮层切库」，并让状态反馈按语义归位，而不是继续往窗口标题里塞。

可核对的成功判据：

1. 左栏与其空置区消失，播放列表宽度 = 窗口宽 − 56px。
2. 30 个媒体库时切换器不溢出、不换行、不裁切。
3. 窗口标题恒为应用名，任何运行状态都不再改写它。
4. 图标栏每个按钮都有非空 tooltip，且每个 `action_id` 都有真实处理方。
5. 参数化状态文案真正填入数值（见 §7，本批次顺带修掉 i18n 的括号缺陷）。
6. 全仓 `setStyleSheet` 仍只有 `view/theme_manager.py` 一处。

## 2. 已定的三个形态决定

这三条来自设计对话，是本 spec 的前提，不是待选项：

- **取消左栏**（B 方案）：`NowPlayingPanel` 整体删除，封面缩到底部控制条左端成为 48px 缩略图 + 曲名/艺人单行，播放列表拿满横向空间。
- **图标栏取代原生菜单栏**（V2）：`menuBar()` 相关代码整块移除，动作全部上栏。macOS 代价见 §8。
- **状态不常驻**（B4 方案 A）：不新建 `QStatusBar`。进度态回到发起动作的按钮上，结果反馈走限时 toast，错误仍走弹窗。

## 3. 组件边界

### 3.1 删除

| 文件 | 原因 |
|---|---|
| `view/widgets/now_playing_panel.py` | 左栏取消；其职责拆给 `NowPlayingStrip` 与 `LibrarySidebar` |
| `view/widgets/library_selector.py` | 横向按钮行 + 末尾 `addStretch` 正是 B3 溢出本身，被浮层取代 |

同时从 `view/widgets/__init__.py` 移除两者导出。

### 3.2 新增

| 单元 | 单一职责 | 对外接口 |
|---|---|---|
| `view/widgets/action_rail.py` → `ActionRail` | 56px 图标栏，承载原菜单全部动作与曲库入口 | `set_progress(action_id: str, running: bool)`、信号 `library_panel_requested`、`action_triggered(action_id: str)` |
| `view/widgets/library_sidebar.py` → `LibrarySidebar` | 浮层曲库面板。**只负责选库与添加库**——刷新与媒体库管理统一归图标栏，不在两处提供同一动作 | `set_libraries(list)`、`set_current(path)`、`show_panel()`/`hide_panel()`/`toggle()`；信号 `library_selected(str)`、`add_library_requested(str)` |
| `view/widgets/now_playing_strip.py` → `NowPlayingStrip` | 控制条左端的封面 + 曲名/艺人单行 | `update_track_info(title, artist, album)`、`update_album_art(bytes)`、`clear()` |
| `view/widgets/toast.py` → `Toast` | 限时反馈浮层 | `show_toast(message: str, msec: int = 2500)`；同时最多一条，后到者替换 |

### 3.3 改造

- `view/main_window.py`：布局由 `QSplitter[左栏 | 列表]` 改为 `QHBoxLayout[ActionRail | 列表]`，底部仍 `BottomPanel`；删除 `_setup_menu()` 整段；`set_status_message()` 从 View 接口移除。
- `view/widgets/bottom_panel.py`：左端嵌入 `NowPlayingStrip`。
- `presenter/main_presenter.py`：状态调用点按 §5 的三类分流；`_on_open_file` 的多文件行为见 §6。
- `core/theme.py`：删除 `ART_SIZE`（左栏没了就无消费者），新增 `STRIP_ART_SIZE = 48` 与 `RAIL_WIDTH = 56`、`SIDEBAR_WIDTH = 240`。
- `core/theme_qss.py`：为四个新控件补规则，objectName 进 `REQUIRED_OBJECT_NAMES`。

## 4. 接口迁移表（presenter 视角）

原则：能保持签名不变的就不动调用点。

| 现有 View 接口 | 批次 2 之后 | presenter 是否改 |
|---|---|---|
| `update_track_info` / `update_album_art` / `clear_now_playing` | `MainWindow` 转发到 `NowPlayingStrip` | 否 |
| `set_libraries` / `set_current_library` | `MainWindow` 转发到 `LibrarySidebar` | 否 |
| `library_selected` 信号 | 由 `LibrarySidebar` 发，`MainWindow` 转发 | 否 |
| `manage_libraries_requested` / `manage_appearance_requested` | 由 `ActionRail` 的 `action_triggered` 分流 | 是（连接点） |
| `set_status_message(msg)` | **移除**，拆成 §5 三类 | 是（全部调用点） |
| `NowPlayingPanel.art_clicked` | **删除**（全仓无消费方） | 否 |
| `MainWindow.set_background_image` / `set_overlay_alpha` | 不变 | 否 |

## 5. 状态反馈的三类分流

现在 `set_status_message` 一个口子混着三种语义，逐个归位：

| 类别 | 现有文案 | 归属 |
|---|---|---|
| 进度态 | `status.refreshing`、`status.refresh_all` | 发起它的图标栏按钮进入进行态（禁用 + 进行态图标），完成即恢复。不产生文本 |
| 结果反馈 | `Refreshed {n} files from {k} libraries`、`Switched to library: {path}`、`status.library_removed`、`status.background_set/cleared` | `Toast`，2.5s 淡出。文案改为走 i18n 并带参数 |
| 错误 | `status.theme_save_failed`、`warning.background_not_found` | 保持 `QMessageBox` |

结果反馈的两条硬编码英文（`main_presenter.py:248`、`:270`）在本批次一并接上 i18n——批次 1 的字面量扫描只禁了特定字符串，没覆盖这类 f-string。

## 6. 边界与错误处理

- **零媒体库首启**：图标栏库图标仍在；点开浮层显示空态 + 「添加媒体库」入口；列表沿用现有空态。
- **浮层尺寸**：宽 `min(SIDEBAR_WIDTH, 窗口宽 − RAIL_WIDTH)`；820×520 下仍浮在列表之上、内部可滚、不出现水平滚动条。
- **图标栏不滚动**：动作固定 7 项（库、打开文件、打开文件夹、刷新当前库、刷新全部、外观设置、关于）。56×~40 共约 280px，最小窗高 500 放得下。「退出」不上栏。
- **可发现性是硬约束**：V2 之下 tooltip 是唯一文字线索，缺 tooltip 视为缺陷而非瑕疵。
- **刷新重入**：进行态期间该按钮禁用；「刷新全部」进行时「刷新当前库」同样禁用——两者共用库加载路径。
- **快捷键**：`Ctrl+O`、`Ctrl+Q` 的 `QAction` 必须继续 `self.addAction()` 挂在主窗口上，菜单不可见不影响生效；有回归测试守。
- **`_on_open_file` 的既有缺陷**：多选文件时只取第一个文件的父目录（[view/main_window.py:226-229](file:///D:/Codes/Python/PyPlayer/view/main_window.py#L226)）。本批次**不改行为**，但图标栏接管该动作时要在 spec 层记为已知缺陷，避免被当成新引入的 bug。

## 7. 一处范围扩大：i18n 括号缺陷（本批次必须先修）

批次 1 把这条判为「先前存在、不并入」而暂缓。本批次**推翻该裁定并纳入范围**，理由是它从「旧文案的小毛病」变成了「新文案的前置条件」：§5 要求结果反馈走带参数的 i18n 文案，而 `core/i18n.py:166` 只替换 `{{key}}`，全仓 properties 却**无一处**使用双括号，于是任何带参数的新文案都会把 `{n}` 原样吐给用户。继续暂缓等于让 §5 无法实现。

修法（最小）：`get()` / `get_category()` 同时支持 `{key}` 与 `{{key}}` 两种形式；顺带解转义 `\n`（当前 5 处多行 `QMessageBox` 文案把 `\n\n` 显示成字面量）。两处都要有测试，且**不得**改变无参数 key 的现有输出。

## 8. macOS：本批次最大的不确定项

移除 `QMenuBar` 后，Qt 在 macOS 上是否仍自动合成最小应用菜单（应用名 / 退出 / About），**无法从代码断定，必须真机验证**。上一提交 `43bbfd8` 专门做过 macOS 菜单栏适配，V2 会把那套惯例拆掉。

因此本批次带一个**回退方案**而非一个假设：若真机验证不成立，则保留一个仅承载应用级项的隐形 `menuBar()`（窗口内不出现菜单条），并在 spec 与代码注释里写明它存在的唯一理由是 macOS 惯例。

本机为 Windows，此项在批次 2 的验收里标记为「未验证」，不得被当作已通过。

## 9. 测试

沿用批次 1 的三件资产：视图冒烟测试、objectName 结构测试、`tests/tools/render_matrix.py`。

新增：

- **ActionRail**：每个动作 tooltip 非空；`action_id` 唯一且每个都在 presenter 有处理方；`set_progress(id, True/False)` 的禁用与恢复；刷新全部进行时刷新当前库被拒。
- **LibrarySidebar**：库数 0 / 1 / 3 / 30 四种下宽度不超窗、可滚动、不裁切；点当前库不重复发信号；`toggle()` 幂等；点列表区与按 Esc 均收起。
- **NowPlayingStrip**：`update_album_art` 后封面像素不等于默认封面；`clear()` 回落默认封面（复用批次 1 Task 9 的像素断言手法）。
- **Toast**：同时最多一条、后到替换先到、到时自动消失。
- **i18n**：`{key}` 与 `{{key}}` 两种都替换；无参数 key 输出逐字节不变；`\n` 解转义。
- **反向回归**：`set_status_message` 必须已从 View 接口消失（沿用批次 1 Task 2 的"断言不存在"写法），防止有人图省事再写回标题。

环境约束沿用批次 1：解释器 `D:/PROGRAMMES/miniconda3/envs/dev_313/python.exe`（`.venv` 无 PyQt6）、`unittest` 不引 pytest、Qt 测试前置 `QT_QPA_PLATFORM=offscreen`、验收标准是**不新增失败**（基线 129 跑 1 失败，那条是 `test_multiple_libraries_display`）。

## 10. 非目标

B5 列结构（批次 4，需先定元数据的获取与缓存策略）、批次 3 的右键菜单/拖拽排序/搜索/快捷键扩展、视频画面渲染、`_on_open_file` 多选行为的修复。

## 11. 风险

| 风险 | 处置 |
|---|---|
| macOS 无原生菜单，退出/关于/快捷键失效 | §8 的回退方案 + 真机验证项，不通过则不合入 macOS 用户 |
| 无文字图标整体可发现性下降 | tooltip 升格为验收判据 4，并有测试钉住 |
| 浮层遮挡列表内容造成"看不见在放哪首" | 浮层只在主动点开时出现，选库/点外/Esc 三处收起；渲染矩阵补窄窗用例 |
| i18n 改动波及既有文案 | §7 要求无参数 key 输出逐字节不变，并单测覆盖 |
| 一次性动 4 新增 + 3 改造 + 2 删除，回归面大 | 沿用批次 1 流程：逐任务提交 + 逐任务审查 + 渲染矩阵目视 |
