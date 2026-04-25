# PyPlayer 故障排除指南 / Troubleshooting Guide

## 常见问题 / Common Issues

### 1. 媒体库扫描问题 / Media Library Scanning Issues

#### 问题：扫描速度慢 / Slow Scanning
**症状**: 大型媒体库扫描需要很长时间

**解决方案**:
- 首次扫描后，结果会自动缓存到 `~/.pyplayer/cache/libraries/`
- 后续启动会使用缓存，无需重新扫描
- 如需强制刷新，使用菜单：`文件` → `刷新媒体库` 或 `刷新全部`

#### 问题：缓存损坏 / Corrupted Cache
**症状**: 播放列表显示异常或空白

**解决方案**:
```bash
# 删除缓存目录
rm -rf ~/.pyplayer/cache/libraries/

# 或在 Windows PowerShell
Remove-Item -Recurse -Force "$env:USERPROFILE\.pyplayer\cache\libraries\"

# 然后重新启动应用程序，将自动重新扫描
```

#### 问题：无法找到媒体文件 / Media Files Not Found
**症状**: 媒体库显示为空，但目录中确实有文件

**检查项**:
1. 确认文件扩展名在支持列表中：
   - 音频: `.mp3`, `.wav`, `.flac`, `.ogg`, `.m4a`, `.aac`
   - 视频: `.avi`, `.mp4`, `.mkv`, `.mov`, `.wmv`
2. 检查目录是否被排除：
   - `node_modules`, `.git`, `__pycache__`, `vendor`, `build`, `dist` 目录会被自动跳过

---

### 2. 播放问题 / Playback Issues

#### 问题：无法播放某些文件 / Cannot Play Certain Files
**症状**: 点击播放后没有声音或报错

**解决方案**:
1. 检查文件是否损坏：
   ```bash
   # 使用 ffprobe 检查文件
   ffprobe "your_file.mp3"
   ```
2. 确保已安装所有依赖：
   ```bash
   pip install pygame opencv-python soundfile sounddevice
   ```
3. 尝试重新安装 soundfile：
   ```bash
   pip uninstall soundfile
   pip install soundfile
   ```

#### 问题：音频播放无声音 / No Audio Output
**症状**: 播放器显示正在播放，但没有声音

**检查项**:
1. 系统音量是否静音
2. 应用程序音量混合器中 PyPlayer 是否被静音
3. 尝试播放其他文件确认是否为文件问题

#### 问题：进度条无法拖动 / Progress Slider Not Working
**症状**: 点击进度条无法跳转

**解决方案**:
- 所有支持的音频格式都支持 seek（使用 soundfile + sounddevice 后端）
- 视频文件的 seek 功能依赖于视频编码

#### 问题：大文件播放中断 / Large File Playback Interruption
**症状**: 大音频文件（>50MB或>30分钟）每分钟出现音频中断

**解决方案**:
- **v2.0 已修复**: 实现了双缓冲预加载机制，chunk切换时无缝播放
- 如仍有问题，请确保 `sounddevice` 正确安装: `pip install sounddevice`

---

### 3. 界面问题 / UI Issues

#### 问题：媒体库切换按钮不显示 / Library Selector Not Showing
**症状**: Now Playing 面板下方没有媒体库按钮

**解决方案**:
1. 确保已添加至少一个媒体库：
   - `文件` → `管理媒体库` → 点击"添加"按钮
2. 检查 `~/.pyplayer/cache/settings.json` 中是否有媒体库配置：
   ```json
   {
     "media_libraries": [
       {"path": "D:\\Music", "name": "Music"}
     ]
   }
   ```

#### 问题：媒体库管理对话框操作无效 / Library Management Dialog Not Working
**症状**: 在管理对话框中添加/删除/排序后没有生效

**解决方案**:
1. 检查文件系统权限，确保可以读写 `~/.pyplayer/cache/` 目录
2. 删除操作会弹出确认对话框，请确认已点击"是"
3. 排序操作后，媒体库按钮顺序会立即更新

#### 问题：启动时没有自动加载播放列表 / Playlist Not Auto-Loading
**症状**: 启动应用后播放列表为空

**解决方案**:
- 应用启动时会自动加载第一个媒体库的播放列表
- 如果媒体库列表为空，需要先添加媒体库：
  - `文件` → `管理媒体库` → 点击"添加"按钮

#### 问题：专辑封面不显示 / Album Art Not Showing
**症状**: Now Playing 面板显示 "No Art" 或默认封面

**可能原因**:
- 音频文件没有嵌入封面图片
- 文件格式不支持元数据读取
- FLAC 文件使用非标准封面存储方式

**解决方案**:

1. 使用诊断工具检查文件：
   ```bash
   python -c "
   from service.tools import diagnose_file
   import json
   result = diagnose_file('your_file.flac')
   print(json.dumps(result, indent=2, default=str))
   "
   ```

2. 检查诊断结果中的关键字段：
   - `has_cover_art`: 是否有封面
   - `diagnostics.has_native_pictures`: FLAC 原生 PICTURE 块
   - `diagnostics.has_metadata_block_picture`: Vorbis 注释中的封面
   - `errors`: 提取错误信息

3. 如果文件确实没有封面，使用音乐标签编辑器添加：
   - 支持的格式：MP3 (ID3), FLAC, M4A, OGG

4. 批量检查目录中缺少封面的文件：
   ```bash
   python -c "
   from service.tools.diagnostic import MetadataDiagnostic
   diag = MetadataDiagnostic()
   files = diag.find_files_without_cover('/path/to/music')
   print(f'Files without cover: {len(files)}')
   for f in files[:10]:  # 显示前10个
       print(f'  {f}')
   "
   ```

#### 问题：外观设置不生效 / Appearance Settings Not Working
**症状**: 调整透明度后界面没有变化

**解决方案**:
1. 确保点击了滑块进行调整，而不是只点击了滑块轨道
2. 检查配置文件是否正确保存：
   - 查看 `~/.pyplayer/cache/settings.json` 中的透明度设置
3. 尝试点击"恢复默认"后再重新调整

#### 问题：背景图片不显示 / Background Image Not Showing
**症状**: 设置了背景图片但界面没有显示

**解决方案**:
1. 确认图片文件存在且可访问
2. 检查图片格式是否支持（JPG、PNG、BMP、GIF、WebP）
3. 如果图片文件被移动或删除，启动时会弹出警告，需要重新选择背景图片

---

### 4. 配置问题 / Configuration Issues

#### 问题：配置文件丢失 / Config File Missing
**症状**: 启动后媒体库列表为空

**解决方案**:
1. 检查配置文件位置：
   - Windows: `C:\Users\<用户名>\.pyplayer\cache\settings.json`
   - Linux/macOS: `~/.pyplayer/cache/settings.json`
2. 手动创建 `settings.json`：
   ```json
   {
     "version": "2.0",
     "last_updated": "2024-01-01T00:00:00",
     "media_libraries": [
       {"path": "D:\\Music"}
     ],
     "overlay_alpha": 0.47,
     "playlist_alpha": 0.75,
     "controls_alpha": 0.85
   }
   ```

#### 问题：媒体库路径错误 / Invalid Library Path
**症状**: 添加媒体库后显示错误

**解决方案**:
- 确保路径存在且可访问
- Windows 路径使用双反斜杠或正斜杠：
  - 正确: `D:\\Music` 或 `D:/Music`
  - 错误: `D:\Music`

---

### 5. 国际化问题 / Internationalization Issues

#### 问题：界面语言不正确 / Wrong Interface Language
**症状**: 界面显示的语言与系统语言不符

**解决方案**:
1. 检查系统 locale 设置
2. 手动设置环境变量：
   ```bash
   # Windows PowerShell
   $env:LANG = "zh_CN.UTF-8"   # 中文
   $env:LANG = "en_US.UTF-8"   # English

   # Linux/macOS
   export LANG=zh_CN.UTF-8
   ```

---

### 6. 依赖问题 / Dependency Issues

#### 问题：ModuleNotFoundError
**症状**: 启动时提示找不到模块

**解决方案**:
```bash
# 确保在虚拟环境中
python -m venv .venv
.\.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt
```

#### 问题：soundfile 安装失败
**症状**: pip install soundfile 报错

**解决方案**:
```bash
# Windows - 使用 conda
conda install -c conda-forge pysoundfile

# 或下载预编译 wheel
pip install --only-binary :all: soundfile
```

#### 问题：PyQt6 导入错误
**症状**: ImportError: cannot import name 'PyQt6'

**解决方案**:
```bash
pip install PyQt6

# 如果仍有问题，尝试完全重装
pip uninstall PyQt6 PyQt6-Qt6 PyQt6-sip
pip install PyQt6
```

---

### 7. 缓存与存储 / Cache and Storage

#### 缓存位置 / Cache Locations
- **配置文件**: `~/.pyplayer/cache/settings.json`
- **媒体库缓存**: `~/.pyplayer/cache/libraries/*.json`
- **缓存文件命名**: SHA-256 哈希值 + `.json`

#### 清理缓存 / Clearing Cache
```bash
# 完整清理
rm -rf ~/.pyplayer/cache/

# 仅清理媒体库缓存（保留配置）
rm -rf ~/.pyplayer/cache/libraries/
```

---

## 调试模式 / Debug Mode

启用详细日志输出：

```python
# 在 main.py 开头添加
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 获取帮助 / Getting Help

如果以上方案都无法解决问题：

1. 检查 GitHub Issues: https://github.com/your-repo/PyPlayer/issues
2. 提交新 Issue 时请包含：
   - 操作系统版本
   - Python 版本 (`python --version`)
   - 错误信息完整输出
   - 重现步骤

---

## 常见故障排除快速参考

### NameError 或崩溃问题
- **最新修复 (v2.0)**: 大文件分块播放无缝切换，双缓冲预加载机制
- **修复 (v1.5)**: 默认封面图片显示修复
- **修复 (v1.4)**: FLAC 封面多策略提取
- 检查 Python 版本是否为 3.6+

### 进度条跳转不工作
- 所有音频格式现在都支持 seek 功能
- 使用 soundfile + sounddevice 后端，通过 numpy 数组切片实现精确跳转
- 如仍有问题，请检查 sounddevice 是否正确安装: `pip install sounddevice`

### 专辑封面不显示
- 确保安装了 Pillow: `pip install Pillow`
- 部分音频文件可能没有嵌入封面图片
- 无封面时现在显示 `resource/default_cover.png` 默认封面图片
- 如果默认封面文件缺失，回退显示灰色占位图

### 元数据显示 "Unknown Artist"
- 音频文件可能没有元数据标签
- 程序会自动使用文件名作为标题

### 视频无法播放
- 确保安装了完整版 `opencv-python` (非 headless)
- Windows 用户可能需要安装 Visual C++ Redistributable

### GUI 无法启动
- 确保显示环境可用（服务器需要 X11 forwarding）
- 可以使用 CLI 模式或 TUI 模式替代

### TUI 不可用 (Windows)
- Windows 默认不支持 curses，建议使用 GUI 模式 (`python main.py`)
- 可在 WSL/Cygwin 等环境中使用 TUI 模式

### 启动后播放列表为空
- 检查 `settings.json` 中 `media_libraries` 路径是否存在且包含媒体文件

### 媒体库扫描无结果
- 确保添加的路径包含支持的媒体文件 (.mp3, .wav, .flac, .ogg, .m4a, .aac, .avi, .mp4, .mkv, .mov)
- 检查 `settings.json` 是否正确保存了配置

### 音频无声
- 检查系统音量设置
- 确认音频文件格式支持 (尝试 WAV/MP3)

### Python 3.13 兼容性
- ✅ PyPlayer 现已完全兼容 Python 3.13
- 使用 soundfile + sounddevice 替代 pydub，避免 audioop 模块缺失问题
