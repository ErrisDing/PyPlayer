# PyPlayer UI 批次 4：播放列表元数据列 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 播放列表显示时长/艺人/专辑三列，元数据按库持久化到既有 JSON 缓存，第二次打开不重新提取。

**Architecture:** 扫描先出文件表，元数据由一个 `LibraryMetadataStore` 记录三态（未取到 / 取到但为空 / 已知），后台 sweep 复用 `MetadataService` 的线程池补齐，按库代号取消、按批写回缓存；补齐的行经队列→模型做**定向更新**，delegate 按固定列网格绘制。

**Tech Stack:** PyQt6（`QAbstractListModel` + 自绘 delegate + `QThreadPool`）、`mutagen`（既有依赖）、`unittest`（无 pytest）。

**Spec:** `docs/superpowers/specs/2026-10-20-ui-batch4-metadata-columns-design.md` —— 计划按它论证，执行者两个都读。

**编号约定：** 本计划的 `Task N` **只在本计划内**有意义，每份计划都从 1 重新计数；spec 用 `§n` 与"判据 n"，两套正交。跨批次引用某个任务时必须写 `B<批>T<号>`（例：仓库注释 `core/theme_qss.py:472` 里的 `Task 10` 指 **B2T10**，不是本批的任何任务）。

**任务顺序即依赖顺序：** 1–3 是数据契约，4 是取数，5–6 是行数据与模型，7 才把前面这些接起来（早期草案把接线放在第 5，自审时发现它引用两个尚未诞生的接口，故后移）。8 画、9 收。

## Global Constraints

- 解释器固定 `D:/PROGRAMMES/miniconda3/envs/dev_313/python.exe`（仓库 `.venv` **无 PyQt6**）。不安装任何包，不新增第三方依赖。
- 测试框架 `unittest`；Qt 测试前置 `QT_QPA_PLATFORM=offscreen`。
- **验收数字一律来自全量**：`cd /d/Codes/Python/PyPlayer && QT_QPA_PLATFORM=offscreen /d/PROGRAMMES/miniconda3/envs/dev_313/python.exe -m unittest discover -s tests -p "test_*.py"`。单模块跑绿不作验收证据。批次 3 收在 `Ran 326 tests, FAILED (failures=1)`；唯一失败是 main 既有的 `test_player.TestHierarchicalPlaylist.test_multiple_libraries_display`，**不要顺手修它**。每任务验收 = 不新增失败。
- 变异/回退检查前先清字节码：`find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`。
- **不得为行状态新增 QSS 规则**：`PlaylistItemDelegate` 覆写 `paint()` 且不咨询 style，`::item` 规则在本仓从不渲染（批次 2、3 各踩过一次）。列与状态一律 delegate 绘制。表头是**普通控件**，它的样式走 `core/theme_qss.py` 既有生成路径，且必须同时过 objectName↔QSS 双向守卫。
- 全仓 `setStyleSheet` 保持**恰好一处**：`view/theme_manager.py`。
- 新文案同时写 `locales/interface/main.{zh_CN,en_US}.properties`，**必须按字节改**：工作区 CRLF、index LF（`* text=auto`），`read_text()`/`write_text()` 会重写全文件行尾并把新块变成 `\r\r\n`。安全做法：`git show HEAD:<path>` 取 blob → `.replace(b'\n', b'\r\n')` → 拼新块 → `write_bytes`；提交前 `git diff --numstat` 必须只有新增行。
- 新键用**按控件命名前缀**（`ctx.*`/`rail.*`/`sidebar.*` 同款），本批用 `col.*`（表头四个列名）与 `meta.*`（`meta.pending`/`meta.unknown` 两个状态记号 —— 它们描述的是单元格的状态，不是某个控件的标签）；**不要**并入退役中的 `menu.*` 块（裁定 R5）。
- patch 自身模块只能用 `f'{__name__}.attr'` 或 `mock.patch.object`（AST 守卫 `SelfReferentialPatchTest`）。`QAction.ActionEvent` 只能惰性两段探测；PyQt6 6.11 上 `Qt.Context.*` 与 `QAction.setShortcutWidget` **不存在**。
- 三态的权威定义（spec §4.1）：缓存条目里 `md` 键**缺失** = 有东西等着取；`md` **存在**（哪怕三项全 `null`）= 已试过。被排除的格式（NCM）归"已试过"，不得伪装成"未取到"。
- `duration <= 0` 一律归一为 `null`（spec §4.2）：提取器今天把"读不到"塌成 `0.0`，缓存里不允许出现 `0.0`。归一只允许出现在一处（Task 3 的 `record`），多处各归一次就有多种"没有"。
- 不新增错误弹窗通道；后台动作的进度沿用批次 2 的"回到发起动作那个图标栏按钮"语义，不新增常驻状态区（可报进度的按钮只有两个，见 Task 7）。
- 每任务一次提交；只 commit，**不 push**；不在 `main` 上直接实现（先开分支 `ui-batch4-metadata`）。
- 派发/自述纪律：不得 `sleep`/轮询/后台任务；不得 `git checkout`/`restore`/`stash`/`reset`/`clean` 还原未提交工作（用 `cp` + `cmp`）；若 harness 拒绝对生产文件做变异，**不得重试或绕道**，如实记为"未经变异取证"。

## Review Focus

spec 暗示但没有任务的测试覆盖、最可能真实咬人的五类输入 —— 每条后面挂到 owning task 的步骤里：

1. **文件在"扫描后、写回前"被删/被改**：期望该条不写进新快照，而不是写进去一份过期元数据。→ Task 7 Step 1。
2. **切库后上一库的 sweep 结果回来**：期望既不写进当前库缓存，也不刷当前列表的行（共享池上串库是本批最贵的脏数据）。→ Task 4 Step 1。
3. **NCM 行**：期望显示"取不到"记号，且永不停在"未取到"（被排除 ≠ 待办）。→ Task 3 Step 1。
4. **名字 + 位置脚注 + 三列一起超宽**：期望名字与位置文本各自省略，数据列不被挤成空、行不溢出。→ Task 8 Step 1。
5. **全知库第二次打开**：期望零次提取、无"未取到"记号（否则持久化等于没生效）。→ Task 5 Step 1。

---

### Task 1: 缓存契约升到 2.0，读侧同时吃 1.0

**Files:**
- Modify: `core/cache_manager.py`（`CachedFile`、`to_dict`/`from_dict`、`CACHE_VERSION`、`load_cache`）
- Test: `tests/test_cache_metadata.py`

**Interfaces:**
- Consumes: 既有 `LibraryCacheManager._get_cache_filepath/load_cache/save_cache`
- Produces: `CachedFile.md: Optional[dict] = None`（`None` **表示键缺失**，见下）；`CACHE_VERSION = "2.0"`；`SUPPORTED_CACHE_VERSIONS: frozenset[str] = frozenset({"1.0", "2.0"})`；`md` 的规范形状 `{"artist": Optional[str], "album": Optional[str], "duration": Optional[float]}`

三态在 JSON 里必须**用键的在场与否**表达，不用值表达：`md` 缺失 ↔ pending。因此 `CachedFile.md` 用 `None` 表示"没有这个键"，`to_dict` 在 `md is None` 时**不输出该键**；`from_dict` 在键缺失时给 `None`，键存在但值为 `null` 时给三项全 `None` 的 dict（"取过、啥也没有"）。1.0 文件的所有条目按 `md=None` 载入。

- [ ] **Step 1: 写失败的测试**

`tests/test_cache_metadata.py`（纯数据，不需 Qt）：
- `test_round_trip_preserves_md_and_absence`：一条带 `md={"artist":"B","album":"M","duration":227.0}`、一条 `md=None`；写盘再读回，前者等值、后者仍是"键缺失"（断言磁盘 JSON 里**没有** `"md"` 键，而不是断言它等于 `null`）。
- `test_explicit_md_with_all_nulls_is_present_and_distinct_from_absent`：`md={"artist":None,"album":None,"duration":None}` 读回后与 `None` **不相等**，且 JSON 里有 `"md"` 键。
- `test_version_one_zero_cache_still_loads_as_pending`：手写一份 `version: "1.0"` 的 JSON，断言 `load_cache` 返回条目、文件表不空、每条 `md is None`。
- `test_wrong_version_is_still_rejected`：`version: "3.0"` 判为不可用（别把兼容窗口开成无限）。
- `test_saving_a_one_zero_library_writes_two_zero`：1.0 载入→save→重读，`version == "2.0"`。

非正时长归一成 `null`（spec §4.2）**不在本任务测**：`md` 是自由 dict，真正的写入闸门在 Task 3 的 `record`，那条钉子挂在 Task 3 Step 1（避免同一个规则在本计划里有两处各测一半）。

Run: `QT_QPA_PLATFORM=offscreen /d/PROGRAMMES/miniconda3/envs/dev_313/python.exe -m unittest tests.test_cache_metadata -v` → Expected: FAIL（`md` 键不认识 / 1.0 被拒）。

- [ ] **Step 2: 实现**

按 Interfaces 改四处；`load_cache` 的版本判断从 `!= CACHE_VERSION` 换成 `not in SUPPORTED_CACHE_VERSIONS`。**不改** `is_cache_fresh` 的根目录 mtime 逻辑（文件表判据，spec §4.6 明确本批不动）。

- [ ] **Step 3: 运行确认通过** → Expected: PASS（5 tests）。
- [ ] **Step 4: 全量确认不新增失败**（基线 326/1）。
- [ ] **Step 5: 变异取证**：把 `to_dict` 改成永远输出 `"md": None`，断言 `test_round_trip_preserves_md_and_absence` 红（这是把两态塌成一态的最小变异）。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `git add core/cache_manager.py tests/test_cache_metadata.py` → `feat(cache): 条目加 md 三态，版本升 2.0 且读侧兼容 1.0`

---

### Task 2: 提取层不再替展示层编"未知"

**Files:**
- Modify: `core/metadata.py`（`:55-56` 的英文兜底、`duration` 归一）
- Test: `tests/test_metadata_fallbacks.py`

**Interfaces:**
- Consumes: `service.tools.ExtractionResult`（既有字段 `title/artist/album/duration/album_art`；`duration` 的类型以文件为准，实现前必读）
- Produces: `SongMetadata.artist/album: Optional[str]`（没有就是 `None`）、`SongMetadata.duration: Optional[float]`（`<= 0` 归 `None`）、函数 `normalize_duration(value: float) -> Optional[float]`（Task 3 的 `record` 是唯一复用点，别在多处各归一次）

实测锚点：英文兜底在 [core/metadata.py:55-56](file:///D:/Codes/Python/PyPlayer/core/metadata.py#L55)，`SongMetadata` 在 [同文件:17](file:///D:/Codes/Python/PyPlayer/core/metadata.py#L17)。

`title` 的 `Path(filepath).stem` 兜底**保留**（那是可用的显示值，不是编造的"未知"）。本任务只消灭"编造的属性值"和 `0.0` 歧义。改 `core/metadata.py` 后必须全量跑一次：`NowPlayingStrip` 与 `player.py` 有既有消费方，若某处依赖 `"Unknown Artist"` 字符串，按展示层决定（记进报告，不许偷偷回退成英文字面量）。

- [ ] **Step 1: 写失败的测试** —— `artist`/`album` 缺失→`None`（不是 `"Unknown Artist"`/`"Unknown Album"`）；`duration` 为 `0.0`/负数/`None` 三种输入→都归 `None`；`227.0`→原值；断言 `core/metadata.py` 源码里不再出现 `Unknown ` 字面量（源码扫描沿用批次 1 既有形状）。
- [ ] **Step 2: 运行确认失败**（当前实现返回英文字面量与 0.0）。
- [ ] **Step 3: 实现** 按 Interfaces。
- [ ] **Step 4: 全量确认不新增失败**，并**逐条报告** `NowPlayingStrip`/播放路径上任何受影响的断言改动。
- [ ] **Step 5: 变异取证**：把 `normalize_duration` 的 `<= 0` 改成 `< 0`，`duration=0.0` 那条必须红。
- [ ] **Step 6: Commit** `feat(metadata): 缺失标签返回 None，时长非正值归一为未知`

---

### Task 3: `LibraryMetadataStore` —— 三态与失效的归属

**Files:**
- Create: `service/metadata_store.py`
- Test: `tests/test_metadata_store.py`

**Interfaces:**
- Consumes: Task 1 的 `CachedFile.md`；Task 2 的 `normalize_duration`；`MediaFile.size_bytes/modified_time/path`（实测 [core/library_manager.py:209-210](file:///D:/Codes/Python/PyPlayer/core/library_manager.py#L209)）
- Produces:
  - `RowMetadata(artist: Optional[str], album: Optional[str], duration: Optional[float])`
  - `LibraryMetadataStore(excluded_extensions: frozenset[str] = frozenset({'.ncm'}))`
  - `.load_cache_entries(files: list[CachedFile]) -> int`（返回可用条数）
  - `.validate(files: list[MediaFile]) -> list[tuple[str, int, float]]`（**需要提取的 (全路径, size, mtime) 三元组**：pending、指纹变了、被排除但还没记"已试过"的；后两类在返回前先 `record(md=None)`。返三元组而不返路径：Task 4 起 sweep 与 Task 7 写回复核要用**同一个时刻**的指纹，只返路径会逼调用方再 stat 一次）
  - `.record(full_path: str, md: Optional[RowMetadata], size_bytes: int, modified_time: float) -> None`（`md=None` 即"试过了但没有"，仍算已试过；`md` 的 `duration` 在此过 `normalize_duration`，所以非正时长**进不了缓存** —— spec §4.2 的缓存面）
  - `.get(full_path: str) -> Optional[RowMetadata]`（`None` = pending）
  - `.state_of(full_path: str) -> str`（`'pending' | 'unknown' | 'known'`，供视图与测试用；三态字符串是本类的**唯一**对外表达）
  - `.dirty_count() -> int` / `.take_dirty() -> list[tuple[str, dict | None]]`（Task 7 按批写回用；`take_dirty` 顺手清脏标志）

被排除的格式在 `validate` 里**立即 `record(md=None)`**，所以它们从第一次扫描起就是 `unknown`，不会停在 `pending`（Review Focus 3）。

- [ ] **Step 1: 写失败的测试**：三态矩阵（未 load / load 后 `md` 缺失 / record 已知 / record 三项全 `null` / 排除格式）；`size` 变、`mtime` 变、都没变三类对 `validate` 返回值的影响；**`md` 存在但全 `null` 的文件不再出现在 `validate` 返回值里**（spec §8 失效矩阵第四类"提取失败不重试"、判据 6 —— 这条和"排除格式记 unknown"是同一条规则的两侧，都要单独红一次）；`record(RowMetadata(duration=0.0))` 与 `duration=-1` 经 `take_dirty` 落出的 `md['duration']` 是 `None`；`take_dirty` 幂等；同名不同库不共享（两个 store 实例互不污染）。
- [ ] **Step 2: 运行确认失败** → Expected: FAIL（模块不存在）。
- [ ] **Step 3: 实现** 按 Interfaces。数据结构：`dict[full_path, _Entry]`，`_Entry` 持 `md` + 指纹 `(size, mtime)` + `dirty` 标志。
- [ ] **Step 4: 全量确认不新增失败**。
- [ ] **Step 5: 变异取证**（三次，各单变量）：① 删掉"排除格式立即记 `md=None`"→ `state_of('x.ncm') == 'unknown'` 红；② 把"`md` 存在即已试过"改成"仅当有非空值才算已试过"→"全 `null` 不重取"那条红；③ 删掉 `record` 里的 `normalize_duration` → `duration=0.0` 落缓存那条红。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `feat(service): 库元数据仓库，三态与逐文件失效`

---

### Task 4: 后台 sweep —— 复用现有线程池 + 按库代号取消

**Files:**
- Modify: `service/metadata_service.py`
- Test: `tests/test_metadata_sweep.py`

**Interfaces:**
- Consumes: `MetadataService` 既有的 `QThreadPool.globalInstance()` 与 `QRunnable` 任务形状，以及那个**至今无人调用**的 `preload_files()`（实测 [service/metadata_service.py:110](file:///D:/Codes/Python/PyPlayer/service/metadata_service.py#L110)）——本批就是它的落点。**实现前必读该文件**，本计划不假设它的信号名
- Produces: `MetadataService.start_sweep(targets: list[tuple[str, int, float]], on_row: Callable[[str, Optional[RowMetadata], int, float], None]) -> int`（入参直接吃 Task 3 `validate` 的三元组；**返回值是本次 sweep 的代号**，不是入队数）；`MetadataService.current_generation() -> int`；`MetadataService.cancel_sweep() -> int`（自增并返回新代号）

**代号由服务持有，不由调用方传入。** 早期草案让 caller 传 `generation`，自审时判定为缺陷：调用方一旦传了过期值，结果是**静默不回调**，而"上一库的结果被丢弃"这条正确行为会被一个恒假的参数替掉。同理不采用并行两列表（`paths` + `size_mtime`）：错位配对不报错、只是数据串了。

规则：结果回调只在"该任务所属代号 == `current_generation()`"时上抛；过期结果**丢弃且不调用 `on_row`**（Review Focus 2）。并发不新增上限，交给池本身。**不做**逐条写缓存（那是 Task 7）。

- [ ] **Step 1: 写失败的测试**：用假 extractor（注入一个 `extractor` 可调用，默认走真实实现）断言每条都回调、且回调里带的 `size/mtime` 就是入参那一条；`start_sweep` 返回 A 代号 → `cancel_sweep()` → A 的在途结果**不**触达 `on_row`，随后新起一次 sweep 能正常回调；空 `targets` 返回一个代号且不起任务；**假 extractor 对某条抛异常**时该条以 `md=None` 回调、其余条目照常、异常不逃出线程池、不弹窗（spec §6 第一、二条）；**事件循环仍可响应**：起一个含阻塞式假提取（等待标志位）的 sweep，期间一个 `QTimer` 单次触发照样兑现，再放开标志位（spec §8"sweep 期间事件循环仍可响应"）。
- [ ] **Step 2: 运行确认失败** → Expected: FAIL（无 `start_sweep`）。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 全量确认不新增失败**。
- [ ] **Step 5: 变异取证**（三次，各单变量）：① 回调里的代号比较改成恒真 → 切库那条红；② 删掉逐条 `try/except` → 抛异常那条红；③ 把入池执行改成在调用线程里直接循环提取 → "事件循环仍可响应"那条红（这条正是"后台"两字唯一可证伪的地方）。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `feat(service): 元数据后台补齐，按库代号丢弃过期结果`

---

### Task 5: 行数据通路 —— DisplayEntry 携带 + 定向行更新

**Files:**
- Modify: `service/queue_service.py`（`DisplayEntry`、`_rebuild_display_entries`、新增两个方法）
- Test: `tests/test_queue_metadata.py`

**Interfaces:**
- Consumes: Task 3 的 `RowMetadata`
- Produces: `DisplayEntry.artist/album: Optional[str] = None`、`DisplayEntry.duration: Optional[float] = None`、`DisplayEntry.metadata_state: str = 'pending'`；`QueueService.set_metadata(mapping: dict[str, Optional[RowMetadata]]) -> None`（整表换：建表后一次刷，也用于切库时清空）；`QueueService.apply_metadata(full_path: str, md: Optional[RowMetadata], state: str) -> list[int]`（返回被更新的**行号列表**，无此行则 `[]`；同一路径在 folder 队列里可占多行，必须**全部**更新，否则同一首歌一处有一处没有）

**本任务不新增信号。** 早期草案带一个 `display_row_metadata_changed(int, str)`，自审时按批次 3 终审的 R9（`clear_playlist_requested` 就是一个没人接的信号）判定删掉：它的两个参数调用方（presenter）**当场已经知道**，留着只会多一条没有落地站的路由。定向更新走方法返回值：Task 7 拿到 `apply_metadata` 返回的行号，逐行调 Task 6 的视图入口。

**元数据必须活在队列上的一份 `dict[full_path, RowMetadata]` 里，不是只活在 `DisplayEntry` 上。** 实测理由：`_rebuild_display_entries()` 在每次队列结构变化时重新造一批 `DisplayEntry`（调用点 [service/queue_service.py:138,161,167,523](file:///D:/Codes/Python/PyPlayer/service/queue_service.py#L138)），只把值写在旧条目对象上等于"移除一首歌，其余行的三列全部退回 `⋯`"。所以 `set_metadata`/`apply_metadata` 都写那份表，`_rebuild_display_entries` 从那份表填新条目 —— 查表发生在**建表**时而不是**画一行**时，spec §4.9 的"不做第二次查找"照旧成立。

**`Track` 不改**（spec §4.9）：`Track.duration` 的 `0.0` 与"未知"同源，不能当显示依据；元数据只在 `DisplayEntry` 上走。全知库建表后一次 `set_metadata` 完成，不应再触发提取（Review Focus 5）。

- [ ] **Step 1: 写失败的测试**：`set_metadata` 后逐行字段与状态；`apply_metadata` 命中/未命中（路径不存在）各一，folder 队列里同一路径占两行时**两行都返回**；**定向更新过一次之后再 `remove_at_display_index`（触发 `_rebuild_display_entries`），其余行的三列必须还是补齐后的值、状态不是 `pending`** —— 这条是本任务存在的理由，缺了它"移除一首歌，整表退回未取到"就是绿的；断言 `set_metadata({})` 后一切回 `pending`（切库形状）；建表 + `set_metadata` 全知库后，store 的 `validate` 返回空（**零提取**，Review Focus 5）。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 全量确认不新增失败**。
- [ ] **Step 5: 变异取证**（两次，各单变量）：① `apply_metadata` 把 `full_path` 当 `node_idx` 用行号 → folder 队列那条红（批次 3 终审留的同类洞）；② 只改条目、不写那份 path→md 表 → "移除后其余行保住元数据"那条红。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `feat(service): 显示条目携带元数据与三态，支持定向行更新`

---

### Task 6: 模型三个 role 与视图的定向更新入口

**Files:**
- Modify: `view/models/playlist_model.py`
- Modify: `view/widgets/playlist_view.py`、`view/main_window.py`（各一层薄转发，照既有 `set_playlist_entries`→`set_entries`（[view/main_window.py:687-689](file:///D:/Codes/Python/PyPlayer/view/main_window.py#L687)）与 `highlight_current_track`→`set_current_playing`（[同文件:683-685](file:///D:/Codes/Python/PyPlayer/view/main_window.py#L683)）的形状，presenter 只认 MainWindow）
- Test: `tests/test_playlist_metadata_model.py`

**Interfaces:**
- Consumes: Task 5 的 `DisplayEntry` 新字段、Task 3 的三态字符串
- Produces: `PlaylistModel.DurationRole/ArtistRole/AlbumRole/MetadataStateRole`（接在现有 `UserRole + 1..6` 之后，实测 [view/models/playlist_model.py:39-44](file:///D:/Codes/Python/PyPlayer/view/models/playlist_model.py#L39)；`MetadataStateRole` 返 `str`，取值就是 Task 3 `state_of` 的那三个词，不另造枚举）；`PlaylistModel.update_row_metadata(row: int, md: Optional[RowMetadata], state: str) -> None`（只对四个新 role 发 `dataChanged`，**不** `layoutChanged`/`reset`）；`PlaylistView.update_row_metadata(row, md, state) -> None` 与 `MainWindow.update_row_metadata(row, md, state) -> None`（越界行号 no-op）

- [ ] **Step 1: 写失败的测试**：四个 role 各返回值，三态各一行（known / unknown / pending）；`update_row_metadata` 不发 `layoutChanged`、不发 reset（用 `layoutChanged`/`modelReset` 计数器断言 0 次），`dataChanged` 恰好一次且 role 是那四个；调用前后**行集合与选区不变**（`selected_display_indices()` 相同 —— 逐行填色不该动用户的选中）；`PlaylistView.update_row_metadata` 对越界行号是 no-op（sweep 的迟到结果撞上表已变短）。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 全量确认不新增失败**。
- [ ] **Step 5: 变异取证**（两次，各单变量）：① `update_row_metadata` 换成 `beginResetModel/endResetModel` → "不发 reset"那条红（整表 reset 会让选中与滚动抖一下，正是"逐行填充"最容易被做成整表重建的地方）；② 去掉越界保护 → 越界那条红。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `feat(view): 播放列表模型加时长/艺人/专辑三 role 与定向更新入口`

---

### Task 7: 接线 —— 扫描后起 sweep、按批写回、按钮上的进度

**Files:**
- Modify: `presenter/main_presenter.py`
- Modify: `core/library_manager.py:430-450` 附近（缓存写入路径，实现前必读）
- Test: `tests/test_metadata_wiring.py`

**Interfaces:**
- Consumes: Task 3 store、Task 4 `start_sweep`、Task 5 `set_metadata`/`apply_metadata`、Task 6 `MainWindow.update_row_metadata`、既有图标栏进度语义（`ActionRail.set_progress(action_id, running)` 与 `PROGRESSABLE_IDS`）
- Produces: `MainPresenter._start_metadata_sweep(files: list[MediaFile]) -> int`（返回本次代号，供切库/重复扫描时比对）；`MainPresenter._on_metadata_row(full_path, md, size, mtime) -> None`；写回批大小常量 `METADATA_WRITE_BATCH = 25`（**实现前用探针量单文件提取耗时与 JSON 整份写耗时，再定这个数**，探针不入库、数字与依据写进报告）

顺序：扫描→文件表上屏→`store.validate`→起 sweep；每行结果 `record` 后调 `apply_metadata`，再对它返回的每个行号调 `view.update_row_metadata`；累计 `METADATA_WRITE_BATCH` 条或 sweep 收尾时 `take_dirty` 写回一次。**写回前**逐条重比对磁盘 `size/mtime`，不一致即跳过（Review Focus 1）。切库：先 `cancel_sweep()` 再 `set_metadata({})`，顺序反了会把上一库的结果灌进当前库的行。

**进度只在发起动作可报进度时才报**：`PROGRESSABLE_IDS` 实测只有 `('refresh', 'refresh_all')`（[view/widgets/action_rail.py:122](file:///D:/Codes/Python/PyPlayer/view/widgets/action_rail.py#L122)），而 `set_progress` 对一个已知但不可进度的 id 是**抛 `ValueError`**，不是静默忽略（[同文件:269-270](file:///D:/Codes/Python/PyPlayer/view/widgets/action_rail.py#L269)）。所以由「打开文件夹」触发的首次 sweep **不得**调用 `set_progress`（转圈会承诺一个这个按钮不做的动作，且当场崩）；此时"未取到"的 `⋯` 记号本身就是进度，正是 spec §10 风险 4 的对策。由刷新触发的 sweep 照旧起停配平。加宽 `PROGRESSABLE_IDS` 不在本批：那条守卫自己写着"这是 spec 决定，不是改测试"（[tests/test_presenter_status.py:311](file:///D:/Codes/Python/PyPlayer/tests/test_presenter_status.py#L311)），而 spec 没做这个决定。

- [ ] **Step 1: 写失败的测试**：假 extractor 下断言"扫完起 sweep、按批写 `ceil(N/25)` 次而不是 N 次"；构造"扫描后删文件"→断言该条不进写回；**由打开文件夹触发的 sweep 全程不触碰 `set_progress`**（用计数器断言 0 次，而不是断言它"被容忍"），由刷新触发的断言起止配平（复用 `tests/test_presenter_status.py` 那套 `_progressable_action_ids` 形状，patch 用 `f'{__name__}.'`）；**`save_cache` 抛 `OSError`** 时内存结果照常生效、行照样刷新、异常不逃出回调（spec §6 第三条）；**sweep 更新到正在播放那一行时不重建 `NowPlayingStrip`**（对 strip 的填充入口计 0 次；spec §6 第四条：标题不许因补元数据而闪）；**切库先 cancel 再清空**：A 库在途结果回来时既不写 B 的缓存也不刷 B 的行（Review Focus 2 的接线面）。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 全量确认不新增失败**。
- [ ] **Step 5: 变异取证**（四次，各单变量）：① 写回改成每行一次 → 次数断言红（O(n²) 回归的钉子）；② 打开文件夹路径也去 `set_progress` → 0 次那条红；③ sweep 完成后顺手重发一次"正在播放" → strip 计数那条红；④ `record` 后不转发给 `apply_metadata`（只写缓存） → 行不更新那条红。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `feat(presenter): 扫描后补齐元数据并按批写回缓存`

---

### Task 8: delegate 列网格 + 表头（方案 P）

**Files:**
- Modify: `view/delegates/playlist_delegate.py`、`view/widgets/playlist_view.py`
- Modify: `core/theme_qss.py`、`core/theme.py`（列宽 token）
- Create: `view/time_format.py`
- Test: `tests/test_playlist_columns.py`

**Interfaces:**
- Consumes: Task 6 的四个 role、`bottom_panel.format_time`（**提成共用**：移到 `view/time_format.py` 并由 `bottom_panel` 与本任务两处引用，不留两份实现；实测住在 [view/widgets/bottom_panel.py:38](file:///D:/Codes/Python/PyPlayer/view/widgets/bottom_panel.py#L38)）
- Produces: `COLUMN_DURATION_WIDTH = 56`、`COLUMN_TEXT_WIDTH = 120`（放 `core/theme.py` 的几何区，与 `ROW_HEIGHT = 28`（[core/theme.py:206](file:///D:/Codes/Python/PyPlayer/core/theme.py#L206)）同处）；表头 objectName `playlistHeaderRow` + `colName/colDuration/colArtist/colAlbum`

布局（方案 P）：`名称 [位置]` 左对齐占剩余宽度，右侧依次 时长(右对齐)/艺人/专辑。名字先按"名字+位置"整体预留、超长的位置文本**自己**省略（这条决定要写进注释）。今天的位置文本绘制在 [view/delegates/playlist_delegate.py:180-195](file:///D:/Codes/Python/PyPlayer/view/delegates/playlist_delegate.py#L180) —— 它已经占了行右端，方案 P 是把它挪到名字之后、把右端让给三列，不是并存。表头接管原 `#playlistHeader` 那行 QLabel：旧名字要么随规则一并迁移、要么按 `KNOWN_DEAD_SELECTORS` 登记，**不得留未登记残留**（objectName↔QSS 双向守卫）。

- [ ] **Step 1: 写失败的测试**（离屏 `grab()` 像素 + 列边界，不写 item QSS 规则）：三列在两主题下各自落在预期 x 区间；时长右对齐；pending=`⋯`、unknown=`—` 且**两个记号可辨**（各取一个不同底色行做对照）；folder 行只有名字与位置、数据列是空而不是记号（**这条在实现前定死：folder 行画空，不画 `—`**）；Review Focus 4 的超宽组合（长名字 + 长位置 + 长艺人/专辑）下无溢出、无列被挤成 0 宽。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** delegate 与表头；locale 加 `col.name/col.duration/col.artist/col.album` 与 `meta.pending`/`meta.unknown` 两记号（**按字节改两份文件**，`git diff --numstat` 只有新增）。
- [ ] **Step 4: 全量确认不新增失败**，且双向守卫 `test_view_structure.py`/`test_theme_qss.py` 全绿。
- [ ] **Step 5: 变异取证**（两次，各单变量）：① 删掉"先为位置文本预留宽度"→ 超宽那条红；② 把 folder 行的数据列改成画 `—` → folder 那条红。还原用 `cp` + `cmp`。
- [ ] **Step 6: Commit** `feat(view): 播放列表三列与表头（位置文本移到名字之后）`

---

### Task 9: 渲染矩阵补帧、README、收尾核对

**Files:**
- Modify: `tests/tools/render_matrix.py`、`README.md`
- Test: 工具自身

**Interfaces:**
- Consumes: 前八个任务全部产物
- Produces: `--metadata` 帧（满数据 / 一个 pending / 一个 unknown / 一个 folder 行，两张主题），以及"第二次打开零提取"的自检

- [ ] **Step 1: 复核探针**（不入库）：各格式单文件提取耗时、整份 JSON 写回耗时；把数字与 Task 7 选定 `METADATA_WRITE_BATCH` 时的数字并列写进报告，若矛盾则改那个常量并说明是哪一个数字变了。
- [ ] **Step 2: 补帧并逐张目视**，脚本内用 `require` 断言前置条件（帧不许"看起来像"）：列对齐、两记号可辨、表头与列不错位、老 1.0 缓存升级后**不**出现满屏 pending（Review Focus 5 的目视面）。
- [ ] **Step 3: README** 交互节补三列与两记号语义；`需真机核对`一节新增：真机上看列可读性、CJK、以及"大库首扫期间一直显示 `⋯` 是否被接受"；保留 macOS 声明。
- [ ] **Step 4: 全量核对**：`Ran <N> tests` 无新增失败；`setStyleSheet` 恰 1 处；无 item QSS 规则；`grep` 无 `Unknown Artist|Unknown Album` 残留；`menu.*` 键数与消费者数报告（不在本批清理）。
- [ ] **Step 5: Commit** `test(ui): 批次 4 渲染矩阵补元数据列帧与 README 对账`

---

## 实现前必读的既有代码（不假设签名）

`service/metadata_service.py`（线程池与任务形状、`preload_files` 目前无人调用，本批是它的落点）、`core/library_manager.py:430-450`（`create_cache`/`save_cache` 调用点）、`view/delegates/playlist_delegate.py` 现有省略与预留逻辑、`service/queue_service.py:127-236`（建表与 `_rebuild_display_entries` 的全部调用点）、`tests/test_presenter_status.py` 的装配与 `SelfReferentialPatchTest` 守卫形状。

## 自审记录（writing-plans 第 2 遍）

九处，全部改在正文里：`drirty_count` 拼写；`update_row_metadata` 的 `state: int` 与 Task 3/5 的三态字符串不一致；sweep 的 `generation` 由调用方传入（恒假参数会伪装成"丢弃过期结果"）；`validate` 返路径导致调用方二次 stat 且与判定不同时刻；`_rebuild_display_entries` 会重造条目、元数据只挂条目则"移除一首歌整表退回 pending"是绿的；接线任务原本排在队列/模型之前、引用两个尚未诞生的接口；`display_row_metadata_changed` 无落地站（R9）；spec §8 的"事件循环仍可响应"、§6 的"提取抛异常""缓存写失败""正在播放行被更新不闪标题"四条没有 owning task；Task 1 的 `duration=0.0` 用例与 Task 3 的归一重复，删前者。（上一笔提交写作"八处"，是把最后一条并进了正文而没数进去。）
