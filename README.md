# PyPlayer - Python Music/Video Player

一个基于 Python 的多媒体播放器，支持 MP3、WAV、MP4、AVI 等常见格式。提供命令行和图形界面两种使用方式。

## 特性

- 🎵 **音频播放**: MP3, WAV, FLAC, OGG, M4A, AAC
- 🎬 **视频播放**: AVI, MP4, MKV, MOV, WMV
- 💻 **GUI 模式**: 基于 Tkinter 的图形界面（跨平台）
- ⌨️ **TUI 模式**: curses 终端界面 (Unix/Linux/macOS)
- 📚 **媒体库管理**: 持久化配置支持，统一管理多个媒体目录
- 🔧 **配置文件**: `settings.xml` 自动保存媒体库清单
- 🌐 **国际化 (i18n)**: 支持中文 (zh_CN) 和英文 (en_US)，根据系统 locale 自动切换

## 媒体库管理功能

通过 `Library Management` 可以添加、删除和扫描媒体库：

### GUI 模式
1. 点击工具栏 **"Library Mgr"** 按钮打开管理对话框
2. **Add**: 选择文件夹添加到媒体库列表
3. **Delete**: 删除选中的媒体库（仅更新配置）
4. **Scan All**: 重新扫描所有媒体库并统计文件数量

### Scan Directory 功能增强
- 点击 **"Scan Directory"** 按钮会自动扫描 `settings.xml` 中配置的**所有媒体库文件夹**，而非当前工作目录
- 支持**层级化播放列表显示**：当媒体库包含子文件夹时，播放表会以树形结构展示
  - **文件夹**使用 `[D] FolderName` 标识（Directory）
  - **文件**使用 `[F] FileName` 标识（File）
  - 文件夹按相对路径缩进显示层级关系
- 例如：
  ```
  [D] Music
    [D] Artists
      [F] Song.mp3
      [F] Track.wav
    [D] Albums
      [F] AlbumTrack.flac

### TUI 模式 (按 `L` 键)
- **A** = Add Library - 添加媒体库（输入路径或粘贴）
- **D** = Delete Selected - 删除选中的媒体库
- **S** = Scan Libraries - 扫描所有媒体库并显示结果
- **Q** or **ESC** = Quit Menu - 退出菜单

配置文件 `settings.xml` 持久化存储媒体库清单，程序启动时自动加载。

## 依赖安装

```powershell
# Windows (推荐使用 conda)
conda install -c anaconda pygame
conda install -c conda-forge opencv-python

# 或使用 pip
pip install pygame opencv-python
```

> 注意：
> - `opencv-python` 用于视频播放（需要图形界面支持）
> - 纯音频模式下可以使用 `opencv-python-headless`

## 快速开始

### 1. 安装依赖

```bash
cd PyPlayer
pip install pygame opencv-python
```

### 2. 启动播放器

#### GUI 模式 (推荐)
```powershell
python gui.py
```

GUI 界面提供：
- 📋 **层级化播放列表管理** - 自动按文件夹结构显示媒体文件
- 🎮 播放控制按钮（播放/暂停/停止/上下曲）
- 🔊 音量调节
- 📂 文件浏览和打开

#### CLI 模式 (直接播放)
```powershell
# 播放单个文件
python player.py "path/to/song.mp3"

# 自动扫描当前目录并显示支持格式
python player.py
```

#### TUI 模式 (终端界面 - Unix/Linux/macOS)
```bash
python tui.py           # 启动终端 UI
python player.py --tui   # 或使用 --tui 参数
```

> 注意：TUI 模式需要 curses/ncurses 支持，在 Windows 上可能不可用。

## 文件结构

```
PyPlayer/
├── player.py              # 核心播放器模块 (音频 + 视频)
├── gui.py                 # Tkinter 图形界面
├── tui.py                 # curses 终端界面 (Unix only)
├── config.py              # 配置管理模块 (settings.xml 读写)
├── library_manager.py     # 媒体库扫描和管理模块
├── i18n.py                # 国际化核心模块
├── settings.xml           # 配置文件（首次运行时自动创建）
├── test/                  # 测试文件目录
│   └── Electric Guitar.wav
├── locales/               # 本地化资源文件
│   ├── interface/         # GUI/TUI 界面文本
│   │   ├── main.zh_CN.properties  # 中文界面文本
│   │   └── main.en_US.properties  # 英文界面文本
│   ├── console/           # 控制台日志输出文本
│   │   ├── output.zh_CN.properties  # 中文日志
│   │   └── output.en_US.properties  # 英文日志
│   └── dialogs/           # 弹窗对话框文本
│       ├── dialog.zh_CN.properties  # 中文对话框
│       └── dialog.en_US.properties  # 英文对话框
├── requirements.txt
└── README.md              # 本文档
```

## 国际化 (Internationalization)

PyPlayer 支持多语言界面，使用基于 `.properties` 文件化的 i18n 系统：

### 语言检测

程序启动时自动检测系统 locale：
- 优先中文 (`zh_CN`) - 如果系统语言包含 "zh" 或环境变量 `LANG/LC_ALL` 设置
- 英文 (`en_US`) - 默认备用语言

可通过环境变量强制指定语言：
```bash
export LANG=zh_CN.UTF-8    # 使用中文
export LC_ALL=en_US.UTF-8  # 使用英文
```

### 支持的界面文本

| Category | File | Description |
|----------|------|-------------|
| `interface/main` | `locales/interface/main.zh_CN.properties` | GUI/TUI 主界面文本（标题、按钮标签、状态消息） |
| `console/output` | `locales/console/output.zh_CN.properties` | player.py 控制台输出日志 |
| `dialogs/dialog` | `locales/dialogs/dialog.zh_CN.properties` | messagebox/Tkinter 弹窗对话框 |

### 使用方式

```python
import i18n

# 获取界面文本（自动替换 {{param}} 占位符）
title = i18n.get('window.title')                          # "PyPlayer v1.0"
status = i18n.get('status.now_playing', title='Song')    # "Now playing: Song"

# 控制台输出
print(i18n.console('console.supported_formats_audio', formats=', '.join(formats)))

# 对话框消息
messagebox.showinfo(
    i18n.dialog('dialog.title.success'),
    i18n.dialog('dialog.msg_added_library', name='MyMusic', path='/path/to/music')
)

# 手动设置语言（用于测试）
i18n.set_locale('zh_CN')   # 切换到中文
i18n.set_locale('en_US')   # 切换到英文
```

### 添加新翻译

在对应语言的 `.properties` 文件中添加条目：

**中文 (`zh_CN.properties`)**:
```properties
new.feature.text=新功能描述文本
button.save.button=保存
```

**英文 (`en_US.properties`)**:
```properties
new.feature.text=New feature description
button.save.button=Save
```

## 支持的媒体格式

## 支持的媒体格式

| 类型 | 扩展名 |
|------|--------|
| **音频** | .mp3, .wav, .flac, .ogg, .m4a, .aac |
| **视频** | .avi, .mp4, .mkv, .mov, .wmv |

## GUI 使用说明

1. **添加文件**:
   - 点击 "Open File(s)" 按钮选择文件
   - 或双击播放列表中的文件开始播放

2. **控制播放**:
   - ⏯️ **Play/Pause**: 暂停/继续播放
   - ⏹️ **Stop**: 停止播放
   - ◀ Prev / Next ▶: 上一首/下一首

3. **键盘快捷键**:
   | 按键 | 功能 |
   |------|------|
   | `空格` | 播放/暂停 |
   | `N` | 下一首 |
   | `M` | 上一首 |
   | `S` | 停止 |
   | `O` | 打开文件 |

4. **音量调节**:
   - 拖动右侧的 Volume 滑块

5. **媒体库管理**:
   - 点击 **"Library Mgr"** 按钮打开管理对话框
   - 添加常用文件夹作为媒体库，方便快速扫描
   - 配置持久化存储，重启后自动加载

## TUI 键盘快捷键 (终端模式)

| 按键 | 功能 |
|------|------|
| `SPACE` | 播放/暂停 |
| `N` / `M` | 下一首 / 上一首 |
| `S` | 停止播放 |
| `O` | 打开文件（输入路径） |
| `L` | **媒体库管理菜单** |
| `H` | 显示帮助信息 |
| `Q` | 退出播放器

## 测试播放器

项目包含一个测试 WAV 文件：

```bash
# GUI 模式
python gui.py

# CLI 模式
python player.py "test/Electric Guitar.wav"
```

## 故障排除

### NameError 或崩溃问题
- **最新修复**: 已优化 `_get_track_from_display_idx()` 方法，将层级结构重建移出循环，解决双击播放列表时的性能问题和潜在路径匹配错误
- 如遇其他异常，检查 Python 版本是否为 3.6+

### 视频无法播放
- 确保安装了完整版 `opencv-python` (非 headless)
- Windows 用户可能需要安装 Visual C++ Redistributable

### GUI 无法启动
- 确保显示环境可用（服务器需要 X11 forwarding）
- 可以使用 CLI 模式或 TUI 模式替代

### TUI 不可用 (Windows)
- Windows 默认不支持 curses，建议使用 GUI 模式 (`python gui.py`)
- 可在 WSL/Cygwin 等环境中使用 TUI 模式

### 媒体库扫描无结果
- 确保添加的路径包含支持的媒体文件 (.mp3, .wav, .flac, .ogg, .m4a, .aac, .avi, .mp4, .mkv, .mov)
- 检查 `settings.xml` 是否正确保存了配置

### 音频无声
- 检查系统音量设置
- 确认音频文件格式支持 (尝试 WAV/MP3)

## License

MIT License
