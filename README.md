# PyPlayer - Python Music/Video Player

一个基于 Python 的多媒体播放器，支持 MP3、WAV、MP4、AVI 等常见格式。提供命令行和图形界面两种使用方式。

## 特性 / Features

- 🎵 **音频播放**: MP3, WAV, FLAC, OGG, M4A, AAC, AIFF, AU (所有格式支持seek)
- 🎬 **视频播放**: AVI, MP4, MKV, MOV, WMV
- 💻 **GUI 模式**: 基于 Tkinter 的图形界面（跨平台）
- ⌨️ **TUI 模式**: curses 终端界面 (Unix/Linux/macOS)
- 📚 **媒体库管理**: 持久化配置支持，统一管理多个媒体目录
- 🔧 **配置文件**: `settings.json` 自动保存媒体库清单（支持从 XML 自动迁移）
- 🌐 **国际化 (i18n)**: 支持中文 (zh_CN) 和英文 (en_US)，根据系统 locale 自动切换
- 🎯 **队列节点架构**: 文件夹作为独立播放单元，支持文件夹内顺序播放和跨文件夹队列播放
- 🔄 **自动播放**: 曲目播放完毕自动跳转下一首
- 🎨 **Now Playing 面板**: 显示专辑封面、歌曲标题、艺术家和专辑信息
- ⏱️ **进度条与计时器**: 实时显示播放进度，支持拖拽跳转（所有音频格式）
- 📝 **元数据提取**: 自动读取 ID3、FLAC、M4A、OGG 标签信息
- 🚀 **Python 3.13 兼容**: 使用 soundfile + sounddevice 后端，无 audioop 依赖

## 依赖安装 / Dependencies

```powershell
# Windows (推荐使用 conda)
conda install -c anaconda numpy scipy
conda install -c conda-forge opencv-python soundfile

# 或使用 pip（推荐）
pip install pygame opencv-python mutagen Pillow soundfile sounddevice numpy scipy
```

## 快速开始 / Quick Start

```bash
# 1. 安装依赖
cd PyPlayer
pip install -r requirements.txt

# 2. 启动 GUI 模式 (推荐)
python gui.py

# 或 CLI 模式直接播放
python player.py "path/to/song.mp3"
```

## License

MIT License
