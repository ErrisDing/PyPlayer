# PyPlayer UI 批次 1：设计 token 与主题层

日期：2026-10-16
状态：待评审
范围：批次 1（主题层 + 语义修正 + 死代码清理）。批次 2（布局）、批次 3（交互）各自另开 spec。

## 1. 目标

让「颜色、字号、间距、圆角、图标」只有一个来源，并让暗色模式成为一等公民。

可核对的成功判据：

1. 全仓 `setStyleSheet` 从 32 处降到 1 处（只剩 `view/theme_manager.py` 发应用级样式）；不再有硬编码主题 `QColor`。分布：`bottom_panel` 7、`appearance_dialog` 7、`now_playing_panel` 6、`control_panel` 6（僵尸文件）、`progress_slider` 2（僵尸文件）、`playlist_view` 2、`library_selector` 1、`main.py` 1。
2. `python main.py` 在 Windows 与 macOS 上都能启动（当前不能，见 §3.1）。
3. 系统为暗色时应用为暗色；`auto|light|dark` 三态可覆盖并持久化；切换无需重启。
4. 所有正文文字对其背景满足 WCAG AA（4.5:1），由测试强制。
5. 「正在播放」与「选中」在视觉上可区分（当前 `#c8e6ff` 与 `#e3f2fd` 近乎同色）。

不在本批次解决：布局与信息架构（B1–B5）、交互（C1–C6）、字体族选择、跟随 OS 字体缩放、TUI。

## 2. 现状约束（已实测）

- 验证环境：`D:\PROGRAMMES\miniconda3\envs\dev_313`（Qt 6.11 / PyQt 6.11）。仓库内 `.venv` **没有 PyQt6**，不能用于 GUI 验证。
- `QStyleHints.colorScheme()` 与 `colorSchemeChanged` 在 Qt 6.11 可用；`QT_QPA_PLATFORM=offscreen` 下 `colorScheme()` 返回 `ColorScheme.Unknown`。
- `PyQt6.QtSvg` 可导入，`QPixmap.loadFromData(svg, 'SVG')` 成功 → SVG 图标方案成立。
- 测试是 `unittest` 风格，`python -m unittest discover -s tests` 可跑；环境无 pytest，本批次不引入。
- 基线：10 个用例，1 个已失败（`tests/test_player.py::TestHierarchicalPlaylist::test_multiple_libraries_display`，期待 `[ML]` 标记，该标记已被 a5da9a8 的相对路径展示取代）。本批次不修，验收标准是「不新增失败」。
- 打包：`.build/pyplayer.spec:21-23` 整体收录 `resource/`（新增 `resource/icons/` 自动生效）；`:31-33` 单独收录 `view/resources`（styles.qss），删文件时必须一并清理。

## 3. 批次 0（前置，单独提交）

`view/main_window.py:81` 使用 `QApplication` 但该模块未导入它，`MainWindow()` 构造即抛 `NameError` —— 应用当前无法启动，来自 43bbfd8。

修法：把 `QApplication` 加入 `view/main_window.py:8` 的 `PyQt6.QtWidgets` 导入列表。单独一个提交，不与批次 1 的样式改动混合。

## 4. 设计

### 4.1 `core/theme.py`：token 定义（纯 Python，不 import Qt）

`@dataclass(frozen=True) class ThemeTokens`，字段按语义命名：

| 组 | 字段 |
|---|---|
| 表面 | `window_bg` `surface` `surface_alt` `surface_header` `scrim` |
| 文字 | `text_primary` `text_secondary` `text_muted` `text_on_accent` |
| 强调 | `accent` `accent_hover` `accent_pressed` `accent_soft` |
| 列表状态 | `selection_bg` `playing_bg` `playing_text` `playing_bar` `hover_bg` |
| 线 | `border` `border_strong` `divider` |
| 控件 | `button_bg` `button_hover` `button_pressed` `button_disabled_bg` `button_disabled_text` `icon` `icon_muted` `icon_on_accent` `focus_ring` |
| 浮层 | `tooltip_bg` `tooltip_text` `scrollbar_thumb` `scrollbar_thumb_hover` |

颜色一律 `#rrggbb` 字符串（不用 `QColor`），使本模块可无 Qt 单测。

`LIGHT`：

```
window_bg #fafafa   surface #ffffff   surface_alt #f5f5f5   surface_header #f0f2f5   scrim #ffffff
text_primary #1f1f1f  text_secondary #5a5a5a  text_muted #6a6a6a  text_on_accent #ffffff
accent #1976d2  accent_hover #1565c0  accent_pressed #0d47a1  accent_soft #e3f2fd
selection_bg #eceff1  playing_bg #e3f2fd  playing_text #0d47a1  playing_bar #1976d2  hover_bg #f0f0f0
border #d5d5d5  border_strong #bdbdbd  divider #eeeeee
button_bg #ffffff  button_hover #f0f0f0  button_pressed #e0e0e0
button_disabled_bg #f7f7f7  button_disabled_text #a8a8a8
icon #444444  icon_muted #6e6e6e  icon_on_accent #ffffff  focus_ring #1976d2
tooltip_bg #323232  tooltip_text #ffffff  scrollbar_thumb #c0c0c0  scrollbar_thumb_hover #9e9e9e
```

`DARK`：

```
window_bg #1e1e1e   surface #252526   surface_alt #2d2d30   surface_header #2f3338   scrim #121212
text_primary #e4e4e4  text_secondary #b0b0b0  text_muted #a3a3a3  text_on_accent #0b1c2c
accent #64b5f6  accent_hover #90caf9  accent_pressed #42a5f5  accent_soft #1f3a52
selection_bg #2f343a  playing_bg #1f3a52  playing_text #90caf9  playing_bar #64b5f6  hover_bg #2a2d2e
border #3f3f46  border_strong #555555  divider #333333
button_bg #2d2d30  button_hover #3e3e42  button_pressed #4a4a4e
button_disabled_bg #2a2a2c  button_disabled_text #6a6a6a
icon #d0d0d0  icon_muted #9a9a9a  icon_on_accent #0b1c2c  focus_ring #64b5f6
tooltip_bg #3b3b3b  tooltip_text #e4e4e4  scrollbar_thumb #4a4a4a  scrollbar_thumb_hover #6a6a6a
```

四处刻意的取值决策（非纯配色平移；最后一处是「不改」）：

- `accent` 从 `#2196F3` 改 `#1976d2`：白字压在 `#2196F3` 上只有 2.6:1，不达标；`#1976d2` 为 4.6:1。
- `text_muted` 从 `#6e6e6e`（LIGHT）/ `#9a9a9a`（DARK）抬到 `#6a6a6a` / `#a3a3a3`：原值对 `selection_bg`、`playing_bg` 只有 4.42 / 4.46（LIGHT）与 4.46 / 4.18（DARK），低于 §6 断言的 4.5:1；新值在四个文字背景上的最低对比度为 4.68（LIGHT）/ 4.66（DARK）。阈值不放宽，改的是色值。
- **`icon_muted` 不跟着 `text_muted` 一起动**，保持 `#6e6e6e` / `#9a9a9a`：它是非文字 UI 组件（loop 关闭态图形），适用 WCAG 1.4.11 的 3:1 而不是 1.4.3 的 4.5:1（见 §4.6 D1），实测在其四个渲染背景（`button_bg`、`button_hover`、`button_pressed`、`surface`）上的最低对比度为 3.86（LIGHT，`button_pressed`）/ 3.14（DARK，`button_pressed`），已达标，并由 `ThemeContrastTest` 以 3.0 阈值守。后来者请勿把它镜像成 `text_muted` 的新值。
- 选中与播放中改用不同族：选中 = 中性 `selection_bg`，播放中 = `playing_bg` + `playing_text` + 左侧 3px `playing_bar`（由 delegate 绘制）。

共享的几何与排印 token（与主题无关，模块级常量）：

```
radius_sm 4  radius_md 6  radius_pill 999
space_1 4  space_2 8  space_3 12  space_4 16
row_height 28  transport_size 40  play_size 50  art_size 200
font_size_sm 12  font_size_md 13  font_size_lg 15  font_size_xl 18
```

字号用 px。已知代价：QSS 里的 px 是绝对值，不跟随 OS 字体缩放；只有未被 QSS 覆盖的控件继承 `app.font()` 的 pointSize。本批次接受这个限制。

几何 token 的消费点写死，避免变成无人使用的装饰：`art_size` 取代 `NowPlayingPanel.ART_SIZE`（`now_playing_panel.py:50`）；`transport_size` / `play_size` 取代 `bottom_panel.py:308`、`:317`、`:338`、`:346`、`:357` 的 `setFixedSize` 字面量；`row_height` 由 `PlaylistItemDelegate.sizeHint()` 使用（新增，当前列表行高只由 QSS padding 隐式决定）。

`resolve(mode: str, system_scheme: str) -> ThemeTokens`：`mode` 为 `light|dark|auto`，`system_scheme` 为 `Dark|Light|Unknown`。`auto` + `Unknown` → `LIGHT`（离屏与旧 Qt 的确定性回退）。纯函数，便于穷举测试。

### 4.2 `build_qss(tokens, alphas) -> str`：唯一样式表来源

取代 `view/resources/styles.qss`（删除该文件）。`alphas` 是 `AlphaSettings(overlay, playlist, controls)`，用于把 `surface` 合成为 `rgba(...)`，保持现有三个透明度设置的用户可见语义。

作用域规则（这是 A1 的根因修复）：

- 单例控件用 `objectName`：`#nowPlayingPanel` `#albumArt` `#trackTitle` `#trackArtist` `#trackAlbum` `#playlistHeader` `#playlistView` `#bottomPanel` `#progressSlider` `#volumeSlider` `#playButton` `#loopButton` `#timeLabel` `#appearanceDialog`
- 重复元素用动态属性选择器：`QPushButton[chip="true"]`（媒体库按钮）、`QPushButton[role="transport"]`（上下曲/停止）
- 删除现在的全局裸 `QPushButton` / `QSlider` 规则。当前正是「全局规则 + widget 内联表」的叠加导致进度条蓝滑块与音量条灰滑块并存。

各 widget 删除自身 `setStyleSheet`：`bottom_panel.py:267`、`:318`、`:360`、`:433-440`、`:444`；`playlist_view.py:52`、`:99`；`library_selector.py:82`；`now_playing_panel.py:78`、`:91`、`:108-124`、`:219`；`appearance_dialog.py:78`、`:171`、`:174`、`:203`、`:210`、`:251`、`:254`。

其中 `appearance_dialog` 那 7 处全是为「背景路径有值/无值」切换字色与斜体，改为动态属性：`set_background_image` 只 `setProperty('empty', not path)` + `unpolish/polish`，样式规则写成 `QLabel#bgPathLabel[empty="true"] { color: <text_muted>; font-style: italic; }`。

### 4.3 `view/theme_manager.py`：持有 QApplication 的那一侧

```
class ThemeManager(QObject):
    theme_changed = pyqtSignal(object)   # ThemeTokens
    def __init__(self, config_service)
    def apply_to(self, app) -> None      # setPalette + setStyleSheet
    def set_mode(self, mode) / set_alpha(which, value)
    @property tokens -> ThemeTokens
```

- `apply_to` 同时设 palette 与 stylesheet：Fusion 的若干子控件（菜单箭头、滚动条槽、对话框底色）只认 palette，只发 QSS 会残留浅色。palette 由 token 映射到 `QPalette.ColorRole` 的 `Window/Base/Text/Button/ButtonText/Highlight/HighlightedText/ToolTipBase/ToolTipText/PlaceholderText`。
- `MainWindow` 在 `theme_changed` 上调用 `bottom_panel.recolor(tokens)`、`now_playing.recolor(tokens)`，并重绘背景 scrim（`main_window.py:365` 的写死 `QColor(255,255,255,alpha)` 改为 `tokens.scrim` + `overlay_alpha`）。
- `PlaylistItemDelegate` 与 `PlaylistModel` 持 manager 引用，绘制时取 `tokens.playing_bg / playing_bar / selection_bg / text_muted`，不再取类级颜色常量（删除 `playlist_model.py:54-55`、`playlist_delegate.py:30` 的常量）。

### 4.4 主题模式：跟随系统 + 手动覆盖

- `core/config.py` 的 `Settings` 增 `theme: str = "auto"`；`_load` 用 `data.get('theme','auto')`，`_save` 写入。**不 bump `CONFIG_VERSION`**：读取侧全部是 `data.get(key, default)`，缺键自然落默认值，bump 只会多打一行无意义警告。
- `service/config_service.py` 增 `get_theme()` / `set_theme(mode)` 与 `theme_changed = pyqtSignal(str)`，与既有 `appearance_changed` 并列（`set_*_alpha` 保持发 `appearance_changed`）。
- 探测：`app.styleHints().colorScheme().name`。`hasattr` 探测 `colorSchemeChanged`：存在则实时跟随；不存在则退化为「启动时求值 + `applicationStateChanged` 转 Active 时求值」，不假装全平台实时。
- 启动路径：`main.py` 不再读 qss 文件（删 `:62-81`），改为 `ThemeManager(config_service).apply_to(app)`；删掉 `:40-60` 的 darwin-only palette 与 `:71-77` 的 macOS QSS 追加（这两段是 A2 半深半浅的直接来源，统一由 token 层承担）。
- 外观弹窗增「主题」分组：`auto/light/dark` 三个 `QRadioButton`，选中即 `set_theme` → 立即生效（无「确定」应用步骤，与现有三个滑块的即时语义一致）。

### 4.5 SVG 图标集

新增 `resource/icons/`，本批次 12 个：`play` `pause` `prev` `next` `stop` `loop_off` `loop_all` `loop_one` `volume_mute` `volume_low` `volume_mid` `volume_high`。统一 24×24 viewBox、单/少路径、`fill="currentColor"`，由本次实现手写，不引入外部图标库。

`view/icons.py`：

```
def icon(name, color_hex, size, dpr) -> QIcon   # 缓存键 (name, color, size, dpr)
```

流程：读 SVG 文本 → 把 `currentColor` 替换为 token 色 → `QSvgRenderer` 渲染到 `size*dpr` 的 `QPixmap` 并 `setDevicePixelRatio(dpr)` → 组 `QIcon`。取代 `bottom_panel.py:52-182` 的手绘多边形与 `create_colored_icon`（无人调用），并消灭 `↺`、`♪♪♪` 字符图标。

已知限制：`dpr` 在构造时取，跨不同缩放显示器移动窗口不会自动重生成图标。本批次接受，批次 3 再评估。

### 4.6 语义与可读性修正

- A6 硬编码文案改用已存在的 key：`metadata.no_track`（"No Track Playing"）、`metadata.unknown_artist`、`metadata.unknown_album`、`button.play_pause`、`button.prev_track`、`button.next_track`；新增 `metadata.unknown_title`、`playlist.header`（表头 "Playlist"）、`loop.mode_off/one/all`、`library.tooltip`。中英文两份 properties 同步补。
- A7：`NowPlayingPanel` 初始态与 `clear()` 态统一为默认封面，删除 `"No Art"` 字面量与那段重复的 placeholder 样式。
- D1：两个 WCAG 类别，两条阈值，不可合并：
  - 文字类（`text_muted`、相对路径文字色）按 1.4.3 正文对比度 ≥4.5:1，对其实际背景（`surface`、`surface_alt`、`selection_bg`、`playing_bg`）断言。
  - 非文字 UI 组件类（`icon_muted`，即 loop 关闭态图形）按 1.4.11 非文字对比度 ≥3:1，对其实际渲染背景（`button_bg`、`button_hover`、`button_pressed`、`surface`）断言。
  两者都由 `tests/test_theme.py::ThemeContrastTest` 守。因此每套主题里「弱文字」与「弱图标」是两种灰：`text_muted` 是对比度更高的那一侧（要过 4.5:1），`icon_muted` 停在 3:1 类所要求的水平，这个差值是类别不同导致的结果，不是笔误（见 §4.1 变更说明）。
- D2：为 `#playlistView`、`[role="transport"]`、`#playButton`、`#loopButton`、`[chip="true"]` 加 `:focus` 环（`focus_ring`，2px）。
- D3：播放/停止/下一曲补 tooltip（用上述 key），删除 `bottom_panel.py:311` 的 `hasattr(i18n,'get')` 无意义防御。

### 4.7 死代码清理

- 删 `view/widgets/control_panel.py`、`view/widgets/progress_slider.py`（461 行，`main_window` 用的是 `BottomPanel`），并从 `view/widgets/__init__.py` 移除导出。
- 删 `main_window.py:272-287` 的 `_on_set_background` / `_on_clear_background`（未挂任何菜单，背景设置走外观弹窗）。
- 死信号，三条各自不同：
  - `MainWindow.remove_library_requested`（`main_window.py:48`）：无 emit、无 connect，直接删。
  - `MainWindow.add_library_requested`（`main_window.py:47`）：有 connect（`main_presenter.py:94`）与 emit（`main_window.py:247`），但 emit 所在的 `_on_add_library` 自身未挂任何菜单动作（`_setup_menu` 用的是 `manage_libraries_requested`），整条链不可达 → 信号、`_on_add_library`、presenter 的连接与 `_on_add_library` 处理函数一并删。
  - `PlaylistView.track_selected`（`playlist_view.py:34`）：`:95` 有 emit，但全仓无 connect → 删信号与 `_on_click`，`clicked` 不再需要。
  - `playlist_view.py:35` 的 `context_menu_requested` 保留并加注释指向批次 3，因为它就是右键菜单的接口。
- `DisplayEntry` 两份定义（`service/queue_service.py:30`、`view/models/playlist_model.py:23`）：view 侧改为 `from service.queue_service import DisplayEntry`，只保留一份。
- `.build/pyplayer.spec:31-33` 移除 `view/resources` 收录块。

## 5. 数据流

启动：`main.py` → `ConfigService` → `ThemeManager(config)` → `resolve(theme, system_scheme)` → `build_qss` → `app.setPalette/setStyleSheet` → `MainWindow` 构造 → presenter 把三个 alpha 与当前 mode 灌入 manager。

切换（用户改主题）：弹窗 radio → `ConfigService.set_theme` → `theme_changed` → `ThemeManager.apply_to` → 全量重发 palette + QSS → `theme_changed(tokens)` → `MainWindow.recolor()` → 按钮图标重生成、delegate 用新色重绘、`update()` 重画 scrim。

透明度：滑块 → `set_*_alpha` → `appearance_changed` → manager 用新 alpha 重新 `build_qss` → `app.setStyleSheet`。widget 侧不再有局部重建逻辑。

## 6. 测试

> 本节在 Task 10 订正：原文低估了 `tests/test_theme.py` 与 `tests/test_theme_qss.py` 实际断言的内容，并把后者的 `build_qss` 断言误记在前者名下。以下按测试文件的现状重写。

新增 `tests/test_theme.py`（纯函数，无 Qt）：

- `ThemeTokensTest.test_token_field_names_match_spec_4_1`：34 个 token 名按 §4.1 的字段分组顺序逐一钉死。期望值是**从 spec 手抄的字面量**，不从 `ThemeTokens` 派生，因此改名、换序、增删任一项都会失败。
- `ThemeTokensTest.test_light_and_dark_define_identical_fields`：两套主题的字段集合完全一致（防漏定义），且每个字段都是小写 `#rrggbb` 字符串。
- `ThemeTokensTest.test_resolve_truth_table`：`auto|light|dark` × `Dark|Light|Unknown` 共 9 种输入，`auto+Unknown → LIGHT`；断言的是 `LIGHT`/`DARK` 单例的**同一性**（`is`），不是相等。
- `ThemeTokensTest.test_resolve_rejects_unknown_mode`：`neon`、`''`、`AUTO`、`Light`、`system` 一律 `ValueError`（大小写敏感是刻意设计）。
- `ThemeContrastTest.test_contrast_requirements`：测试内实现 WCAG 2.1 相对亮度与对比度，对两套主题逐对断言，阈值不放宽、不达标就改色值。断言的对远多于原文所列：
  - 文字类（4.5:1）：`text_primary`、`text_secondary`、`text_muted` 各自对 `surface`、`surface_alt`、`selection_bg`、`playing_bg` 共 12 对；另有 `text_on_accent`/`accent`、`playing_text`/`playing_bg`、`tooltip_text`/`tooltip_bg`。
  - 非文字组件类（3:1，WCAG 1.4.11）：`icon`/`surface`、`icon_on_accent`/`accent`；`icon_muted` 对其四个真实渲染背景（`button_bg`、`button_hover`、`button_pressed`、`surface`）；Task 8 之后 `icon` 与 `accent` 各自对 transport/loop 按钮的三个背景也进入断言表。
  - 结论是每套主题里 `text_muted` 与 `icon_muted` 是两种灰（4.5 类与 3 类的必然结果，见 §4.1、§4.6 D1）。

新增 `tests/test_theme_qss.py`（纯函数，无 Qt）：

- `SelectedChipContrastTest`：`QPushButton[chip="true"][selected="true"]` 必须是「描边态」——`background-color` 取 `surface`、`color` 与 `border-color` 取 `accent`（逐条比对生成表里该规则块的实际声明），且该前景/背景组合在两套主题下都过 4.5:1。这条守的是 §4.2 映射表被裁定改掉的那一格（表里的 `accent` on `accent_soft` 在 LIGHT 只有 4.03:1）。
- `BuildQssTest`：对 `LIGHT|DARK` × 三组 alpha 共 6 份输出断言——无未替换的 `{placeholder}`、花括号配对；`QPushButton`/`QSlider`/`QListView`/`QLabel` 每条规则都带作用域（两道闸：行锚定的裸类正则，覆盖 `:disabled`、`:hover` 与逗号列表成员；以及逐 compound 的选择器解析，它连 `*` 和任何未登记裸类一起拒）；`EXEMPT_CHROME_CLASSES` 七项（`QMenuBar` `QMenu` `QScrollBar` `QToolTip` `QSplitter` `QGroupBox` `QMainWindow`）是**封闭清单**，多一个少一个都失败；对话框家族（`QDialog QPushButton`、`QDialog QListWidget` 及其 `::item` 状态）必须是祖先限定而非裸类；`REQUIRED_OBJECT_NAMES` 与 `REQUIRED_DYN_PROPERTIES` 每一项都出现在输出里；alpha 生效且越界被夹到 0..1；`hex_to_rgba` 的格式（含尾零裁剪）。
- `PaletteOnlyColoursTest`：输出里每个 `#rrggbb` 必须等于某个 token 值、每个 `rgba(...)` 必须是「某 token + 某 alpha」，命名色只允许 `transparent` 与 `none`；并有一条元测试确认这套颜色扫描本身有牙。

新增 `tests/test_icons.py`：12 个 SVG 均存在、可 XML 解析、含 `viewBox="0 0 24 24"` 与 `currentColor`、无外部引用；`icon()` 在 dpr 1 与 2 下返回非空且真的填满了 `size*dpr` 那张图（HiDPI 断言量像素，不接受「调用过就行」）；缓存键含颜色、`clear_cache` 有效、资源缺失/坏 SVG 降级为 `QIcon()` 且只打一行警告；几何组用 2 px/unit 光栅化后的墨迹掩膜断言光学盒、transport 五连的高度节奏、prev/next 镜像一致、音量四级只增弧不移喇叭、loop 三态共用同一枚环、以及（Task 10 补）loop 图形不得跳出 transport 那一档尺寸级别。

新增 `tests/test_view_smoke.py`：offscreen 下构造 `MainWindow`，断言不抛异常且 `grab()` 非空非零。**这条就是本批次 0 那个启动崩溃的回归网**——它当时能直接拦住。无 PyQt6 时 `unittest.skipUnless` 跳过。

Task 10 另补 `tests/tools/render_matrix.py`：把上述断言看不见的部分交给眼睛。`--out DIR`，offscreen，真 `MainWindow` 灌假数据，产出 `light|dark` × `空|有数据` × `820×520|1100×720` 共 8 张 PNG，退出码 0。注意离屏 harness 的中文字形会退化为方框，文字正确性须在真实 Windows 运行确认；离屏也不驱动 `:hover`，弹窗与 chip 的悬停态需要真实指针。

## 7. 提交拆分

1. `fix(view): 补 QApplication 导入，修复启动崩溃`（§3）
2. `feat(theme): token 层与 QSS 生成`（§4.1–4.2，含删 styles.qss 与 spec 清理）
3. `feat(theme): 跟随系统 + 手动覆盖`（§4.4，含 config/service/presenter/弹窗）
4. `feat(icons): SVG 图标集与着色管线`（§4.5）
5. `refactor(view): 移除内联样式与僵尸 widget`（§4.2 收尾 + §4.7）
6. `fix(ui): 文案 i18n、状态色区分与对比度`（§4.6）
7. `test: 主题、图标与视图冒烟测试`（§6）

每个提交独立可跑；提交 5 之后 widget 内联样式应为零。

## 8. 风险

| 风险 | 处置 |
|---|---|
| Fusion 子控件只认 palette，漏设会残留浅色 | `apply_to` 同时发 palette + QSS；验证矩阵里专看菜单/滚动条/对话框 |
| 删 5 个文件的内联样式面广，易视觉回归 | 提交 5 单独成一次，配前后渲染图对比 |
| `colorScheme()` 在部分环境返回 `Unknown` | `resolve` 明确回退 `LIGHT` 并单测覆盖 |
| QSS px 字号不跟随 OS 缩放 | 记为已知限制，本批次不解决 |
| 无 pytest、`.venv` 缺 PyQt6 | 测试保持 `unittest`；GUI 验证固定用 `dev_313` |
| 已有 1 个失败用例 | 基线记为「10 跑 1 失败」，本批次标准是不新增失败 |
