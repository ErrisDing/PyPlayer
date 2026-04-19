# PyPlayer - Python Music/Video Player

一个基于 Python 的多媒体播放器，支持 MP3、WAV、MP4、AVI 等常见格式。提供命令行和图形界面两种使用方式。

## 特性 / Features

- 🎵 **音频播放**: MP3, WAV, FLAC, OGG, M4A, AAC, AIFF, AU (所有格式支持seek)
- 🎬 **视频播放**: AVI, MP4, MKV, MOV, WMV
- 💻 **GUI 模式**: 基于 PyQt6 的现代图形界面（跨平台）
- ⌨️ **TUI 模式**: curses 终端界面 (Unix/Linux/macOS)
- 📚 **媒体库管理**: 持久化配置支持，统一管理多个媒体目录
- 🔄 **媒体库切换**: 快速在多个媒体库之间切换，无需重新扫描
- 🔄 **智能刷新**: 手动刷新单个或全部媒体库，JSON缓存加速扫描
- 🔧 **配置文件**: `settings.json` 自动保存媒体库清单（支持从 XML 自动迁移）
- 🌐 **国际化 (i18n)**: 支持中文 (zh_CN) 和英文 (en_US)，根据系统 locale 自动切换
- 🎯 **队列节点架构**: 文件夹作为独立播放单元，支持文件夹内顺序播放和跨文件夹队列播放
- 🔄 **自动播放**: 曲目播放完毕自动跳转下一首
- 🎨 **Now Playing 面板**: 显示专辑封面、歌曲标题、艺术家和专辑信息
- ⏱️ **进度条与计时器**: 实时显示播放进度，支持拖拽跳转（所有音频格式）
- 📝 **元数据提取**: 自动读取 ID3、FLAC、M4A、OGG 标签信息
- 🚀 **Python 3.13 兼容**: 使用 soundfile + sounddevice 后端，无 audioop 依赖

## 媒体库功能 / Media Library Features

### JSON 缓存系统
- 扫描结果自动缓存至 `~/.pyplayer/cache/libraries/`
- 基于目录修改时间自动检测缓存是否过期
- 结构化 JSON 格式存储，包含文件元数据

### 媒体库刷新
- **刷新媒体库**: 重新扫描当前媒体库
- **刷新全部**: 重新扫描所有已配置的媒体库

### 媒体库切换
- 在 Now Playing 面板下方显示媒体库按钮组
- 点击按钮快速切换到对应的媒体库
- 当前选中的媒体库高亮显示

### 播放列表优化
- 自动隐藏媒体库根节点，仅显示文件夹和文件
- 更清晰的层级结构展示

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
python main.py --tkinter   # Tkinter GUI (传统)
python main.py --tui       # 终端界面
python main.py song.mp3    # CLI 直接播放
```

## 目录结构 / Project Structure

```
PyPlayer/
├── main.py                 # 主入口点
├── player.py               # 播放器核心
├── library_manager.py      # 媒体库管理
├── cache_manager.py        # JSON 缓存管理器
├── config.py               # 配置管理
├── i18n/                   # 国际化模块
├── view/
│   ├── main_window.py      # 主窗口
│   └── widgets/
│       ├── now_playing_panel.py   # 正在播放面板
│       ├── library_selector.py    # 媒体库切换器
│       ├── playlist_view.py       # 播放列表视图
│       └── control_panel.py       # 控制面板
├── presenter/
│   └── main_presenter.py   # MVP 协调器
├── service/
│   ├── library_service.py  # 媒体库服务
│   ├── queue_service.py    # 队列服务
│   └── playback_service.py # 播放服务
└── locales/
    └── interface/          # i18n 资源文件
```

## License

MIT License
