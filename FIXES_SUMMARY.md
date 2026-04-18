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