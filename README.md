# PyPlayer - Python Music/Video Player

一个基于 Python 的多媒体播放器，支持 MP3、WAV、MP4、AVI 等常见格式。提供命令行和图形界面两种使用方式。

## 特性 / Features

- 🎵 **音频播放**: MP3, WAV, FLAC, OGG, M4A, AAC, AIFF, AU, NCM (所有格式支持seek)
- 🎬 **视频播放**: AVI, MP4, MKV, MOV, WMV
- 🔐 **NCM 支持**: 网易云音乐加密格式，自动解包播放（通过 ncmdump 工具）
- 💻 **GUI 模式**: 基于 PyQt6 的现代图形界面（跨平台）
- ⌨️ **TUI 模式**: curses 终端界面 (Unix/Linux/macOS)
- 🌐 **国际化 (i18n)**: 支持中文 (zh_CN) 和英文 (en_US)，根据系统 locale 自动切换
- 🚀 **Python 3.13 兼容**: 使用 soundfile + sounddevice 后端，无 audioop 依赖

## 媒体库管理 / Media Library

- 📚 **多库管理**: 持久化配置支持，统一管理多个媒体目录（添加、删除、排序）
- 🔄 **快速切换**: 在多个媒体库之间快速切换，无需重新扫描
- 💾 **JSON 缓存**: 扫描结果自动缓存，基于目录修改时间自动检测过期
- 🔄 **智能刷新**: 手动刷新单个或全部媒体库
- 🎯 **队列架构**: 文件夹作为独立播放单元，支持文件夹内顺序播放
- 📍 **相对位置**: 播放列表展示文件相对路径（如 `[Rock/Albums]`）

## 播放功能 / Playback Features

- 🔄 **自动播放**: 曲目播放完毕自动跳转下一首
- 🎨 **正在播放条 (Now Playing strip)**: 封面 + 曲名/艺人两行，位于底部控制栏内（批次 2 起不再是左侧面板），空间不足时省略号截断、悬停看全名
- ⏱️ **进度条与计时器**: 实时显示播放进度，支持拖拽跳转（所有音频格式）
- 📝 **元数据提取**: 自动读取 ID3、FLAC、M4A、OGG、NCM 标签信息

## 界面布局 / Interface Layout (批次 2 / batch 2)

菜单栏与左侧面板已整体移除。窗口现在由五部分组成：

- **56 px 图标栏 (ActionRail)**: 固定在左侧的七个动作（打开文件、打开文件夹、刷新当前库、刷新全部、媒体库切换、外观设置、关于），Ctrl+Q 退出挂在窗口级快捷键上。
- **全宽播放列表**: 列表宽度恒等于窗口宽度减 56 px，不再被任何左栏占用。
- **浮层媒体库面板 (LibrarySidebar)**: 由图标栏的媒体库按钮开合，浮在列表之上而不向其取宽；页脚集中了添加媒体库与管理媒体库两个入口。选择库、点击面板外或 Esc 都会收起面板。面板左边缘与其父容器（图标栏右侧的内容区）原点重合，因此**与图标栏之间没有间隙**（批次 3 修正了批次 2 在这里双重扣除 56 px 的坐标假设；渲染矩阵的 `--sidebar-open` 帧把这条量成 `gap=0 FLUSH ON THE RAIL`）。
- **正在播放条**: 见上，位于底部栏第一行。
- **限时提示 (Toast)**: 一两行文字的瞬时反馈，2.5 秒后自动消失。

状态反馈按三类分流 / status is routed three ways: 进度显示在发起它的图标栏按钮上（running 态），成功反馈走 toast，错误仍是模态对话框；窗口标题恒为应用名，不再被任何运行时状态改写。
Progress rides on the rail button that started it, feedback is a transient toast, errors stay dialogs -- and the window title is never rewritten by runtime state.

- ⚠️ **macOS 注意 / macOS caveat**: 批次 2 删除了原生菜单栏。Qt 在没有任何 `QMenuBar` 内容时是否仍会合成一个最小应用菜单（应用名、退出等），**尚未在真实 macOS 硬件上验证**（本仓库在 Windows 上开发，离屏平台无法回答该问题）。批次 3 没有触及外壳或菜单结构，这条声明原样保留。macOS 用户在升级到此版本前必须先在实际设备上确认这一点；若 Qt 不再合成应用菜单，Cmd+Q 之外的系统级菜单项将不复存在。
  The native menu bar was removed in batch 2. Whether Qt still synthesises an application menu with no `QMenuBar` content has **not been verified on real macOS hardware**; batch 3 changed nothing about the shell or the menu structure, so the caveat stands unchanged. Confirm it on an actual device before a macOS user upgrades.

## 播放列表交互 / Playlist Interaction (批次 3 + 批次 4 / batch 3 + batch 4)

- 🖱️ **多选语义 = Windows 资源管理器**: `Ctrl+点击` 切换单行、`Shift+点击` 选择区间、`Ctrl+A` 全选。选区读回是 `PlaylistView.selected_display_indices()`，**升序去重的显示索引**（可见列表里的行号），不是队列的 `node_idx`。
- 🎯 **右键目标规则**: 光标下那行不在选区内 → 选区收缩为它，菜单只作用于它；已在选区内 → 不改选区，菜单作用于整批；空白区（最后一行以下、header 条、空列表）→ 不弹菜单、不发信号、不动选区。
- 📋 **右键菜单三项**: `播放`（目标批次里含正在播放那行时改成 `暂停`）、`从播放列表移除`（多行时是 `移除 {count} 项`）、分隔线之后 `清空播放列表`。文案全部走 `ctx.*` 两组 locale 同步；不用 `menu.*` 前缀——那是批次 2 拆掉 `QMenuBar` 后遗留的菜单栏文案块。
- ⌨️ **快捷键 / Shortcuts**:

  | 键 | 动作 | 归属 |
  |---|---|---|
  | `Delete` | 移除整个选区（按显示索引**降序**删，否则交错删除会删错歌） | `PlaylistView.keyPressEvent` |
  | `Enter` / 小键盘 `Enter` | 播放选区中显示索引最小的那行（与双击同源） | 同上 |
  | `Ctrl+Space` | 播放 / 暂停 | `MainWindow._setup_shortcuts()` |
  | `Ctrl+↑` / `Ctrl+↓` | 上一首 / 下一首 | 同上 |
  | `Ctrl+Q` | 退出 | 同上（批次 2） |
  | `Ctrl+O` | 打开文件 | `ActionRail`（批次 2 刻意钉在按钮上） |
  | `↑` / `↓` / 裸 `Space` | **列表原生导航，本批次不劫持** | `QListView` |
  | `Ctrl+A` | 全选 | **Qt 原生 `selectAll`，仓库没有自己实现**，只有一条测试钉住它仍是原生行为 |

  裸 `Space` 让给列表而不是播放/暂停，是实测决定的：`QListView` 的 `Space` 会把当前行下移一行并选中它，一次按下就能塌缩整个选区，所以播放/暂停退到 `Ctrl+Space`。`Delete`/`Enter` 之所以是**窗口层绑定的两个例外**：`QAction.setShortcutWidget` 在 PyQt6 6.11 里根本不存在，而窗口级快捷键一旦匹配 Qt 就已消费按键——槽里再判焦点也还不回按钮和输入框（实测 `#playButton` 的 `keyPressEvent` 计数 0）。反过来，`QListView` 不吃这三个键，它们才会冒泡到外层视图，所以「能进这个 handler 的按键」定义上就是列表此刻没在用的按键。
- 🎨 **行状态一律 delegate 绘制**: 底色优先级 `playing_bg` > `selection_bg` > `hover_bg` > 无，三条是 `elif` 链、从不叠加；hover 还需要 `QListView.viewport()` 上的 `WA_Hover`，否则 Qt 根本不发 `State_MouseOver`。QSS 的 `#playlistView::item` 规则在本项目**从不渲染**（delegate 覆写 `paint()` 且不咨询 style），所以一条也没有。
- 🧯 **删除的两种危险形状**: 移除**正在播放**那行 → 清空正在播放条并保持停止态，不会把高亮指向另一首；移除播放行**上方**的行 → 播放中曲目不变（presenter 以曲目身份重解析新的显示索引）。

### 元数据三列与两个记号 / Three metadata columns and two marks (批次 4 / batch 4)

- 📊 **列网格（方案 P，整块右锚定）**: 名字列之后依次是 **时长**（`COLUMN_DURATION_WIDTH` = 56px，**右对齐**，好让数字按位对齐）、**艺人**、**专辑**（各 `COLUMN_TEXT_WIDTH` = 120px，左对齐），列间距 `SPACE_2` = 8px（`COLUMN_GAP` 就是它，网格不引入第二个间距值）。只有名字列浮动：行的右端属于三列，`[relative_position]` 脚注因此从"行右端"搬进"名字块内右对齐"，贴住时长列这条稳定列。
- 🙈 **让位规则只有一个作者**: `metadata_columns_fit()` 同时回答行和表头 —— 窄到放不下"三列 + 96px 名字下限"时，三列连同表头的三个词**一起**消失，把行还给名字，绝不会出现"表头写着列名而行上没有列"。本机实测的让位阈值是 432/448px 一档（见下方第 15 条真机核对里引用的 B4-R24）。
- 🔣 **两个记号的语义**: `⋯`（U+22EF）= **pending**，"还没取过，后台正在补"；`—`（U+2014）= **unknown**，"取过了（或按规则跳过了），标签里没有" —— 它**永远不会**自己变成值，`.ncm` 就是这一类（解密有副作用，本批不自动提取）。**folder 行的三个数据格是空的**：文件夹头不拥有文件，没有可查的路径，画空白而不是画记号 —— 若按状态词而不是 `is_folder` 分支，库里每个文件夹头都会挂上一排 `⋯`。
- 🧭 **状态词决定格子，值不决定**（裁定 B4-R17）: 队列里可以存在自相矛盾的行（刷新把已有值的行放回 pending），显示层只读状态词。`known` 行里**单个字段**缺失只标那一格（时长 `—`、艺人照画），因为空白读起来是"还没取"——那是反方向的谎。未识别的状态词画 unknown 记号，绝不画空白（空白是 folder 的答案）。三态词只有 `service/metadata_store` 的 `STATE_PENDING/STATE_UNKNOWN/STATE_KNOWN` 三个字符串，任何消费方一律 import（裁定 B4-R5）。
- ⏱️ **时长字符串**: 统一走 `view/time_format.format_time`（与底部进度条同一份实现，仓库里只允许有一个 `def format_time`），`MM:SS` 或 `HH:MM:SS`。`duration <= 0` 在进缓存前就被归一为 `null`（裁定 B4-R7），所以 `0:00` 不可能出现在这三列里 —— 提取器用 `0.0` 表达"读不到"，那是"取不到"而不是"零秒"。
- 🎨 **没有 per-state QSS**: 记号用 `text_muted`、值用 `text_secondary`，都是 delegate 的画笔；行状态（playing / selected / hover）与列状态互不相干，`#playlistView::item` 规则依然一条也没有。
- 📸 **`--metadata` 十张帧**: `python tests/tools/render_matrix.py --out DIR --metadata --crops` 产出 `metadata-full` / `metadata-pending` / `metadata-unknown` / `metadata-folder` / `metadata-legacy-cache` 各深浅两张，全部在 **1200×720 + 40 行**（必出滚动条）这一档，因为表头与行网格的错位只在滚动时发生。pending 与 unknown 两张把记号打在**同一行**上，两帧只差一个码位——本机实测这两张 PNG **逐字节相同**（退化字体把两个码位光栅成同一个框，正是第 14 条要真人看的那件事），所以它们的证据只在字符串层与墨迹位置上。folder 那张把**表头下面第一行**留成未答：表头行（显示行 13）的三个格子是空白、紧接其下的文件行（显示行 14）在同一条带上画 `⋯`，空白与记号的差别于是可以在同一张裁剪图里被眼睛比出来（此前这张与 `metadata-full` 逐字节相同，等于没有这张帧）。每张帧都自带前置断言，不满足就停下而不交图：滚动条真的可见（否则拒绝测对齐）、四个表头词逐边零容差压在各自列上、记号串与码位、对实测底色的 WCAG 对比度 ≥ 4.5:1、legacy 帧磁盘上的文件 `version` 真是 `1.0` 且没有 `md` 键。

## 需真机核对 / Requires a human on a real desktop (批次 3 + 批次 4 / batch 3 + batch 4)

下面每一条都被**实测判定为离屏平台观察不到**，所以本批次的测试一条也没有主张它们——不是测试的缺口，而是交付的一部分。
运行方式：`python main.py` 逐项手测；另外两次矩阵跑（`--capture window` 与 `--interaction`）在下面第 13 条点名。批次 4 的第 14 到 17 条各自点名 `--metadata` 里的一处打印或测量，那十张帧本身**在离屏就能跑**（`python tests/tools/render_matrix.py --out DIR --metadata --crops`，跑法与每张帧的前置断言见上文「元数据三列与两个记号」一节），真机要看的只是它们证不到的那一半。
Every item below was measured to be unobservable offscreen, so no test in this batch claims it. This is a deliverable, not a gap.
批次 2 的 macOS 声明（见上文「界面布局」一节的 ⚠️）仍然成立，第 6 条就是它；批次 4 没有触及外壳或菜单结构，那条声明原样保留。
**第 14 到 20 条是批次 4 的账**，每一条都是账本裁定明写的代价（B4-R22/R24/R25/R28/R29），不是待办的排查线索。

1. **`Enter` 真的激活 `#playButton` 与 `LibraryRow` 按钮**。离屏对聚焦按钮注入 Enter 报 `pressed=0 clicked=0`，所以 Task 6 只能用投递计数器断言。**这份清单里风险最高的一条**：它正是裁定 R11 要恢复的那个行为，若真机不成立，键盘层就是在交付一个自动测试无法兑现的承诺。
2. **带真实 `KeypadModifier` 的小键盘 `Enter`**。范围已订正：只有「修饰键那一半」需要人。`Key_Enter` 的**代码路径**已被 `tests/test_playlist_shortcuts.py::test_numpad_enter_plays_selection` 钉住（它按的是 `(Key_Enter, NO_MODS)`），而 `PlaylistView.keyPressEvent` 有意不查修饰键；自动路径看不见的是真实按键的**到达形状**本身。
3. **新菜单与正在播放条文案的中文可读性**——离屏把中文画成方框。
4. **DARK 下 hover 是否真的看得见**：`hover_bg` 比交替底色**更暗**。按本仓库量表（BT.709 luma，通道为 gamma 编码值，**不是** WCAG 相对亮度）：DARK `#2a2d2e` 对交替底 `#2d2d30` 是 **−0.30**、对实测纯底 `#242424` 是 **+3.31**；LIGHT 是 **−1.96** 与 **−5.49**（实测纯底 `#fefefe`）。「这算不算反馈」只能由眼睛判。
5. **右键菜单作为活弹窗**：矩阵帧是 `QMenu.grab()` 合成图，弹窗自身的原生边框、阴影、边界翻转与指针响应都不在里面。更尖锐的一半：生产 `_popup_menu` 的函数体（`return menu.exec(global_pos)`，`view/widgets/playlist_view.py`）**在任何自动路径都没执行过**——本工具的帧与所有菜单测试都替换了这个缝。所以那一帧证明的是**路由与构建**，不是**交互**：菜单是否模态打开在光标处、是否跟随指针、点击是否生效。
6. **macOS**：移除 `QMenuBar` 后 Qt 是否仍合成应用菜单（批次 2 的升级前置检查，本批次未变）。
7. **spec §10 的交互走查**：Ctrl/Shift 多选、右键批量移除（含删掉正在播放那首）、`Delete`、`Enter`、`Space` vs `Ctrl+Space`、`Ctrl+A`、`Ctrl+↑/↓`、裸 `↑/↓` 仍能导航、面板与图标栏齐平无间隙。
8. **自发（非注入）右键落在空白区**——最后一行以下、header 条、空列表。`PlaylistView.contextMenuEvent` 明确拒绝替这个问题下结论，并把答案**按名字推给真机核对**（`view/widgets/playlist_view.py:240-246`：空白路径既不 accept 也不 ignore，于是「被忽略的事件是否会继续上行到祖先」在本批次无人观测）。这是本批次代码自己记账的那笔欠债。
9. **指针移开后 hover 底色是否真的消失**。hover 帧拍的是指针**到来**，而 `park_cursor()` 只是把指针挪到播放行、从未离开列表，所以没有任何自动路径看着那片颜色退场；若 `State_MouseOver` 卡住不清，帧仍然会通过守卫。
10. **多选在两套主题下是否可辨**（不只看 hover）。奇数行是最紧的一档：`selection_bg` 在 DARK 只比交替底 `#2d2d30` 高 **+2.42** luma 点（`#2f343a`），在 LIGHT 比 `#f5f5f5` 低 **−2.55**（`#eceff1`）——即 LIGHT 下选中奇数行读作**变暗**。同一把量表见第 4 条。请判断一眼能否认出整批，以及它与 `playing_bg` 并排时是否分得开。
11. **真实运行的声音那一半**。关于「移除正在播放那行」的自动断言全是**状态**断言：测试里的 playback service 是 mock（`tests/test_playlist_actions.py:174` 自陈「The engine is a mock」），最强的一条只是 `playback.stop.called`——stop 被**调用**过，不等于声音停了。真机请确认：删掉播放行后声音真的停（无尾音、无偷换成另一首）、正在播放条与进度跟着复位；同一趟走查的另一半——删掉播放行**上方**的行时播放不中断。
12. **HiDPI**。`view/icons.py:91` 的 `icon(..., dpr)` 2× 光栅化路径在离屏永远走不到（离屏报 device pixel ratio 1），工具文档也把它列进「读 PNG 读不出来的东西」。请在缩放显示上跑 `--capture window`，核对图标栏与传输键图标是原生 2× 而非放大的 1×。
13. **确认「跳过」这件事本身**。在真实桌面上跑一次
    `python tests/tools/render_matrix.py --out DIR --capture window --interaction`：
    应当打印两条 `hover SKIPPED on the 'windows' QPA` 并且**不**写出任何 `*_hover_1100x720.png`，
    而多选帧与菜单帧照常写出。理由——真实 QPA 不肯让 harness 移动指针——目前是 `cursor_lands()`
    里一次 `platformName()` 比较，**不是本批次观测到的事实**（已在工具里改写成假说）；这一跑要么把它升级为实测，要么推翻它。
14. **U+22EF（`⋯`）的字体覆盖检查**（账本 **B4-R25**）。验什么：真机上 pending 行的记号与 unknown 行的记号**形状不同**（三个点 vs 一横）。为什么 offscreen 证不了：本机离屏字体把**每个**码位——`M`、`x`、`…`、U+FFFD、`⋯`、`—` 一律——光栅成同一个 12px 空心框，`--metadata` 的 pending 与 unknown 两张帧把记号打在**同一行的同一列位置**上，工具打印的 `metadata pair census` 实测两帧墨迹 run **完全相同**（`[[1061, 11]]` == `[[1061, 11]]`，两帧 PNG 因此逐字节相同、md5 相等）。所以这些帧只能证"各自有墨迹 + 字符串层是两个不同码位 + 对底色 4.5:1 达标"，证不了"眼睛分得出"。失败意味着什么：**真字体缺该码位时 pending 会退化成与 unknown 同一个方框，spec 判据 3 会以完全相同的方式静默失效**——所有自动断言仍然全绿，而"还没取"与"取不到"在屏幕上再也没人能分辨，正是判据 3 要防的那件事。可行的修法是换 `meta.pending` 的写法（例如 `…`，U+2026 覆盖率高得多），但那要同时动两份 locale 与钉码位的用例。
15. **≥1 小时曲目的时长是否完整显示**（账本 **B4-R24**）。验什么：找一首真实长度跨过 `1:00:00` 的曲目，读时长列**实际画出的字符串**——是 `1:02:03` 还是 `1:0…`。不要只看"有没有点"。为什么 offscreen 证不了：`COLUMN_DURATION_WIDTH` 56px 与 `HH:MM:SS` 的宽度之争原本是用离屏退化字体量出来的（每字形 12px，约为真字体两倍，那把坏尺量出 `1:02:03`=84px、`Duration`=104px），`--metadata` 帧里 `metadata duration row 1: cell '1:02:03', band 56px, advance 105px …` 那一行量的仍是替代字体，不是用户看到的字体。失败意味着什么：`elidedText` 会把 `1:02:03` 收成 `1:0…`，**省略号吃掉分钟位比硬切更坏**——看着仍整齐，读出来是错的长度。若真溢出：**只抬 `COLUMN_DURATION_WIDTH` 到 72，不再多**，并同时复核 en 表头词宽（`Time` 保持不动；`Duration` 那句是坏尺产物）。抬到 88/112 会把三列的让位阈值从实测 432/448 推到 464/488，每多 1px 都在那一段窗口宽度里整片藏掉三列。
16. **残缺字形与省略号观感**（账本 **B4-R29**）。验什么：三列文本与名字列的省略语言是否**一致**——都是右省略号，没有哪一格把字切掉半个字形。为什么 offscreen 证不了：120px 带配出厂字号在离屏正好是 10 个整框（120 = 10×12），**根本切不出残框**，该性质只能由 56px@9pt、120px@20pt 两档（run 宽度实测能红）加上字符串层（delegate 交给 `drawText` 的确实是省略后的串）钉住。失败意味着什么：真机上 120px 带会常态化切字，若哪一格走了硬切而不是省略号，那一列的尾巴会永远少半个字，而这是行高与列宽都正确、只有内容被啃掉的缺陷，最容易被放过。
17. **真实窗口缩放 / 滚动条出现时表头与列网格是否仍对齐**（账本 **B4-R28**）。验什么：拖动窗口宽度跨过让位阈值、让垂直滚动条出现与消失，看四个表头词是否始终**逐边**压在各自列上。为什么 offscreen 只证了一半：`--metadata` 十张帧与 `tests/test_playlist_columns.py::HeaderGridAlignmentTest` 都在真实 `MainWindow` 1200×720 + 40 行（必出滚动条，实测 `list=1144`、`viewport=1132`）上量到逐边 0 偏差；离屏看不到的是**动态过程**——拖动途中 `viewport` Resize 事件与布局取整的先后、真实窗口管理器附加的边框宽度。失败意味着什么：测试采**逐边零容差**而不是 ±1px 是有意选择——容差会把真实存在的 off-by-one（修复轮实测 **+11px** = 垂直滚动条 10 + 边框 1）吸进误差里；因此未来 Qt 版本布局取整差 1px 就会红，**那是要看的，不是要忍的**。
18. **`refresh_all` 之后屏幕只显示最后一个库**、**`load_all_libraries` 在生产里零调用者（启动只加载第一个库）**（账本 **B4-R22**）。验什么：点「刷新全部」，确认每个库的三列最终都被补齐并各自落盘（第二次打开该库不再重新提取），同时注意**屏幕上只有最后一个库的队列**。为什么 offscreen 证不了：这是多库外壳的既有形状（批 2/3 起"每库重建一次播放表，最后一个胜出"），要真实点击与真实等待。失败意味着什么：本批只保证"每库都被答完并各自写回自己的缓存文件"；若真机上其余库永远不补列，问题在"启动只加载第一个库"与单活计划叠出的批 2/3 形状，不在元数据层。多库同屏显示不是本批的交付面。
19. **重叠路径会被提取两次、重绘两次**。验什么：把一个库放进另一个库里（`os.walk` 递归会把同一文件列进两个库），观察它是否出现两行、`⋯` 是否两次变值、耗时是否翻倍。为什么 offscreen 证不了：需要真实磁盘上的嵌套库与真实提取。失败意味着什么：**已知代价，本批裁定不改**——跨库去重会改动"每 target 一次投递"的计数规则（那是 sweep 收尾写回的判据），把去重塞进显示层等于用特殊案例顶掉一条不变量。若真机上这份代价不可接受，改动点在扫描层。
20. **大库首扫期间一直显示 `⋯` 是否被接受**。验什么：打开一个几千行的冷库，看开头那几分钟三列全是 `⋯` 会不会被读成卡死。为什么 offscreen 证不了：真实提取耗时、真实磁盘、真实线程池。失败意味着什么：spec §10 风险 4 的对策就是**表头 + 记号本身**（没有新增状态区），且 `PROGRESSABLE_IDS`（`view/widgets/action_rail.py:122`）只有 `refresh`/`refresh_all` —— 由「打开文件夹」触发的那次 sweep **不转圈**：`ActionRail.set_progress` 对不可进度的 id 直接抛 `ValueError`（同文件 `:270`），想让它转就得先给 rail 加一个可进度的按钮位。若判定不可接受，需要给 sweep 加进度语义，那动的是批次 2 的图标栏契约，不是本批的显示层。

## 外观设置 / Appearance Settings

- 🌗 **主题三态 (Theme: auto / light / dark)**: 默认 `跟随系统`，读取系统的浅色/深色偏好并随其切换实时改变；也可在外观弹窗里手动锁定 `浅色` 或 `深色`。选择写入 `settings.json` 的 `theme` 键，重启后保持；无法识别的值回落到 `auto`。
  The default mode follows the OS colour scheme and reacts to a live scheme flip; the dialog's two overrides pin the app to light or dark. The choice persists in `settings.json` under `theme`.
- 🎨 **单一来源的语义 token (34 semantic tokens)**: 所有颜色、圆角、间距与字号集中在 `core/theme.py`，整张样式表由 `core/theme_qss.py` 按当前主题生成，`view/theme_manager.py` 是全应用唯一推送 palette 与 stylesheet 的地方。widget 内不再有局部样式表。
  Every colour, radius, spacing and font size comes from `core/theme.py`; the one application stylesheet is generated by `core/theme_qss.py`, and `ThemeManager` is the only code allowed to push a palette or a stylesheet.
- 🖼️ **自定义背景**: 设置背景图片，等比缩放适配窗口；蒙层颜色取自主题的 `scrim` token，暗色主题下不再是白蒙层
- ✨ **透明效果**: 播放列表、控制面板、背景蒙层三条透明度滑块，即时生效
- 🔤 **SVG 图标集**: 播放/暂停、上一曲、下一曲、停止、三种循环模式与四级音量共 12 个图形，手写于 `resource/icons/`（24×24 viewBox，`fill="currentColor"`），按主题 token 光栅化，因此深浅两套都能保持对比度达标；图标不再是文字字符，缺字体的平台不会再出现方框。
  Twelve hand-authored SVGs in `resource/icons/`, rasterised through a theme token instead of being drawn as polygons or typed as characters, so a glyph can never keep a light-mode colour in dark mode.
- 🧾 **播放状态区分**: 「正在播放」行用 `playing_bg` 底色 + `playing_text` 文字 + 左侧 3px `playing_bar` 色条，与仅选中行的中性 `selection_bg` 分属两族；进度条与音量条共用同一套滑块规则。
- 🎛️ **统一配置**: 通过图标栏的 `外观设置` 按钮打开配置弹窗（批次 2 起不再有 `文件` 菜单）
- 📸 **渲染矩阵 / Render matrix**: `python tests/tools/render_matrix.py --out DIR` 在离屏环境渲染 12 张对比图（`light|dark` × `空|有数据|三十库` × `820×520|1100×720`，其中三十库帧浮层面板展开），另有四类可选帧：`--sidebar-open`（面板展开，量出面板与图标栏的间隙并打印 `FLUSH ON THE RAIL`）、`--toast`（真实 toast 文案压在有数据的列表上）、`--interaction`（批次 3 的三个状态：`hover` / `multi-selected` / `context-menu-grab-composite`，**深浅两套各一张**）、`--metadata`（批次 4 的五个状态：`metadata-full` / `metadata-pending` / `metadata-unknown` / `metadata-folder` / `metadata-legacy-cache`，**深浅两套各一张，全部 1200×720 + 40 行**——必出滚动条，因为表头与行网格只在滚动时错位），以及 `--crops` 2x 局部放大，用于改动主题层或外壳后的目视核对。交互帧与元数据帧各自自带前置断言：光标没落上、邻行也带上了 hover 底色、选区不是点的那三行、菜单不是真 handler 建的那一份、滚动条其实没出现、表头词没逐边压在列上、磁盘上的文件其实不是 `version: "1.0"`——脚本直接停下，不会交出一张「看起来像」的图。**`context-menu-grab-composite` 这张图的名字就是它的性质**：`QMenu.exec()` 进的是嵌套事件循环，自动化路径不能进去，所以脚本替换掉 `PlaylistView._popup_menu` 这个缝、在缝**内**用 `menu.grab()` 取像素、再把这张 grab 合成到点击坐标上（裁切图同样叫 `…__menu-grab-composite.png`）。于是这一帧证明的是**路由与构建**：真实 `QContextMenuEvent` 走到了 `contextMenuEvent`、资源管理器目标规则跑了、菜单的 id／分隔线／带计数的文案确由 `build_playlist_menu` 做出；它**不证明交互**——生产 `_popup_menu` 的函数体（`return menu.exec(global_pos)`）在任何自动路径里都没执行过（本工具与所有菜单测试都替换了这个缝），所以弹窗是否真的模态打开、是否落在光标处、是否跟随指针、点击是否生效，只能真机看。合成图里也没有弹窗自身的原生边框、阴影与边界翻转。注意离屏 harness 的中文字形会退化为方框，文字正确性需在真实桌面（`--capture window`）运行确认；反过来，**行 hover 只有离屏跑得起来**——按 `cursor_lands()` 的判断，真实 QPA 下 `QTest.mouseMove` 与 `QCursor.setPos` 都不会让 `underMouse()` 变真，所以 `--capture window` 会为 hover 帧打印一条跳过说明而不是图片。**这条理由是假说而非实测**（该函数比的是 `platformName()`，本批次从未在真实 QPA 下跑过这个工具），核对方法见上一节第 13 条。
  `python tests/tools/render_matrix.py --out DIR` renders the 12-frame shell matrix (light|dark × empty|populated|thirty-libraries × 820x520|1100x720), plus opt-in `--sidebar-open` / `--toast` / `--interaction` / `--metadata` frames and 2x crops. The batch-4 `--metadata` set is five states x two themes at 1200x720 with forty rows -- a scrolling playlist, since the header band only matters once the vertical scrollbar has narrowed the rows -- and each frame asserts its own preconditions (the scrollbar is really visible, the four headings sit edge-for-edge on the delegate's bands at zero tolerance, the mark strings and their WCAG contrast are measured, and the legacy frame's file on disk really is `version: "1.0"`). Offscreen, the pending and unknown frames come out **byte-identical** -- the substituted font rasterises both code points to one box -- which is exactly why real-desktop item 14 exists; the folder frame keeps the row under its header unanswered so a blank cell and a mark are comparable one row apart. The interaction frames assert their own preconditions and stop the run rather than photographing a state that is not on screen. **The third frame's name is its disclaimer**: `context-menu-grab-composite` is a `QMenu.grab()` composited onto the window at the click point, not a photographed popup, because `QMenu.exec()` spins a nested event loop no automated path may enter -- the harness replaces the `PlaylistView._popup_menu` seam and paints the menu from inside it (its crop is `…__menu-grab-composite.png`). So that frame proves **routing and the builder** (a real `QContextMenuEvent` reached `contextMenuEvent`, the Explorer target rule ran, and the ids / separator / counted copy come from the real `build_playlist_menu`) and **not the interaction**: production's `_popup_menu` body (`return menu.exec(global_pos)`) never executes in any automated path -- this tool and every menu test patch that seam -- so whether the popup really opens modally at the cursor, tracks the pointer and acts on a click is a real-run judgement. Such a composite also lacks the popup's own native frame, shadow and edge-flip. Offscreen, CJK glyphs degrade to boxes, so copy still needs a real desktop run (`--capture window`) -- and row hover needs the offscreen run, because `cursor_lands()` assumes a real QPA will not let the harness move the pointer. That assumption is a hypothesis, not a measurement this batch took; checklist item 13 above is the one run that settles it.

## NCM 格式支持 / NCM Format Support

PyPlayer 支持播放网易云音乐加密格式（.ncm）文件。

### 工作原理
1. 播放 .ncm 文件时，自动调用 ncmdump 工具解包
2. 解包后的音频文件（MP3/FLAC）缓存在 `proxy/` 目录
3. 后续播放同一文件直接使用缓存，无需重复解包
4. 代理文件按曲库分类管理，30天未访问自动清理

### ncmdump 工具
- 位于 `bin/{platform}/{arch}/ncmdump`
- 支持 Windows (amd64) 和 Linux (amd64)
- 首次播放 NCM 文件时自动调用

### 代理文件目录结构
```
proxy/
├── {library_hash_1}/
│   ├── song1.mp3      # 来自 song1.ncm
│   └── song2.flac     # 来自 song2.ncm
└── {library_hash_2}/
    └── ...
```

## 依赖安装 / Dependencies

```powershell
# Windows (推荐使用 conda)
conda install -c anaconda numpy scipy
conda install -c conda-forge opencv-python soundfile

# 或使用 pip（推荐）
pip install pygame opencv-python mutagen Pillow soundfile sounddevice numpy scipy PyQt6
```

## 快速开始 / Quick Start

```bash
# 1. 安装依赖
cd PyPlayer
pip install -r requirements.txt

# 2. 启动 PyQt GUI 模式 (默认)
python main.py

# 3. 或指定其他模式
python main.py --qt        # PyQt GUI (默认)
python main.py --tui       # 终端界面
python main.py song.mp3    # CLI 直接播放
```

## 目录结构 / Project Structure

```
PyPlayer/
├── main.py                 # 主入口点
├── core/                   # 核心业务逻辑
│   ├── player.py           # 播放器核心
│   ├── library_manager.py  # 媒体库管理
│   ├── cache_manager.py    # JSON 缓存管理器
│   ├── config.py           # 配置管理
│   ├── i18n.py             # 国际化模块
│   ├── metadata.py         # 元数据提取
│   └── ncm_proxy.py        # NCM 代理管理器
├── view/
│   ├── main_window.py      # 主窗口
│   ├── dialogs/            # 对话框
│   │   ├── library_dialog.py    # 媒体库管理对话框
│   │   └── appearance_dialog.py # 外观设置对话框
│   └── widgets/
│       ├── action_rail.py         # 左侧图标栏（七个动作）
│       ├── library_sidebar.py     # 浮层媒体库列表
│       ├── now_playing_strip.py   # 底部封面+曲名/艺人条
│       ├── toast.py               # 限时反馈浮层
│       ├── playlist_view.py       # 播放列表视图
│       ├── bottom_panel.py        # 底部面板（进度条+控制按钮）
├── presenter/
│   └── main_presenter.py   # MVP 协调器
├── service/
│   ├── config_service.py   # 配置服务
│   ├── library_service.py  # 媒体库服务
│   ├── queue_service.py    # 队列服务
│   ├── playback_service.py # 播放服务
│   └── tools/              # 元数据提取工具
│       ├── base.py         # 基类定义
│       ├── mp3.py          # MP3 提取器
│       ├── flac.py         # FLAC 提取器
│       ├── m4a.py          # M4A 提取器
│       ├── ogg.py          # OGG 提取器
│       └── ncm.py          # NCM 提取器
├── bin/                    # 外部工具
│   ├── windows/amd64/      # Windows 工具
│   │   └── ncmdump.exe     # NCM 解包工具
│   └── linux/amd64/        # Linux 工具
│       └── ncmdump         # NCM 解包工具
├── tui/
│   └── tui.py              # 终端界面
├── tests/
│   └── test_player.py      # 单元测试
└── locales/
    ├── interface/          # 界面 i18n 资源
    └── dialogs/            # 对话框 i18n 资源
```

## License

MIT License

## 打包发布 / Building Distributable Package

### 环境准备 / Prerequisites

```powershell
# 安装打包工具
pip install pyinstaller

# 确保所有依赖已安装
pip install -r requirements.txt
pip install PyQt6 opencv-python
```

### 构建步骤 / Build Steps

```powershell
# 进入项目目录
cd PyPlayer

# 方式一：目录模式打包（推荐，启动快）
python .build/build_windows.py

# 方式二：单文件打包（体积小，启动慢）
python .build/build_windows.py --onefile

# 方式三：清理后重新打包
python .build/build_windows.py --clean
```

### 输出目录 / Output

打包完成后，输出文件位于 `.target/` 目录：

```
.target/
└── PyPlayer/
    ├── PyPlayer.exe    # 主执行文件
    ├── resource/       # 默认封面等资源
    ├── locales/        # 国际化文件
    └── ...             # 依赖库文件
```

### 分发 / Distribution

将整个 `.target/PyPlayer/` 文件夹打包分发即可。用户解压后双击 `PyPlayer.exe` 运行。

### 注意事项 / Notes

1. **目录模式 vs 单文件模式**
   - 目录模式：启动快，但需要分发整个文件夹
   - 单文件模式：分发方便，但启动时需要解压，首次运行较慢

2. **杀毒软件误报**
   - PyInstaller 打包的程序可能被杀毒软件误报
   - 可以考虑进行代码签名解决此问题

3. **资源文件路径**
   - 项目已内置 `core/resource_utils.py` 处理打包后的资源路径
   - 确保所有资源文件通过此模块访问

4. **Qt 插件**
   - spec 文件已配置自动收集 PyQt6 插件
   - 如遇显示问题，检查 platforms 插件是否正确打包

### 故障排除 / Troubleshooting

```powershell
# 如果打包失败，尝试以下步骤：

# 1. 清理缓存
python .build/build_windows.py --clean

# 2. 检查依赖完整性
pip install --upgrade pyinstaller
pip install --upgrade PyQt6

# 3. 使用调试模式打包（显示控制台窗口）
# 编辑 .build/pyplayer.spec，将 console=False 改为 console=True
```
