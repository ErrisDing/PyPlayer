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
- 🎨 **Now Playing 面板**: 显示专辑封面、歌曲标题、艺术家和专辑信息
- ⏱️ **进度条与计时器**: 实时显示播放进度，支持拖拽跳转（所有音频格式）
- 📝 **元数据提取**: 自动读取 ID3、FLAC、M4A、OGG、NCM 标签信息

## 外观设置 / Appearance Settings

- 🖼️ **自定义背景**: 设置背景图片，等比缩放适配窗口
- ✨ **透明效果**: 播放列表、控制面板支持自定义透明度
- 🎨 **统一配置**: 通过 `文件` → `外观设置` 打开配置弹窗

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
│       ├── now_playing_panel.py   # 正在播放面板
│       ├── library_selector.py    # 媒体库切换器
│       ├── playlist_view.py       # 播放列表视图
│       ├── bottom_panel.py        # 底部面板（进度条+控制按钮）
│       ├── progress_slider.py     # 进度条组件
│       └── control_panel.py       # 控制面板组件
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
