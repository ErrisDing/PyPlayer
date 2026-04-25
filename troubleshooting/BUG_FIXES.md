# PyPlayer Bug Fixes & Troubleshooting

## 已完成的修复（高优先级）

### 1. i18n locale检测API修复
- **文件**: `i18n.py` (第50-55行)
- **问题**: 使用已弃用的`locale.getdefaultlocale()[0]` API (Python 3.11+)
- **修复**: 使用`locale.getlocale()[0]`替代，并添加向后兼容回退机制
- **代码示例**:
  ```python
  # 优先使用getlocale() (Python 3.11+推荐)
  detected = locale.getlocale()[0]

  # 如果getlocale返回None，尝试旧API保持向后兼容
  if detected is None:
      try:
          detected = locale.getdefaultlocale()[0]
      except AttributeError:
          # Python 3.11+中getdefaultlocale已移除
          pass
  ```

### 2. 空字符串默认值修复
- **文件**: `i18n.py` (第149行和第190行)
- **问题**: `default_value or f"[MISSING: {keyword}]"`逻辑中，空字符串`""`被视为False
- **修复**: 明确检查`default_value is not None`而非依赖短路逻辑
- **代码示例**:
  ```python
  if value is None:
      if default_value is not None:
          return default_value
      return f"[MISSING: {keyword}]"
  ```

### 3. i18n缓存逻辑优化
- **文件**: `i18n.py` (第178-199行)
- **问题**: 缓存键不一致，`get_category()`每次调用加载整个属性文件
- **修复**: 统一使用`load_properties()`的字典缓存，移除`get_category()`的独立缓存逻辑
- **代码示例**:
  ```python
  # 简化get_category函数，直接使用load_properties的缓存
  props = load_properties(category)
  value = props.get(keyword, None)
  ```

### 4. Windows路径处理修复
- **文件**: `library_manager.py` (第245-257行)
- **问题**: 字符串替换处理Windows路径不完整，生成无效路径`/C:/Music`
- **修复**: 使用`Path`对象方法进行跨平台路径解析
- **代码示例**:
  ```python
  path_obj = Path(full_path)
  parts = list(path_obj.parts)  # 获取路径组件元组

  # 使用Path对象构建跨平台路径
  parent_path_obj = Path(*parts[:i+1])
  parent_path = parent_path_obj.as_posix()  # 统一使用正斜杠
  ```

### 5. 缺失翻译完成
- **文件**: `locales/interface/main.zh_CN.properties` (第19行)
- **问题**: `file.select_library=Select Library Folder`未翻译
- **修复**: 添加中文翻译`选择媒体库文件夹`
- **验证**: 设置locale为`zh_CN`后应显示中文翻译

### 6. 配置格式从XML迁移到JSON
- **文件**: `config.py` (全局修改)
- **问题**: 使用XML格式配置文件，相对于JSON格式更冗长，不便手动编辑
- **修复**: 迁移到JSON格式，保持向后兼容性和API兼容性
- **主要修改**:
  1. **常量更新**: `DEFAULT_FILE = "settings.json"`, `XML_FILE = "settings.xml"`, `CONFIG_VERSION = "2.0"`
  2. **自动迁移**: `_check_and_migrate()`方法检测并执行XML到JSON迁移
  3. **迁移方法**: `_migrate_xml_to_json()`方法执行XML到JSON的转换
  4. **加载策略**: `load()`方法支持JSON优先，XML回退的加载策略
  5. **原子写入**: `save()`方法使用JSON格式和原子写入
  6. **向后兼容**: 保持现有API完全兼容，外部代码无需修改
- **迁移流程**:
  1. 检测现有`settings.xml`文件是否存在
  2. 解析XML文件，提取媒体库配置和时间戳
  3. 转换为JSON格式，添加版本号字段
  4. 原子写入`settings.json`文件
  5. 备份原XML文件为`settings.xml.backup`
- **代码示例**:
  ```python
  def _migrate_xml_to_json(self, xml_path: Path, json_path: Path) -> bool:
      """从XML迁移到JSON格式"""
      try:
          # 1. 解析XML
          tree = ET.parse(xml_path)
          root = tree.getroot()

          # 2. 提取数据
          last_updated = root.get('last_updated', datetime.now().isoformat())

          libraries = []
          media_libs_elem = root.find("media_libraries")
          if media_libs_elem is not None:
              for lib_elem in media_libs_elem.findall("library"):
                  path = lib_elem.get("path", "")
                  if path:
                      name = lib_elem.get("name", None)
                      libraries.append({
                          "path": os.path.normpath(path),
                          "name": name
                      })

          # 3. 构建JSON数据
          data = {
              "version": self.CONFIG_VERSION,
              "last_updated": last_updated,
              "media_libraries": libraries
          }

          # 4. 原子写入JSON
          temp_path = json_path.with_suffix('.tmp')
          with open(temp_path, 'w', encoding='utf-8') as f:
              json.dump(data, f, indent=2, ensure_ascii=False)

          temp_path.rename(json_path)

          # 5. 备份原XML文件
          backup_path = xml_path.with_suffix('.xml.backup')
          try:
              xml_path.rename(backup_path)
              print(f"Migrated configuration to {json_path}, backup at {backup_path}")
          except OSError as e:
              print(f"Migration successful but backup failed: {e}")

          return True

      except (ET.ParseError, OSError, IOError, json.JSONEncodeError) as e:
          print(f"Migration failed: {e}")
          if 'temp_path' in locals() and temp_path.exists():
              temp_path.unlink(missing_ok=True)
          return False
  ```

## 验证测试

运行以下命令验证修复：

```bash
# 测试i18n空字符串默认值
python -c "import i18n; print('空字符串测试:', repr(i18n.get('nonexistent.key', default='')))"

# 测试Windows路径处理
python -c "
from library_manager import _HierarchicalPlaylist
p = _HierarchicalPlaylist()
p.add_track('C:\\\\Music\\\\song.mp3', 'test')
print('路径处理测试: 成功')
"

# 测试翻译（需要设置中文locale）
python -c "
import i18n
i18n.set_locale('zh_CN')
print('中文翻译测试:', i18n.get('file.select_library'))
"

# 测试配置迁移（需要settings.xml文件）
python -c "
import sys
sys.path.insert(0, '.')
from config import SettingsManager
import os

# 如果有settings.xml，测试迁移
if os.path.exists('settings.xml'):
    print('settings.xml exists, testing migration...')
    # 删除可能存在的迁移结果
    for f in ['settings.json', 'settings.xml.backup']:
        if os.path.exists(f):
            os.remove(f)

    manager = SettingsManager()
    print(f'Config loaded, libraries: {len(manager.settings.media_libraries)}')
    print(f'settings.json created: {os.path.exists(\"settings.json\")}')
    print(f'settings.xml.backup created: {os.path.exists(\"settings.xml.backup\")}')
else:
    print('No settings.xml found, creating test config...')
    manager = SettingsManager()
    manager.settings.add_library('/test/path', 'Test Library')
    manager.save()
    print(f'JSON config saved, exists: {os.path.exists(\"settings.json\")}')
    # 清理测试文件
    if os.path.exists('settings.json'):
        os.remove('settings.json')
print('配置迁移测试: 成功')
"
```

## 待处理的改进（根据用户选择的"深度修复加改进"）

### 中等优先级修复
1. **统一注释语言**: 将中文注释改为英文（建议）
2. **异常处理细化**: 使用更具体的异常类型替代泛化的`Exception`
3. **添加类型注解**: 为函数添加完整的类型注解

### 配置格式迁移 ✅ **已完成**
1. **✅ 评估迁移方案**: 已完成XML配置使用情况分析
2. **✅ 设计JSON格式**: 已完成JSON配置格式设计
3. **✅ 实施迁移**: 已实现支持JSON和XML回退的配置管理器
4. **✅ 保持向后兼容性**: 已实现自动迁移工具和原子写入

### 性能优化
1. **播放列表性能**: 优化`build_display_list()`递归算法
2. **i18n性能**: 预加载常用翻译文件，优化占位符替换逻辑

## 建议的下一步

1. **立即进行**: 中等优先级修复（注释统一、异常处理细化）
2. **已完成**: 配置格式迁移到JSON格式 ✅
3. **后续优化**: 性能改进（在性能问题出现时进行）

## 风险说明

- **低风险**: 已完成的修复是局部修改，不影响核心功能
- **兼容性**: locale检测修复保持向后兼容
- **跨平台**: 路径处理修复确保在Windows/Linux/macOS上正常工作
- **配置迁移**: ✅ 已实现安全迁移，包含自动备份和原子写入

---

*修复完成时间: 2026-04-19*
*所有高优先级问题已解决，配置格式迁移到JSON已完成*

---

## 队列管理系统重构 (2026-04-19)

### 问题描述
原播放器存在以下核心问题：
1. 只有第一个媒体库正确加载，后续库被当作普通文件夹处理
2. 缺乏独立队列管理，所有文件共享一个扁平播放列表
3. 无状态机支持前进/后退导航
4. 无跨队列播放能力（"播放全部"功能缺失）

### 修复内容

#### 1. AudioPlayer 类结构修复
- **文件**: `player.py`
- **问题**: `PlaybackQueueInfo` 类被错误地插入到 `AudioPlayer` 类内部，导致 `play_file`、`stop`、`is_active` 等核心方法丢失
- **修复**: 删除错误的 `PlaybackQueueInfo` 类，将核心播放方法恢复到 `AudioPlayer` 类中

#### 2. 新增队列感知方法
```python
# AudioPlayer 新增方法
def play_from_queue(self, library_id: str, position_index: Optional[int] = None) -> bool
def next_track_in_queue(self, library_id: str, loop_mode: str = "OFF") -> bool
def prev_track_in_queue(self, library_id: str) -> bool
def register_library_queue(self, library_id: str, queue: 'PlaybackQueue') -> None
def unregister_library_queue(self, library_id: str) -> bool
```

#### 3. 状态机实现 (library_manager.py)
```python
@dataclass
class PlaybackState:
    current_position: int = 0
    history: List[int] = field(default_factory=list)
    loop_mode: str = "OFF"  # "OFF", "ONE", "ALL"

    def record_position(self, new_pos: int) -> None:
        if self.current_position != new_pos:
            self.history.append(self.current_position)
            self.current_position = new_pos

@dataclass
class PlaybackQueue:
    library_id: str
    track_list: List[Track] = field(default_factory=list)
    current_index: int = -1  # -1 = idle
    state: str = "IDLE"  # IDLE, LOADING, PLAYING, PAUSED, COMPLETED
    position_state: PlaybackState = field(init=False)  # auto-created
```

#### 4. 向后兼容性
- `PlayerManager.get_status()` 返回值新增可选字段 `library_queues_status`
- 现有 GUI/TUI 代码无需修改即可正常工作
- 测试文件 `test_player.py` 验证所有 8 个核心功能

### 验证测试
```bash
python test_player.py
# Ran 8 tests in 0.001s
# OK
```

### 错误修复详情
| 错误 | 原因 | 修复 |
|------|------|------|
| `AttributeError: 'AudioPlayer' object has no attribute 'play_file'` | `PlaybackQueueInfo` 类定义在 `AudioPlayer` 类内部，导致方法归属错误 | 删除 `PlaybackQueueInfo` 类，将方法移回 `AudioPlayer` |
| `AttributeError: 'AudioPlayer' object has no attribute 'stop'` | 同上 | 同上 |
| `AttributeError: 'AudioPlayer' object has no attribute 'is_active'` | 同上 | 同上 |

---

*队列管理修复完成时间: 2026-04-19*

---

## QueueNode 队列节点架构重构 (2026-04-19)

### 问题描述
播放列表管理存在严重的索引错位问题：
- `self.playlist` 是扁平的 `List[Track]`，只包含文件轨道
- `_update_playlist_display()` 构建的是层级显示，包含文件夹和文件
- 显示索引与播放列表索引不匹配：显示有 N+M 项（含文件夹），播放列表只有 N 项
- `_get_track_from_display_idx()` 用显示索引访问 `self.playlist[i]`，导致 `IndexError: list index out of range`

### 核心设计

引入 **QueueNode** 抽象，每个节点是一个可播放单元：

```
QueueNode (abstract)
├── FileNode: 单文件节点
└── FolderNode: 文件夹节点
    ├── tracks: List[Track]
    ├── current_sub_index: int
    └── loop_mode: str
```

### 修复内容

#### 1. QueueNode 数据结构 (library_manager.py)

新增四个类：

| 类名 | 类型 | 说明 |
|------|------|------|
| `QueueNode` | ABC | 可播放队列节点的抽象基类 |
| `FileNode` | dataclass | 单文件节点，包含一个 Track |
| `FolderNode` | dataclass | 文件夹节点，维护内部播放状态 (`current_sub_index`, `loop_mode`) |
| `DisplayIndexMap` | dataclass | 显示索引到队列节点的映射表 |

`FolderNode` 关键方法：
- `get_current_track()` - 获取当前播放轨道
- `advance_to_next()` - 前进到下一首（支持 OFF/ONE/ALL 循环模式）
- `advance_to_prev()` - 后退到上一首
- `reset()` - 重置播放状态
- `set_sub_index()` - 设置播放位置并返回轨道

`DisplayIndexMap` 关键方法：
- `add_entry()` - 添加映射条目 (display_idx → node_idx + sub_index)
- `get_by_display_idx()` - 根据显示索引获取映射
- `get_by_full_path()` - 根据完整路径获取映射

#### 2. 曲目结束回调 (player.py)

```python
# AudioPlayer 新增
self._on_track_end_callback: Optional[callable] = None

def set_track_end_callback(self, callback: callable) -> None
def clear_track_end_callback(self) -> None

# PlayerManager 新增
self._was_playing = False  # 跟踪上一帧播放状态

def check_track_end(self) -> bool  # 检测轨道是否播放完毕并触发回调
```

#### 3. GUI 架构重构 (gui.py)

**数据结构替换**：
```python
# 旧
self.playlist: List[Track] = []

# 新
self.queue_nodes: List[QueueNode] = []
self.display_map: DisplayIndexMap = DisplayIndexMap()
self.current_node_idx: int = -1
self.current_sub_index: int = -1

# 向后兼容 - playlist 属性
@property
def playlist(self):
    """从 queue_nodes 生成扁平轨道列表"""
```

**重写的方法**：

| 方法 | 旧逻辑 | 新逻辑 |
|------|--------|--------|
| `_update_playlist_display()` | 仅构建层级显示 | 同时构建 `display_map` 映射 |
| `_get_track_from_display_idx()` | 重建 hierarchy 匹配，索引易错位 | 直接查表 `display_map.get_by_display_idx()` |
| `_on_double_click()` | 混合处理，fallback 查找 | 通过映射区分文件夹/文件节点 |
| `_next_track()` | 简单 `% len` 循环 | 文件夹内顺序播放 → 文件夹间跳转 |
| `_prev_track()` | 简单 `% len` 循环 | 文件夹内后退 → 跨文件夹后退 |
| `_scan_directory()` | 扁平追加到 playlist | 按父目录分组构建 FolderNode |

**新增方法**：
- `_play_folder_node(node_idx)` - 播放文件夹节点，从第一首开始
- `_play_file_node(node_idx, sub_index)` - 播放文件节点或文件夹内特定文件
- `_play_first_node()` - 播放队列中第一个节点
- `_find_node_idx_by_path(path, is_folder)` - 根据路径查找节点索引

**删除方法**：
- `_get_track_info_from_display_idx()` - 被 `display_map` 替代
- `_play_folder()` - 被 `_play_folder_node()` 替代

**曲目结束自动播放**：
`run_gui()` 中设置 `set_track_end_callback(on_track_end)`，更新循环中调用 `check_track_end()` 实现自动下一首。

### 向后兼容性

- `self.playlist` 通过 `@property` 保持向后兼容，返回 `queue_nodes` 的扁平轨道列表
- `self.playlist` setter 可将 Track 列表转换为 FileNode
- `_HierarchicalPlaylist` 显示逻辑保持不变，仅新增映射层
- `self.current_index` 和 `self.selected_index` 保留用于显示选择状态

### 验证步骤

1. **语法检查**: `python -m py_compile gui.py library_manager.py player.py` ✅
2. **手动测试**:
   - 扫描包含多层嵌套文件夹的媒体库
   - 双击文件夹，验证从第一首开始播放
   - 点击下一首，验证文件夹内顺序播放
   - 文件夹最后一首播完后，验证跳转到下一文件夹
   - 双击单个文件，验证只播放该文件
   - 点击上一首，验证正确回退
   - 曲目播完自动播放下一首

---

*QueueNode 架构重构完成时间: 2026-04-19*

---

## 主页面重构 - Now Playing 面板 (2026-04-19)

### 新增功能

#### 1. 元数据提取模块 (metadata.py)
- **新增文件**: `metadata.py`
- **依赖**: `mutagen>=1.47.0`, `Pillow>=10.0.0`
- **支持格式**:
  - MP3 (ID3v2 标签, APIC 封面)
  - FLAC (Vorbis 注释, 嵌入图片)
  - M4A/MP4 (iTunes 风格标签, covr 封面)
  - OGG Vorbis (Vorbis 注释, metadata_block_picture)
- **数据结构**:
  ```python
  @dataclass
  class SongMetadata:
      title: str
      artist: str
      album: str
      duration: float  # 秒
      album_art: Optional[bytes] = None
  ```
- **兜底逻辑**: 无元数据时使用文件名作为标题，"Unknown Artist/Album" 作为默认值

#### 2. Track 数据结构扩展 (library_manager.py)
- **新增字段**:
  ```python
  @dataclass
  class Track:
      path: str
      title: str
      artist: Optional[str] = None
      album: Optional[str] = None
      duration: float = 0.0
  ```

#### 3. 播放器位置追踪 (player.py)
- **新增实例变量**:
  ```python
  self._play_start_time: float = 0.0
  self._pause_accumulated: float = 0.0
  self._track_duration: float = 0.0
  self._current_file_ext: str = ""
  ```
- **新增类常量**:
  ```python
  SEEKABLE_FORMATS = {'.mp3', '.ogg'}  # 仅 MP3/OGG 支持 seek
  ```
- **修改方法**:
  - `play_file()`: 加载元数据，初始化位置追踪
  - `pause()`: 记录累计播放时间
  - `resume()`: 重置开始时间
- **新增方法**:
  ```python
  def get_position(self) -> float  # 当前播放位置（秒）
  def get_duration(self) -> float  # 当前曲目时长
  def seek(self, position_seconds: float) -> bool  # 跳转（仅 MP3/OGG）
  def is_seekable(self) -> bool  # 检查当前格式是否支持 seek
  ```

#### 4. GUI 重构 (gui.py)
- **移除**: 停止按钮（简化控制栏）
- **新增 Now Playing 面板**:
  - 专辑封面 (100x100 像素，PIL 处理)
  - 歌曲标题 (大号字体)
  - 艺术家 (次要信息)
  - 专辑名 (次要信息)
- **新增进度面板**:
  - 当前时间显示 (左侧, `0:00` 格式)
  - 进度滑块 (中间，可拖拽跳转)
  - 总时长显示 (右侧)
- **新增方法**:
  ```python
  def _configure_styles()           # ttk 样式配置
  def _create_now_playing_panel()   # Now Playing 面板
  def _create_progress_panel()      # 进度条面板
  def _format_time(seconds) -> str  # 时间格式化 (M:SS 或 H:MM:SS)
  def _on_progress_change(value)    # 进度条拖拽
  def _on_progress_release(event)   # 进度条释放 → seek
  def _update_progress()            # 进度更新循环 (250ms)
  def _update_now_playing(track)    # 更新元数据显示
  def _update_now_playing_with_art(filepath)  # 更新显示含封面
  def _update_album_art(bytes)      # 更新专辑封面
  def _set_default_album_art()      # 默认占位图
  ```

#### 5. i18n 更新
- **新增键**:
  ```properties
  metadata.unknown_artist=Unknown Artist
  metadata.unknown_album=Unknown Album
  metadata.no_track=No track playing
  ```
- **移除键**: `button.stop`

### 限制说明

| 功能 | 支持格式 | 说明 |
|------|----------|------|
| Seek (跳转) | MP3, OGG | pygame.mixer 限制，其他格式进度条仅显示 |
| 元数据提取 | MP3, FLAC, M4A, OGG | WAV 无标准元数据，使用文件名 |
| 专辑封面 | MP3, FLAC, M4A, OGG | WAV 无嵌入封面 |

### 验证测试

```bash
# 测试模块导入
python -c "from core.metadata import extract_metadata; from core.player import AudioPlayer; print('OK')"

# 测试元数据提取
python -c "
from core.metadata import extract_metadata
meta = extract_metadata('test/song.mp3')
print(f'Title: {meta.title}')
print(f'Artist: {meta.artist}')
print(f'Duration: {meta.duration:.1f}s')
"
```

---

*主页面重构完成时间: 2026-04-19*

---

## 音频后端重构 - soundfile + sounddevice (2026-04-19)

### 问题背景
原 pygame.mixer 后端存在以下限制：
1. **Seek支持有限**: 仅 MP3 和 OGG 格式支持进度跳转
2. **进度追踪不精确**: 依赖 time.time() 外部计算

### 技术选型过程

| 方案 | 结果 | 原因 |
|------|------|------|
| pydub + simpleaudio | ❌ 放弃 | Python 3.13 移除 audioop 模块 |
| soundfile + sounddevice + numpy | ✅ 采用 | 无 audioop 依赖，兼容 Python 3.13 |

### 实现详情

#### 1. 依赖更新 (requirements.txt)
```diff
- pydub>=0.25.1
- simpleaudio>=1.0.4
+ soundfile>=0.12.0
+ sounddevice>=0.4.0
+ numpy>=1.24.0
+ scipy>=1.10.0
```

#### 2. AudioPlayer 类重构 (player.py)

**核心数据结构变更**:
```python
# 旧 (pygame.mixer)
self._current_file: Optional[str] = None
pygame.mixer.music.load(filepath)
pygame.mixer.music.play()

# 新 (soundfile + sounddevice)
self._audio_data: Optional[np.ndarray] = None  # 音频数据为numpy数组
self._sample_rate: int = 44100
self._channels: int = 2
self._total_samples: int = 0
```

**核心方法变更**:

| 方法 | 旧实现 | 新实现 |
|------|--------|--------|
| `play_file()` | pygame.mixer.music.load() + play() | sf.read() + sd.OutputStream |
| `seek()` | 仅MP3/OGG，停止重载播放 | numpy数组切片，所有格式支持 |
| `pause()/resume()` | pygame.mixer.music.pause() | stream.stop()/重新启动 |
| `get_position()` | time.time()计算 | 样本索引计算 |
| `set_volume()` | pygame.mixer.music.set_volume() | numpy数组乘法 |

**新增特性**:
- 所有音频格式支持精确 seek（通过numpy数组切片）
- 基于样本索引的精确位置追踪
- 回调式音频流播放（sounddevice.OutputStream）
- 大文件分段加载（>50MB 或 >30分钟）

#### 3. 支持格式扩展

```python
SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.aiff', '.au'}
```

### 验证测试

```bash
# 测试模块导入
python -c "from player import AudioPlayer, VideoPlayer, PlayerManager; print('OK')"

# 测试基本功能
python -c "
from player import AudioPlayer, PlayerManager
player = AudioPlayer()
print(f'is_seekable: {player.is_seekable()}')  # 应返回 True
manager = PlayerManager()
formats = manager.get_supported_formats()
print(f'Audio: {formats[\"音频\"]}')  # 应包含 .aac, .aiff, .au 等
"
```

---

*音频后端重构完成时间: 2026-04-19*

---

## 常见故障排除

### NameError 或崩溃问题
- **最新修复 (v1.3)**: 新增 Now Playing 面板、进度条、元数据提取功能
- **修复 (v1.2)**: QueueNode 架构重构，彻底解决播放列表索引错位问题
- **修复 (v1.1)**: 已修复 `AudioPlayer` 类结构问题，`play_file`、`stop`、`is_active` 等方法现已正确归属于 `AudioPlayer` 类
- **队列管理修复**: 独立队列系统已实现，每个媒体库维护独立的播放状态
- 如遇其他异常，检查 Python 版本是否为 3.6+

### 进度条跳转不工作
- **v1.4 更新**: 所有音频格式现在都支持 seek 功能
- 使用 soundfile + sounddevice 后端，通过 numpy 数组切片实现精确跳转
- 如仍有问题，请检查 sounddevice 是否正确安装: `pip install sounddevice`

### 专辑封面不显示
- 确保安装了 Pillow: `pip install Pillow`
- 部分音频文件可能没有嵌入封面图片
- **v1.5 更新**: 无封面时现在显示 `resource/default_cover.png` 默认封面图片
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
- **v1.6 修复**: 修复 `LibraryRuntime` 初始化参数错误（`playback_queue=None` 不应传入 `init=False` 字段）
- **v1.6 修复**: 调整队列服务初始化顺序，先 `set_current_library` 再 `build_from_tracks`
- 如仍有问题，检查 `settings.json` 中 `media_libraries` 路径是否存在且包含媒体文件

### 媒体库扫描无结果
- 确保添加的路径包含支持的媒体文件 (.mp3, .wav, .flac, .ogg, .m4a, .aac, .avi, .mp4, .mkv, .mov)
- 检查 `settings.json` 是否正确保存了配置

### 音频无声
- 检查系统音量设置
- 确认音频文件格式支持 (尝试 WAV/MP3)

### Python 3.13 兼容性
- ✅ PyPlayer 现已完全兼容 Python 3.13
- 使用 soundfile + sounddevice 替代 pydub，避免 audioop 模块缺失问题

---

## PyQt6 前端修复 (2026-04-19)

### 1. JSONEncodeError 属性错误修复
- **文件**: `config.py`, `cache_manager.py`
- **问题**: `json` 模块没有 `JSONEncodeError` 属性，正确的名称是 `JSONDecodeError`
- **修复**: 将 `json.JSONEncodeError` 改为 `TypeError`，因为 `json.dump()` 在序列化失败时抛出 `TypeError`
- **代码示例**:
  ```python
  # 修复前
  except (OSError, IOError, json.JSONEncodeError) as e:

  # 修复后
  except (OSError, IOError, TypeError) as e:
  ```

### 2. Windows 文件覆盖错误修复
- **文件**: `config.py`, `cache_manager.py`
- **问题**: 在 Windows 上 `Path.rename()` 无法覆盖已存在的文件，抛出 `WinError 183`
- **修复**: 使用 `os.replace()` 替代 `Path.rename()`，支持原子性覆盖
- **代码示例**:
  ```python
  # 修复前
  temp_path.rename(self.config_file)

  # 修复后
  os.replace(temp_path, self.config_file)
  ```

### 3. 媒体库列表未同步刷新
- **文件**: `presenter/main_presenter.py`
- **问题**: 添加新媒体库后，UI 中的媒体库列表未更新
- **修复**: 在 `_on_add_library` 成功后调用 `self._view.set_libraries()` 刷新列表
- **代码示例**:
  ```python
  def _on_add_library(self, path: str) -> None:
      if self._config.add_library(path):
          self._library.load_library(path)
          # 新增：刷新媒体库列表
          libraries = self._config.get_libraries()
          self._view.set_libraries(libraries)
          self._view.set_status_message(f"Added library: {path}")
  ```

### 4. 歌曲时长显示不准确
- **文件**: `player.py`
- **问题**: `get_duration()` 优先返回元数据中的时长，可能为 0 或不准确
- **修复**: 优先使用实际解码的时长 `_total_samples / _sample_rate`
- **代码示例**:
  ```python
  # 修复前
  def get_duration(self) -> float:
      if self.current_track and hasattr(self.current_track, 'duration'):
          return self.current_track.duration
      return self._total_samples / self._sample_rate if self._sample_rate > 0 else 0.0

  # 修复后
  def get_duration(self) -> float:
      # 优先使用实际解码的时长
      if self._sample_rate > 0 and self._total_samples > 0:
          return self._total_samples / self._sample_rate
      # 回退到元数据
      if self.current_track and hasattr(self.current_track, 'duration'):
          return self.current_track.duration
      return 0.0
  ```

### 5. 音量条拖动导致并发播放
- **文件**: `player.py`
- **问题**: `set_volume()` 在播放时重新加载文件并启动新播放线程，未停止旧线程，导致多个声音同时播放
- **修复**: 移除重新加载逻辑，改为在音频回调中动态应用音量
- **代码修改**:
  1. 加载时不再预乘音量，存储原始音频数据
  2. 在 `audio_callback` 中动态应用 `self._volume`
- **代码示例**:
  ```python
  # 修复前 - set_volume 会重新加载文件
  def set_volume(self, level: float) -> None:
      self._volume = max(0.0, min(1.0, level))
      if self.is_playing and not self.is_paused:
          # 重新加载文件并播放 - 导致并发问题
          audio_data, sample_rate = sf.read(self._filepath, ...)
          self._audio_data = audio_data * self._volume
          self._start_playback(from_sample=...)

  # 修复后 - 简化为仅设置音量值
  def set_volume(self, level: float) -> None:
      self._volume = max(0.0, min(1.0, level))

  # 在 audio_callback 中动态应用音量
  def audio_callback(outdata, frames, time_info, status):
      ...
      outdata[:] = samples_to_play[start:end] * self._volume  # 动态应用音量
  ```

### 6. 进度条点击跳转功能
- **文件**: `view/widgets/progress_slider.py`
- **问题**: 进度条只能通过拖动滑块跳转，点击轨道无法跳转
- **修复**: 创建自定义 `ClickableSlider` 类，重写 `mousePressEvent` 实现点击跳转
- **代码示例**:
  ```python
  class ClickableSlider(QSlider):
      """支持点击轨道跳转的滑块"""

      def mousePressEvent(self, event: QMouseEvent) -> None:
          if event.button() == Qt.MouseButton.LeftButton:
              # 计算点击位置对应的值
              value = self.minimum() + int(
                  event.position().x() / self.width() * (self.maximum() - self.minimum())
              )
              self.setValue(value)
              # 发射信号更新显示并触发跳转
              self.sliderMoved.emit(value)
              self.sliderReleased.emit()
              return
          super().mousePressEvent(event)
  ```

---

*PyQt6 前端修复完成时间: 2026-04-19*

---

## 默认封面图片显示修复 (2026-04-20)

### 问题描述
当歌曲没有嵌入封面图片时：
1. `resource/default_cover.png` 存在但未被使用
2. UI 显示动态生成的灰色占位图，而非预设的默认封面
3. 原因是 `album_art_loaded` 信号仅在歌曲有封面时触发，无封面时不更新显示

### 修复内容

#### 1. PyQt UI 默认封面加载 (view/widgets/now_playing_panel.py)
- **问题**: `_clear_art()` 方法显示 "No Art" 文本占位符，未使用默认封面
- **修复**:
  1. 添加模块级常量 `DEFAULT_COVER_PATH` 指向 `resource/default_cover.png`
  2. 添加类属性 `_default_pixmap: Optional[QPixmap]` 缓存默认封面（类级别，避免重复加载）
  3. 添加 `@classmethod _load_default_cover()` 方法加载并缓存默认封面
  4. 修改 `_clear_art()` 方法显示缩放后的默认封面图片
- **代码示例**:
  ```python
  # 默认封面路径
  DEFAULT_COVER_PATH = Path(__file__).parent.parent.parent / "resource" / "default_cover.png"

  class NowPlayingPanel(QWidget):
      _default_pixmap: Optional[QPixmap] = None  # 类级别缓存

      @classmethod
      def _load_default_cover(cls) -> None:
          """Load and cache the default cover image."""
          if cls._default_pixmap is not None:
              return
          if DEFAULT_COVER_PATH.exists():
              cls._default_pixmap = QPixmap(str(DEFAULT_COVER_PATH))
              if cls._default_pixmap.isNull():
                  cls._default_pixmap = None

      def _clear_art(self) -> None:
          """Clear album art and show default cover or placeholder."""
          if self._default_pixmap and not self._default_pixmap.isNull():
              scaled = self._default_pixmap.scaled(
                  self.ART_SIZE, self.ART_SIZE,
                  Qt.AspectRatioMode.KeepAspectRatio,
                  Qt.TransformationMode.SmoothTransformation
              )
              self._art_label.setPixmap(scaled)
          else:
              # Fallback to text placeholder
              self._art_label.clear()
              self._art_label.setText("No Art")
  ```

#### 2. Tkinter UI 默认封面加载 (gui.py) [已移除]
> **注意**: Tkinter GUI (`gui.py`) 已于 2026-04-20 移除，项目现在仅使用 PyQt6 GUI。

- **问题**: `_set_default_album_art()` 方法动态生成灰色图片，未使用默认封面
- **修复**:
  1. 添加 `DEFAULT_COVER_PATH` 常量
  2. 修改 `_set_default_album_art()` 优先加载默认封面文件
  3. 正确处理 RGBA 图像的透明度
  4. 加载失败时回退到灰色占位图
- **代码示例**:
  ```python
  DEFAULT_COVER_PATH = Path(__file__).parent / "resource" / "default_cover.png"

  def _set_default_album_art(self):
      if PIL_AVAILABLE:
          if DEFAULT_COVER_PATH.exists():
              try:
                  img = Image.open(DEFAULT_COVER_PATH)
                  img.thumbnail((100, 100), Image.Resampling.LANCZOS)
                  canvas = Image.new('RGB', (100, 100), color='#ffffff')
                  offset = ((100 - img.width) // 2, (100 - img.height) // 2)
                  if img.mode == 'RGBA':
                      canvas.paste(img, offset, mask=img.split()[3])
                  else:
                      canvas.paste(img, offset)
                  self.default_album_art = ImageTk.PhotoImage(canvas)
                  self.album_art_label.configure(image=self.default_album_art)
                  return
              except Exception as e:
                  print(f"Warning: Failed to load default cover: {e}")
          # Fallback: gray placeholder
          img = Image.new('RGB', (100, 100), color='#cccccc')
          self.default_album_art = ImageTk.PhotoImage(img)
  ```

#### 3. Presenter 无封面时触发更新 (presenter/main_presenter.py)
- **问题**: 当 `metadata.album_art` 为 `None` 时，`album_art_loaded` 信号不触发，UI 不更新
- **修复**: 在 `_on_metadata_loaded` 中检查，无封面时调用 `update_album_art(None)` 显示默认封面
- **代码示例**:
  ```python
  @pyqtSlot(str, object)
  def _on_metadata_loaded(self, filepath: str, metadata) -> None:
      current = self._playback.current_track
      if current and current.path == filepath:
          self._view.update_track_info(
              metadata.title,
              metadata.artist,
              metadata.album
          )
          # 新增：无封面时显示默认封面
          if not metadata.album_art:
              self._view.update_album_art(None)
  ```

### 数据流程说明

```
播放歌曲
    │
    ▼
MetadataService.load_async()
    │
    ▼
extract_metadata() → SongMetadata(album_art=None 或 bytes)
    │
    ├── 有封面 (album_art is not None)
    │       │
    │       ▼
    │   album_art_loaded.emit(filepath, art_data)
    │       │
    │       ▼
    │   _on_album_art_loaded() → update_album_art(art_data)
    │
    └── 无封面 (album_art is None)
            │
            ▼
        metadata_loaded.emit(filepath, metadata)
            │
            ▼
        _on_metadata_loaded()
            │
            ▼
        检测 album_art is None → update_album_art(None)
            │
            ▼
        _clear_art() → 显示默认封面
```

### 验证测试

```bash
# 测试默认封面存在
python -c "from pathlib import Path; print(Path('resource/default_cover.png').exists())"

# 测试 PyQt 组件
python -c "
from view.widgets.now_playing_panel import NowPlayingPanel, DEFAULT_COVER_PATH
print(f'Default cover path: {DEFAULT_COVER_PATH}')
print(f'Exists: {DEFAULT_COVER_PATH.exists()}')
"
```

---

*默认封面修复完成时间: 2026-04-20*

---

## FLAC 封面图片提取重构 (2026-04-20)

### 问题描述
用户反馈 FLAC 文件的专辑封面没有正确加载。原实现仅检查 `audio.pictures`，但 FLAC 文件可能使用多种封面存储方式。

### 问题分析

原 `metadata.py` 中 FLAC 封面提取实现：
```python
if audio.pictures:
    album_art = audio.pictures[0].data
```

**可能的失败原因**：
1. `audio.pictures` 为空列表 - FLAC 文件可能使用非标准封面存储方式
2. 封面存储在 Vorbis 注释的 `METADATA_BLOCK_PICTURE` 标签中（base64 编码），而非 FLAC 原生 PICTURE 块
3. 封面存储在旧版 `COVERART` 标签中
4. 异常被静默捕获，无诊断信息

### 解决方案

#### 新增 `service/tools/` 模块

创建可扩展的元数据提取工具模块：

| 文件 | 说明 |
|------|------|
| `service/tools/base.py` | 基类 (`MetadataExtractor`) 和数据结构 (`ExtractionResult`, `ExtractedPicture`, `PictureType`) |
| `service/tools/flac.py` | FLAC 提取器，支持多策略封面提取 |
| `service/tools/mp3.py` | MP3/ID3 提取器 |
| `service/tools/m4a.py` | M4A/MP4 提取器 |
| `service/tools/ogg.py` | OGG Vorbis 提取器，支持多策略封面提取 |
| `service/tools/diagnostic.py` | 诊断工具 (`MetadataDiagnostic`) |
| `service/tools/__init__.py` | 统一导出和便捷函数 |

#### FLAC 多策略封面提取

`FLACExtractor` 按优先级尝试三种策略：

1. **策略 1**: FLAC 原生 PICTURE 块 (`audio.pictures`)
   - 标准 FLAC 元数据块，直接访问 `audio.pictures` 列表

2. **策略 2**: Vorbis 注释 `METADATA_BLOCK_PICTURE`
   - base64 编码的 FLAC Picture 结构
   - 解码后使用 mutagen 的 `Picture` 类解析

3. **策略 3**: 旧版 `COVERART` 标签
   - base64 编码的原始图片数据
   - 自动检测 MIME 类型

#### 诊断工具

新增 `MetadataDiagnostic` 类支持诊断：

```python
from service.tools.diagnostic import MetadataDiagnostic

diag = MetadataDiagnostic()

# 分析单个文件
report = diag.analyze_file('path/to/audio.flac')
print(report.to_summary())

# 分析目录（查找无封面文件）
reports, summary = diag.analyze_directory('/path/to/music')
print(f"无封面文件: {summary.files_without_cover_art}/{summary.total_files}")
```

#### 向后兼容

`metadata.py` 改为 facade，调用 `service.tools` 模块，API 保持不变：

```python
# 原有代码无需修改
from metadata import extract_metadata, SongMetadata

meta = extract_metadata('song.flac')
print(f'Title: {meta.title}')
print(f'Album art: {len(meta.album_art) if meta.album_art else 0} bytes')
```

### 验证测试

```bash
# 测试诊断功能
python -c "
from service.tools import diagnose_file
import json
result = diagnose_file('path/to/audio.flac')
print(json.dumps(result, indent=2, default=str))
"

# 测试封面提取
python -c "
from service.tools import extract_metadata
result = extract_metadata('path/to/audio.flac')
print(f'Success: {result.success}')
print(f'Pictures: {len(result.pictures)}')
if result.pictures:
    print(f'First picture size: {len(result.pictures[0].data)} bytes')
print(f'Errors: {result.errors}')
print(f'Warnings: {result.warnings}')
"

# 测试向后兼容
python -c "
from metadata import extract_metadata, SongMetadata
meta = extract_metadata('path/to/audio.flac')
print(f'Title: {meta.title}')
print(f'Album art: {len(meta.album_art) if meta.album_art else 0} bytes')
"

# 批量诊断目录
python -c "
from service.tools.diagnostic import MetadataDiagnostic
diag = MetadataDiagnostic()
reports = diag.analyze_directory('/path/to/music')
files_without = diag.find_files_without_cover('/path/to/music')
print(f'Files without cover art: {len(files_without)}')
"
```

### 支持格式

| 格式 | 扩展名 | 封面提取方式 |
|------|--------|--------------|
| MP3 | `.mp3` | ID3 APIC 帧 |
| FLAC | `.flac` | PICTURE 块 / METADATA_BLOCK_PICTURE / COVERART |
| M4A/MP4 | `.m4a`, `.mp4`, `.m4b`, `.m4p` | covr 标签 |
| OGG | `.ogg`, `.oga` | METADATA_BLOCK_PICTURE / COVERART |

---

*FLAC 封面提取重构完成时间: 2026-04-20*

---

## 项目结构重组 (2026-04-20)

### 变更概述

对项目进行代码清理和文件结构调整，优化模块组织。

### 删除的文件

| 文件 | 原因 |
|------|------|
| `gui.py` | Tkinter 遗留 GUI，已被 PyQt6 替代 |
| `check_chinese_comments.py` | 开发辅助脚本，非项目功能 |

### 新增目录结构

```
PyPlayer/
├── main.py              # 唯一入口点
├── core/                # 核心业务逻辑 (新增)
│   ├── __init__.py
│   ├── player.py
│   ├── library_manager.py
│   ├── cache_manager.py
│   ├── config.py
│   ├── i18n.py
│   └── metadata.py
├── tui/                 # 终端 UI (新增)
│   ├── __init__.py
│   └── tui.py
├── tests/               # 测试 (新增)
│   ├── __init__.py
│   └── test_player.py
├── service/             # 服务层 (保持不变)
├── presenter/           # MVP 控制层 (保持不变)
├── view/                # PyQt6 视图层 (保持不变)
└── ...
```

### 导入路径更新

所有核心模块的导入路径已更新：

```python
# 旧
from player import AudioPlayer
from library_manager import LibraryManager
from config import SettingsManager
import i18n

# 新
from core.player import AudioPlayer
from core.library_manager import LibraryManager
from core.config import SettingsManager
from core import i18n
```

### 启动命令更新

```bash
# 启动 PyQt GUI (默认)
python main.py

# 启动终端 UI
python main.py --tui

# CLI 模式播放
python main.py song.mp3

# 注意: --tkinter 选项已移除
```

---

*项目结构重组完成时间: 2026-04-20*

---

## 启动时自动加载第一个媒体库播放列表修复 (2026-04-20)

### 问题描述

打开主页时，未自动加载第一个媒体库的播放列表。虽然媒体库列表正确显示，但播放列表区域为空。

### 问题分析

经过调试发现两个问题：

#### 问题 1: LibraryRuntime 初始化参数错误

**文件**: `core/library_manager.py`

**问题**: `LibraryRuntime` 类的 `playback_queue` 字段定义为 `field(init=False)`，表示它不是构造函数参数。但代码中多处错误地传入了 `playback_queue=None` 参数：

```python
# 错误的调用方式
runtime = LibraryRuntime(
    config=lib_config,
    media_files=[],
    playback_queue=None  # 这个参数不应该传入！
)
```

**错误信息**:
```
LibraryRuntime.__init__() got an unexpected keyword argument 'playback_queue'
```

**影响**: `LibraryService.load_library()` 在创建 `LibraryRuntime` 时抛出异常，`library_loaded` 信号未能发出，导致播放列表未加载。

#### 问题 2: 队列服务初始化顺序错误

**文件**: `presenter/main_presenter.py`

**问题**: `_on_library_loaded` 方法中，先调用 `build_from_tracks()` 再调用 `set_current_library()`，导致 `_rebuild_display_entries()` 时 `_current_library_path` 尚未设置。

```python
# 修复前的错误顺序
self._queue.build_from_tracks(tracks)  # 此时 _current_library_path 为空
self._queue.set_current_library(library_path)  # 设置太晚了
```

### 修复内容

#### 1. 移除错误的 playback_queue 参数 (core/library_manager.py)

三处创建 `LibraryRuntime` 的代码，移除 `playback_queue=None` 参数：

**修复前**:
```python
runtime = LibraryRuntime(
    config=lib_config,
    media_files=[],
    playback_queue=None  # 错误：init=False 的字段不应传入
)
```

**修复后**:
```python
runtime = LibraryRuntime(
    config=lib_config,
    media_files=[]
)
# playback_queue 在 __post_init__ 中自动创建
```

**涉及位置**:
- 第 326-329 行: `LibraryRuntimeManager.get_runtime()`
- 第 575-578 行: `LibraryManager.ensure_library_scanned()`
- 第 604 行: `LibraryManager.refresh_library_from_runtime()`

#### 2. 调整队列初始化顺序 (presenter/main_presenter.py)

**修复前**:
```python
# Build queue from tracks
self._queue.build_from_tracks(tracks)
self._queue.set_current_library(library_path)
```

**修复后**:
```python
# Set current library BEFORE building queue so display optimization works
self._queue.set_current_library(library_path)
# Build queue from tracks
self._queue.build_from_tracks(tracks)
```

### 验证测试

```bash
# 测试库加载信号触发
python -c "
from PyQt6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv)

from service.library_service import LibraryService
from service.config_service import ConfigService

library_service = LibraryService()
config_service = ConfigService()

loaded = []
library_service.library_loaded.connect(lambda p, f: loaded.append((p, len(f))))

libraries = config_service.get_libraries()
if libraries:
    library_service.load_library(libraries[0].path, libraries[0].name)

app.processEvents()
print(f'Loaded: {len(loaded)} libraries')
for path, count in loaded:
    print(f'  {path}: {count} files')
"

# 测试完整应用启动
python -c "
from PyQt6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv)

from view.main_window import MainWindow
from service.playback_service import PlaybackService
from service.queue_service import QueueService
from service.library_service import LibraryService
from service.metadata_service import MetadataService
from service.config_service import ConfigService
from presenter.main_presenter import MainPresenter

playback_service = PlaybackService()
queue_service = QueueService()
library_service = LibraryService()
metadata_service = MetadataService()
config_service = ConfigService()

view = MainWindow()
presenter = MainPresenter(
    view=view,
    playback_service=playback_service,
    queue_service=queue_service,
    library_service=library_service,
    metadata_service=metadata_service,
    config_service=config_service
)
presenter.start()

print(f'Queue entries: {len(queue_service.get_display_entries())}')
print(f'Queue is empty: {queue_service.is_empty()}')
print(f'Current library: {presenter._current_library_path}')
"
```

### 技术说明

**LibraryRuntime 正确初始化方式**:

```python
@dataclass
class LibraryRuntime:
    config: Any
    media_files: List[MediaFile] = field(default_factory=list)
    playback_queue: PlaybackQueue = field(init=False)  # init=False 表示不是构造参数

    def __post_init__(self):
        # playback_queue 在这里自动创建
        self.playback_queue = PlaybackQueue(library_id=self.config.path, track_list=[])
```

`field(init=False)` 的含义：该字段不作为 `__init__()` 的参数，而是在 `__post_init__()` 中初始化。这是 dataclass 的标准用法，用于派生字段或需要依赖其他字段的复杂初始化。

---

*启动时自动加载修复完成时间: 2026-04-20*

---

## 播放列表显示优化 (2026-04-20)

### 变更内容

#### 1. 移除类型前缀标记

**问题描述**：播放列表中的条目显示类型前缀标记（`[F]` 文件、`[D]` 文件夹、`[ML]` 媒体库），影响显示简洁性。

**修改文件**：
- `service/queue_service.py` - GUI 显示层前缀移除
- `core/library_manager.py` - TUI 显示层前缀移除

**修改内容**：
| 位置 | 原代码 | 修改后 |
|------|--------|--------|
| `queue_service.py:153` | `f"[D] {folder_node.display_text}"` | `folder_node.display_text` |
| `queue_service.py:166` | `f"{indent}[F] {track.title}"` | `f"{indent}{track.title}"` |
| `queue_service.py:179` | `f"[F] {file_node.display_text}"` | `file_node.display_text` |
| `library_manager.py:874` | `track_indent + "[F] " + file_title` | `track_indent + file_title` |
| `library_manager.py:886` | `"[ML] " + name` | `name` |
| `library_manager.py:890` | `folder_indent + "[D] " + name` | `folder_indent + name` |
| `library_manager.py:913` | `track_indent + "[F] " + file_item.get(...)` | `track_indent + file_item.get(...)` |

#### 2. 按完整路径字典序排序

**问题描述**：播放列表仅按文件名排序，同一目录下的文件可能分散显示。

**修改文件**：`core/library_manager.py`

**修改内容**：
- 第 459 行：移除 `sorted(filenames)`，改为直接遍历
- 第 475 行：新增 `files.sort(key=lambda f: f.path)` 按完整路径排序

**修改前**：
```python
for filename in sorted(filenames):  # 仅按文件名排序
    ...
# 文件按扫描顺序返回，未统一排序
```

**修改后**：
```python
for filename in filenames:  # 先收集，不排序
    ...
# 按完整路径排序
files.sort(key=lambda f: f.path)
```

#### 3. 递归扫描

**说明**：媒体库选中时递归扫描子目录的功能已存在于原有代码中。`LibraryScanner.scan_directory()` 使用 `os.walk()` 遍历所有子目录，无需修改。

### 验证测试

```bash
# 启动应用
python main.py

# 验证项目：
# 1. 播放列表不显示 [F]、[D]、[ML] 前缀
# 2. 子目录下的文件被正确扫描
# 3. 播放列表按完整路径字典序排列
```

---

*播放列表显示优化完成时间: 2026-04-20*

---

## 播放列表相对位置显示 (2026-04-25)

### 变更内容

#### 1. 新增相对位置计算功能

**功能描述**：播放列表中显示每个文件相对于媒体库根目录的位置，用于标识媒体分组。

**修改文件**：
- `service/queue_service.py` - 添加相对位置计算逻辑
- `view/models/playlist_model.py` - 添加 `RelativePositionRole` 角色
- `view/delegates/playlist_delegate.py` - 新建自定义绘制委托
- `view/widgets/playlist_view.py` - 应用自定义委托
- `presenter/main_presenter.py` - 传递 `relative_position` 字段

**实现细节**：

| 文件 | 修改内容 |
|------|----------|
| `queue_service.py:30-39` | `DisplayEntry` 添加 `relative_position` 字段 |
| `queue_service.py:88-125` | 新增 `_calculate_relative_position()` 方法 |
| `queue_service.py:170-232` | `_rebuild_display_entries()` 计算并填充相对位置 |
| `playlist_model.py:22-32` | `DisplayEntry` 添加字段同步 |
| `playlist_model.py:45-50` | 新增 `RelativePositionRole` |
| `playlist_model.py:111-115` | `data()` 方法返回相对位置 |
| `playlist_delegate.py` | 新建，实现自定义绘制 |
| `playlist_view.py:17-18` | 导入并应用委托 |
| `main_presenter.py:395` | 转换时传递 `relative_position` |

#### 2. 相对位置计算逻辑

```python
def _calculate_relative_position(self, file_path: str) -> str:
    """计算文件相对于媒体库根的位置"""
    # 根目录下 → "root"
    # 子目录下 → 相对路径如 "Rock/Albums"
    # 不在媒体库内 → 空字符串
```

#### 3. 自定义绘制委托

**文件**：`view/delegates/playlist_delegate.py`

**绘制逻辑**：
1. 先绘制相对位置（半透明灰色，右侧）
2. 后绘制文件名（正常颜色，左侧）
3. 空间不足时，文件名直接遮盖相对位置（不截断相对位置）

**样式参数**：
- 相对位置颜色：`QColor(136, 136, 136, 160)`（半透明灰色）
- 括号格式：中括号 `[]`，如 `[root]`、`[Rock/Albums]`

### 验证测试

```bash
# 启动应用
python main.py

# 验证项目：
# 1. 选择媒体库，播放列表显示相对位置
# 2. 根目录文件显示 [root]
# 3. 子目录文件显示相对路径如 [Rock/Albums]
# 4. 相对位置为半透明灰色字体
# 5. 文件名过长时，文件名遮盖相对位置
```

---

*播放列表相对位置显示完成时间: 2026-04-25*
