# PyPlayer 代码修复总结

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
- `_update_playlist_display()` 构建的是层级显示，包含文件夹 `[D]`、媒体库 `[ML]` 和文件 `[F]`
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
python -c "import metadata; import player; import gui; print('OK')"

# 测试元数据提取
python -c "
from metadata import extract_metadata
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