# PyPlayer - Python Music/Video Player

一个基于 Python 的多媒体播放器，支持 MP3、WAV、MP4、AVI 等常见格式。提供命令行和图形界面两种使用方式。

## 特性

- 🎵 **音频播放**: MP3, WAV, FLAC, OGG, M4A, AAC
- 🎬 **视频播放**: AVI, MP4, MKV, MOV, WMV
- 💻 **GUI 模式**: 基于 Tkinter 的图形界面（跨平台）
- ⌨️ **CLI 模式**: 直接通过命令行参数播放文件

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
- 📋 播放列表管理
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
├── player.py      # 核心播放器模块 (音频 + 视频)
├── gui.py         # Tkinter 图形界面
├── tui.py         # curses 终端界面 (Unix only)
├── test/          # 测试文件目录
│   └── Electric Guitar.wav
├── requirements.txt
└── README.md      # 本文档
```

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

## 测试播放器

项目包含一个测试 WAV 文件：

```bash
# GUI 模式
python gui.py

# CLI 模式
python player.py "test/Electric Guitar.wav"
```

## 故障排除

### 视频无法播放
- 确保安装了完整版 `opencv-python` (非 headless)
- Windows 用户可能需要安装 Visual C++ Redistributable

### GUI 无法启动
- 确保显示环境可用（服务器需要 X11 forwarding）
- 可以使用 CLI 模式或 TUI 模式替代

### 音频无声
- 检查系统音量设置
- 确认音频文件格式支持 (尝试 WAV/MP3)

## License

MIT License
