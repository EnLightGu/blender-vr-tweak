# VR Tweak（P9）· Blender VR 网格微调扩展

戴着 PICO 头显，把控制器当成"笔尖"：在 Blender 视口里直接刷选顶点、拖动、平滑、撤销、保存 —— 不必回桌面摸键鼠。

本 README 分两部分：

1. **介绍**：这个插件是什么、怎么用、代码怎么组织（第 1~4 节）；
2. **本机适配研究**：把它跑到这台 Windows 机器（Blender 4.4.3 + SteamVR + PICO 4S 串流）上的可行方案、实测证据、需要动的代码与验收清单（第 5 节起）。

> 文档基于源码通读 + 本机实测（2026-11-21）。凡标注 ✅ 的是本机跑出来的结果，⚠️ 是代码推断或仍需真机确认的项。

---

## 0. 30 秒结论（本机能不能用？）

| 问题 | 结论 |
| --- | --- |
| 插件原本面向什么环境 | Blender **5.2**（清单写死 `blender_version_min = "5.2.0"`），作者在 Linux 上开发；核心是 OpenXR 输入 + bmesh 编辑 |
| 本机装的 Blender | **4.4.3**（便携版 `C:\Users\enlig\TheD\App\blender`） |
| 直接安装行吗 | ❌ 不行：扩展清单要求 5.2.0，4.4.3 会静默拒装（✅ 实测） |
| 代码要重写吗 | ❌ 不用：插件用到的 XR Python API 在 4.4.3 上**一个不缺**，签名与 5.2 官方文档逐一比对一致（✅ 核对 + 实测 register/unregister） |
| 最小改动 | 把清单里的 `blender_version_min` 改成 `4.4.0`，重新打包安装即可（✅ 已完整验证：打包 → 安装 → 启用 → 注册） |
| 还建议顺手修的 | ① ✅ 已修：中文界面下 HUD 材质发光色设置失效（节点名被本地化，实测复现）；② 待修：`_toast` 临时文字对象没排除渲染/选择 |
| 崩溃问题 | ✅ 已定位并修复：4.4.3 上 XR 绘制回调会破坏 `bpy.context`（见 5.5 ⑤），overlay 已改为场景物体，重新安装即可 |
| 本机安装状态 | ✅ 已装入 Blender 4.4.3 并启用（路径与校验见 5.9） |
| 唯一必须真机验证的 | PICO 4S 经 SteamVR 暴露的 OpenXR 交互 profile 能否让摇杆/A/B/X/Y 绑定生效（有 `oculus_touch` 兼容重映射的迹象，见 5.6） |

---

## 更新记录

### 0.0.3（2026-11-21）

- 新增**左手悬浮面板**：快捷方式速查 + 10 个编辑按钮（全选/取消/反选/相连/合并/删除/平滑/撤销/保存/编辑模式），右手柄 aim 射线 + 右扳机点击，左手 `Y` 开关
- 放宽进入 VR 的条件：没选中网格也能进（只读视图），面板「编辑/物体」可随时切换编辑模式
- 面板悬停时右扳机不再触发刷选
- 新增 `mesh.py` 选择/拓扑操作：全选、反选、选择相连、合并顶点、删除顶点

### 0.0.2（2026-11-21）

- 适配 Blender 4.4.3：清单最低版本改为 `4.4.0`（用到的 XR API 与 5.2 文档逐项核对一致）
- **修复崩溃**：XR 绘制回调会破坏 `bpy.context`（4.4.3/Windows），overlay 改为场景物体（见 5.5 ⑤）
- **修复双扳机自转**：控制器姿态是导航后的世界坐标，改为在 base 空间测量（见 5.5 ⑥）
- 新增双扳机旋转 gizmo：旋转中轴线、`旋转 XX°` 文字、方向箭头
- 导航校准：`Invert Stick X` / `Invert Stick Y` / `Invert Two-Hand View`；移动速度默认 1.5 → 0.5 m/s，并按 `base_scale × navigation_scale` 缩放
- 修复中文界面下 HUD 材质发光色设置失效（按节点类型查找 Principled BSDF）
- 输入日志新增 `pinch=` 角度字段，便于排查双手操作
- 新增本 README（含本机 Windows + PICO 4S + SteamVR 适配研究）

### 0.0.1

- 初始版本（P0/P1 原型：XR 会话、刷选、拖动、平滑、撤销、保存）
## 1. 这是什么

`VR Tweak` 是一个 Blender 扩展（extension，Blender 4.2+ 的新式打包格式），在编辑模式下把 VR 控制器变成建模笔：

- **刷选**：右扳机按住，笔尖球体内的顶点 / 边 / 面被选中，可连续累加；
- **拖动**：右握把按住拖动，实时移动选中顶点，松开提交一步撤销；
- **精细移动**：拖动时同时按左扳机，位移 ×0.1；
- **平滑**：右 A 按住，对选中顶点做 Laplacian 平滑；
- **保存**：右 B 单击，异步保存（并给一个震动 + 文字提示）；
- **选择模式**：左 X 单击，在顶点 / 边 / 面之间循环；
- **撤销 / 重做**：左握把单击撤销；面板上也有按钮；
- **移动与转向**：左摇杆平面移动（可切换成升降），右摇杆左右 30° 快速转身；
- **双手捏合**：左右扳机同时按住，有选中就缩放/旋转选中，没有选中就缩放/平移/旋转视野；旋转场景时会显示**旋转中轴线、旋转角度和方向箭头**（角度按"手转了多少度"实时更新，手停后不再自转）；
- **可视化**：控制器 grip 环、笔尖刷子环（颜色随选择模式变化）、选中元素高亮、视野内 HUD 文本（显示预选对象与模式）。
- **悬浮面板**：左手柄前上方一块面板，写着当前快捷方式，并有 10 个编辑按钮（全选/反选/合并/删除/平滑/保存…），右手射线 + 扳机点击，左手 `Y` 开关。

项目信息：

| 项 | 值 |
| --- | --- |
| 扩展名 / ID | `VR Tweak` / `blender_vr_tweak` |
| 版本 | `0.0.3` |
| 声明的最低 Blender | `5.2.0`（见 `blender_manifest.toml`） |
| 许可 | GPL-3.0-or-later |
| 规模 | 8 个文件、约 1700 行 Python |
| 测试 | 无自动化测试；代码里的 P0 输入日志（`%TEMP%\vrtweak-input.log`）就是最初的"测量工具" |

代码注释里保留了 `P0` / `P1` 的阶段痕迹：P0 先解决"能进 VR、能看到笔尖、能把每个按键的真实值记下来"，P1 才加上选择/移动/撤销。作者刻意**不猜手柄映射**，而是先记录、再按实测结果定映射 —— 这也解释了 `actions.py` 为什么把每个按钮、摇杆、握把都建了 action。

---

## 2. 操作映射（按代码实际行为整理）

默认右手为主手（面板 `Hand = Right`），笔尖取 `AIM` 姿态。

| 手柄输入 | 内部 action | 实际行为 | 生效条件 |
| --- | --- | --- | --- |
| 右扳机 `trigger` | `trigger` | 按下第一帧：清空选择 + 拾取最近元素（拾取不到则球形刷选）；按住继续累加 | 编辑模式 |
| 右握把 `squeeze` | `squeeze` | 记录选中顶点基线，拖动并实时更新；松开提交一步撤销 | 有选中 |
| 左扳机（配合拖动） | `trigger`（左手） | 当前拖动位移 ×0.1（精细移动） | 拖动中 |
| 右 A | `a_click` | 按住：每帧对选中顶点平滑 1 次；松开提交撤销 | 有选中 |
| 右 B | `b_click` | 异步保存；有 `.blend` 存原文件，否则写到 `~/Desktop/vr-tweak-autosave.blend` | — |
| 左 X | `x_click` | 顶点 / 边 / 面选择模式循环 + 中文 toast | — |
| 左握把 | `squeeze`（左手） | 撤销一步（插件内撤销栈） | — |
| 左摇杆 | `stick`（左手） | 平面移动，1.5 m/s，死区 0.15；`Vertical Move` 打开时上下=升降 | 非拖动中 |
| 左摇杆按下 | `stick_click` | 切换 水平/垂直 移动模式 | — |
| 右摇杆左右 | `stick`（右手） | 超过 0.65 时转身 `Turn Angle`（默认 30°），带回滞 | — |
| 双扳机 | `trigger` L+R | 捏合：有选中→缩放/旋转选中；无选中→缩放/平移/旋转视野。场景旋转时显示中轴/角度/箭头 | 双手都有笔尖位置 |

### 2.1 悬浮面板（左手）

设计思路：**离散命令交给面板，连续操作留给你手里的感觉**。刷选、拖动、平滑这些需要手感的事仍然用手柄完成；全选、反选、合并、删除这类一次性命令做成面板按钮，不用记更多组合键。

- **位置**：悬浮在左手柄前上方约 14 cm，始终转向你（billboard），跟着左手移动
- **开关**：左手 `Y` 显示 / 隐藏（默认显示）
- **指向**：右手柄的 aim 射线，面板上会画出一条青色激光
- **点击**：射线停在按钮上时按**右扳机**；此时扳机不会再触发刷选（悬停时自动吞掉）
- **反馈**：悬停按钮变青色，`Status` 显示 `panel: <按钮>`

面板上半部分是当前快捷方式速查，下半部分是 10 个按钮：

| 按钮 | 作用 |
| --- | --- |
| 全选 | 选中当前编辑网格的所有元素 |
| 取消选择 | 清空选择 |
| 反选 | 反转当前选择 |
| 选择相连 | 从已选顶点扩展整块连通区域 |
| 合并顶点 | 选中顶点按 0.1 mm 阈值合并（`bmesh.ops.remove_doubles`） |
| 删除顶点 | 删除选中顶点（`bmesh.ops.delete`） |
| 平滑 | 对选中顶点做 2 次拉普拉斯平滑 |
| 撤销 | 插件内撤销一步 |
| 保存 | 异步保存（有 `.blend` 存原文件，否则写桌面副本） |
| 编辑/物体 | 在编辑模式 / 物体模式之间切换 |

### 2.2 为什么以前必须选中物体才能进 VR？

这是**插件实现上的选择，不是 Blender 的要求**。`session.start()` 第一行就是 `mesh.ensure_edit(context)`：它要求存在 active 网格并进入编辑模式，否则抛 `Select a mesh object first`。原因是整个工具只对编辑模式下的 bmesh 工作（刷选、拾取、拖动都基于 `bmesh.from_edit_mesh`），而进 VR 后没有键盘，作者干脆在启动前强制进入。

0.0.3 起放宽了：启动时按「active 网格 → 已选网格 → 场景里唯一的网格」顺序尝试进入编辑；都不满足也照样进 VR（只读视图，面板和导航可用），HUD 会提示「未进入编辑模式」，点面板上的「编辑/物体」即可随时切换。
关键参数（`VRTweakSettings`，存在场景里，随 `.blend` 保存）：

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `hand` | RIGHT | 主手 |
| `tip_source` | AIM | 笔尖来源：`AIM`（aim pose）/ `GRIP`（grip pose）/ `OFFSET`（grip + 偏移） |
| `tip_offset` | (0, 0, -0.055) | grip 空间下的笔尖偏移（米），`OFFSET` 模式用于校准 |
| `brush_radius` | 0.02 m | 刷子半径（也是拾取容差） |
| `brush_multi` | True | 扳机按住时是否持续累加选择 |
| `smooth_strength` | 0.5 | 平滑强度 |
| `vertical_move` | False | 摇杆上下是否改为升降 |
| `move_speed` | 0.5 m/s（0.1–3.0） | 移动速度，会再乘上 Blender 的 `base_scale × navigation_scale` |
| `invert_stick_x` | False | 翻转摇杆左右轴（横移 + 快速转身），方向不对时勾选 |
| `invert_stick_y` | False | 翻转摇杆前后轴 |
| `invert_grab` | False | 翻转双手视图平移/旋转方向 |
| `turn_angle` | 30° | 快速转身角度 |
| `pinch_gain` / `view_pinch_gain` | 2.0 / 0.25 | 双手捏合缩放灵敏度（物体 / 视野） |
| `pinch_invert` | True | 视野捏合方向反转 |

---

## 3. 代码结构

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `__init__.py` | 292 | 扩展入口：属性组 `VRTweakSettings`、5 个 Operator（start / stop / undo / redo / save）、3D 视图侧栏面板「VR Tweak」、注册/注销；并把 `actions.session_pre` 挂到 `bpy.app.handlers.xr_session_start_pre` |
| `actions.py` | 232 | 自建 OpenXR action set（名为 `vrtweak`）：grip/aim pose、trigger、squeeze、stick、stick_click、a/b/x/y、haptic；按 touch / index / vive / simple 四种交互 profile 建绑定；读取封装与调试日志 |
| `session.py` | 715 | 会话状态机：启停 XR、20 Hz 定时器 `tick()`、输入→行为映射、导航、HUD 文本、toast 提示、异步保存、震动、输入日志 |
| `mesh.py` | 582 | 编辑模式网格操作（全部经 bmesh）：顶点/边/面拾取、刷选、清空、选择模式循环、Laplacian 平滑，以及 `Translate` / `Scale` / `Pinch` 三个实时变换器 |
| `undo.py` | 90 | 插件内撤销/重做栈（上限 50 步，存 bmesh 顶点坐标的 before/after） |
| `panel.py` | 293 | 左手悬浮面板：快捷方式文本 + 10 个按钮、billboard、右手 aim 射线拾取与点击派发 |
| `overlay.py` | 333 | 场景物体式 overlay：grip 环、笔尖刷子环、选中元素高亮，以及双扳机旋转时的**中轴线 / 角度文字 / 方向箭头**（不使用 XR 绘制回调，见 5.5 ⑤） |
| `tip.py` | 25 | 笔尖位置：AIM / GRIP / GRIP+offset |
| `blender_manifest.toml` | 9 | 扩展清单 |

五个值得知道的设计决策：

1. **几何写入一律走 bmesh**。编辑模式下直接写 `mesh.vertices` 会被静默丢弃（`mesh.py` 顶部注释记录了这个 P0 结论），所有变换都基于 `bmesh.from_edit_mesh()`。
2. **撤销是插件自己的坐标快照栈**，不是 Blender 全局 undo。原因同上：编辑模式下 `obj.data.copy()` 是过期数据，只能存 bmesh 坐标。代价是手动 Ctrl+Z 与插件栈不同步。
3. **输入用自建 OpenXR action set**，而不是 Blender 内置动作映射，这样才能把"任意按钮 + 摇杆 + 握把"映射成自定义建模行为。action set 必须在 XR 会话**开始前**建好（会话运行中创建会让 Blender 的 XR 层崩溃），所以挂在 `xr_session_start_pre` 处理器里。
4. **绘制走 XR draw handler**，辅助环不进场景；唯一的场景对象是 HUD 文本（FONT 曲线，`hide_render` / `hide_select`）。
5. **交互循环是 20 Hz 定时器**（`tick()` 返回 0.05），拾取另外节流到 10 Hz。

数据流（一次 tick）：

```text
OpenXR runtime ──(action 值 / 控制器姿态)──> actions.py
                                              │
                                        session.tick()  20 Hz
        ┌──────────────┬──────────────────┼───────────────┬──────────────┐
        ▼              ▼                  ▼               ▼              ▼
   tip.read()   mesh.pick/brush     Translate/Pinch    undo.push     overlay.draw()
   (笔尖位置)    (选择/拾取)          /Scale 实时变换    (坐标快照)    (XR draw handler)
        │              │                  │               │              │
        └──────────────┴──────────────────┴───────────────┴──────> HUD / toast 文本对象
```

---

## 4. 安装与使用（通用）

插件是「仓库根目录 = 扩展本体」的结构（没有多套一层文件夹），所以可以直接把仓库根目录当作 `--source-dir` 打包：

```bash
blender --command extension build --source-dir <仓库根目录> --output-dir <输出目录>
```

产物是 `blender_vr_tweak-0.0.3.zip`（约 24 KB，只含 9 个文件，自动排除 `.git`、`.gitignore`、`dist/`、`README.md`）。

安装（二选一）：

- **图形界面**：`Preferences → Get Extensions → 右上角下拉 → Install from Disk…`，选中 zip，勾选启用；
- **命令行**：
  ```bash
  blender --command extension install-file -r user_default -e blender_vr_tweak-0.0.3.zip
  ```

安装后模块名为 `bl_ext.user_default.blender_vr_tweak`。

使用流程：

1. 选中一个网格物体（可多选），按 `Tab` 进入**编辑模式**；
2. 3D 视图侧栏（`N` 面板）→「VR Tweak」标签 → **开始 VR 微调**；
3. XR 会话启动后，头显里会出现 grip 环、笔尖刷子环和 HUD；
4. 按第 2 节的操作表使用；面板上的 `Status` 会显示当前状态；
5. **停止 VR** 会退出会话、清理 overlay / HUD，并回到物体模式。

日志（排错主要看这两个）：

- `%TEMP%\vrtweak-input.log`：每 0.25 s 写左右手两行（grip/tip 位置、trigger、squeeze、摇杆、选中数、是否拖动中）；
- `%TEMP%\vrtweak-actions.log`：action set 创建全过程（`ensure OK` 才是成功；`action_create FAIL` / `binding FAIL` 会记录失败项）。

> Linux 上（作者原环境）注意：默认 OpenXR runtime 要指到你的运行时（SteamVR / Monado / WiVRn），PICO 串流一般走 WiVRn；HUD 字体会优先找 `/usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc`。

---

## 5. 本机（Windows）适配研究

### 5.1 本机环境实测

| 项 | 实测值 |
| --- | --- |
| 系统 | Windows 11 家庭中文版 `10.0.26300` |
| CPU / 内存 | Intel Core Ultra X7 358H（16 核）/ 31.5 GB |
| GPU | **Intel Arc B390**（核显，驱动 `32.0.101.8359`） |
| 额外显示适配器 | `OrayIddDriver Device`、`RemoteControl Virtual Display`（远程控制软件的虚拟显示器） |
| Blender | **4.4.3**（便携版，`C:\Users\enlig\TheD\App\blender\blender.exe`，构建 `802179c51ccc`） |
| Blender 界面语言 | `zh_HANS`，且「翻译新建数据名」开启 |
| Blender GPU 后端 | OpenGL |
| OpenXR 当前运行时 | **SteamVR**：`HKLM\SOFTWARE\Khronos\OpenXR\1\ActiveRuntime = ...\SteamVR\steamxr_win64.json`（指向 `bin\vrclient_x64.dll`） |
| SteamVR | `C:\Users\enlig\TheD\App\Steam\steamapps\common\SteamVR`，构建 2026-10-17，上次运行 2026-11-10 |
| 头显 | SteamVR 记录 `LastKnown.HMDModel = PICO 4S`，`ActualHMDDriver = pico` |
| 串流 | PICO Connect **10.6.6**（`D:\APP\Pico\PICO Connect`），在 SteamVR 里注册了外部驱动 `openvr_driver`（driver 名 `pico`） |
| 串流参数 | PICO Connect 设为 `sd` 分辨率、HEVC、60 Mbps、90 Hz 关闭（即 72 Hz）、ASW 关、手部追踪开 |
| SteamVR 性能自评 | `gpuSpeedHorsepower = 342`，自动把渲染分辨率比例压到 **0.58** |
| 已有的其它扩展 | `mmd_tools`、`looptools`、`cloudrig`、`VMC Link`、`VRM Addon`（VRM/VMC 工作流在用） |

自查命令：

```powershell
Get-ItemProperty 'HKLM:\SOFTWARE\Khronos\OpenXR\1' | Select-Object ActiveRuntime
Get-Process | Where-Object { $_.ProcessName -match 'PICO|vrserver|vrcompositor|vrmonitor' }
Get-Content 'C:\Users\enlig\TheD\App\Steam\config\steamvr.vrsettings'   # LastKnown 里有 HMD 型号
```

### 5.2 兼容性核对：只差一个版本门槛

插件用到的每一个 XR API，我都在本机 4.4.3 上枚举过（`bpy.types.*.bl_rna`），并与 `docs.blender.org` 的 5.2 文档逐个比对：

| 插件用法 | 4.4.3 | 与 5.2 文档 |
| --- | --- | --- |
| `bpy.types.XrSessionState.is_running(context)` | 有 | 签名一致 |
| `state.actionmaps.new(...)` | 有 | 一致 |
| `state.action_set_create(context, map)` | 有 | 一致 |
| `state.action_create(context, map, item)` | 有 | 一致 |
| `state.action_binding_create(context, map, item, binding)` | 有 | 一致 |
| `state.controller_pose_actions_set(ctx, set, grip, aim)` | 有 | 一致 |
| `state.active_action_set_set(ctx, set)` | 有 | 一致 |
| `state.action_state_get(ctx, set, action, path)` | 有，返回 **2 个 float 的数组**（文档明确"第二个值仅 2D 向量类型有效"），`data[0]` / `data[1]` 可用 | 一致 |
| `state.controller_grip/aim_location_get`、`..._rotation_get` | 有 | 一致 |
| `state.haptic_action_apply(ctx, set, action, path, dur, freq, amp)` | 有 | 一致 |
| `state.viewer_pose_*`、`navigation_location/rotation/scale` | 有 | 一致 |
| `XrActionMapItem.type` 枚举 | `FLOAT / VECTOR2D / POSE / VIBRATION` 全在 | 一致 |
| `XrActionMapBinding.profile` | **字符串**（非枚举），写错不会报错、只会静默不生效 | 一致 |
| `bpy.ops.wm.xr_session_toggle` | 有 | — |
| `SpaceView3D.draw_handler_add(..., "XR", "POST_VIEW")` | 实测注册成功 | — |
| `bpy.app.handlers.xr_session_start_pre` | 有 | — |

另外做了三项实际运行验证（后台模式，不需要头显）：

1. ✅ **注册/注销**：把 8 个文件复制成 `blender_vr_tweak` 包，导入 + `register()` + `unregister()` 全部成功，`Scene.vrtweak` 属性、5 个 operator、面板、`xr_session_start_pre` 处理器都正常挂上；
2. ✅ **几何/撤销/平滑/HUD 冒烟测试**：造一个立方体进编辑模式，`capture_selection` / `Translate.begin/apply` / `push_translate` / `undo` / `redo` / `smooth_selection` / `cycle_select_mode` / `brush_select` / `Scale` / `Pinch` / `_ensure_hud` / `_update_hud` 全部通过，HUD 字体成功加载为 `Microsoft YaHei Regular`；
3. ✅ **打包 → 安装 → 启用**链路：原清单（5.2.0）装进 4.4.3 会被拒（命令行返回 0 但扩展没有落地，提示 `Package should have been installed but not found`）；把 `blender_version_min` 改成 `4.4.0` 重新打包后，安装 + 启用 + 注册全部成功（用 `BLENDER_USER_RESOURCES` 指向临时目录做的隔离验证，没有污染本机配置）。

**结论：代码本身不需要为 4.4.3 改写，唯一阻断项是扩展清单的版本门槛。**

### 5.3 方案对比

| 方案 | 做法 | 工作量 | 风险 | 建议 |
| --- | --- | --- | --- | --- |
| **A. 留在 Blender 4.4.3** | 改清单最低版本 → 重新打包安装 | 5 分钟 | 低（API 已核对/实测） | ✅ 首选 |
| **B. 升级到 Blender 5.2** | 装 5.2，清单不动 | 下载安装 + 迁移配置 | 中：便携版扩展/插件要重装，5.x 对显卡驱动更挑，且本机当前配置未验证 | 以后想跟作者环境完全一致再升 |
| C. 丢进 `scripts/addons` 当旧式插件 | 补 `bl_info` 后放用户插件目录 | 中 | 高：插件没有 `bl_info`，4.2+ 也不再推荐旧式插件 | 不推荐 |

> 说明：A 方案让插件跑在 4.4.3 上，但插件**不会**使用任何 4.4 缺失的特性；反过来，同一份代码在 5.2 上也能跑（API 名称/签名一致），所以 A 不是"降级分叉"，只是放宽了安装门槛。

### 5.4 方案 A 的具体步骤

```powershell
$blender = 'C:\Users\enlig\TheD\App\blender\blender.exe'
$repo    = 'C:\Users\enlig\Desktop\AIwork\C1-代码库工程\P9-VRBlender'
$stage   = Join-Path $env:TEMP 'vr-tweak-build\blender_vr_tweak'
$out     = Join-Path $env:TEMP 'vr-tweak-build\out'

New-Item -ItemType Directory -Force $stage, $out | Out-Null
Copy-Item "$repo\*.py", "$repo\blender_manifest.toml" $stage -Force
```

> 本仓库的 `blender_manifest.toml` 已经改成 `4.4.0` 了；只有当你拿到的是原始 5.2 版本时，才需要做下面这步。

把 `$stage\blender_manifest.toml` 里的

```toml
blender_version_min = "5.2.0"
```

改成

```toml
blender_version_min = "4.4.0"
```

然后打包并安装：

```powershell
& $blender --command extension validate $stage        # 可选：先校验清单
& $blender --command extension build --source-dir $stage --output-dir $out
& $blender --command extension install-file -r user_default -e "$out\blender_vr_tweak-0.0.3.zip"
```

也可以走图形界面：`Preferences → Get Extensions → 下拉 → Install from Disk…` 选 zip，勾选启用。

> ⚠️ **BOM 坑（实测踩过）**：用 Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 改 TOML 会写入 BOM，Blender 直接报
> `FATAL_ERROR: Error parsing TOML ... Invalid statement (at line 1, column 1)`。
> 用编辑器另存为「UTF-8 无 BOM」，或者：
> ```powershell
> $text = (Get-Content $path -Raw) -replace '5\.2\.0', '4.4.0'
> [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
> ```

**推荐开发方式**：安装后扩展会被复制到
`%APPDATA%\Blender Foundation\Blender\4.4\extensions\user_default\blender_vr_tweak\`，
直接改那里的 `.py`，然后在 Blender 里 `F3 → Reload Scripts`（或重启）即可迭代，改稳定了再回到仓库同步。

### 5.5 本机已确认的 6 个问题与限制（含补丁）

#### ① 中文界面下 HUD 材质"不发光"（✅ 已实测复现并修复）

`session.py`：

```python
bsdf = mat.node_tree.nodes.get("Principled BSDF")   # ← 中文界面下节点名是「原理化 BSDF」
```

本机 Blender 是 `zh_HANS` 且开启了"翻译新建数据名"，所以新建材质里的节点实际名为 `原理化 BSDF`，`get("Principled BSDF")` 返回 `None`，于是 `Base Color` / `Emission Color` / `Emission Strength` 全都没设置 —— HUD 文字用默认灰材质、不发光，暗场景里发灰。

改为按节点类型查找（与语言无关）：

```python
bsdf = next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
if bsdf:
    bsdf.inputs["Base Color"].default_value = tint
    bsdf.inputs["Emission Color"].default_value = tint      # 输入标识符不随界面翻译，安全
    bsdf.inputs["Emission Strength"].default_value = 2.0
```

（顺带确认：`inputs["Emission Color"]`、`inputs["Base Color"]` 这些 **socket 标识符不翻译**，本机实测存在，没问题。）

> 本仓库的 `session.py` 已按上面的写法修好，原代码保留在此仅作对照。

#### ② `_toast()` 生成的文字对象会进渲染、能被选中（代码推断，建议修）

`session.py` 的 `_toast()` 创建 FONT 对象后只设了位置，没有 `hide_render` / `hide_select`（HUD 对象是设了的）。它 2 秒后自动删除，但期间可能出现：视口里点到它、渲染时被拍进去。建议照 HUD 的写法补两行：

```python
obj.hide_select = True
obj.hide_render = True
```

> 顺带说明：`_toast` 里的中文**不需要**额外设字体。本机实测 Blender 4.4.3 自带 `Noto Sans CJK Regular.woff2` 回退字体，中文"保存"能正常出字形（与显式加载微软雅黑生成的网格顶点数几乎相同）。

#### ③ PICO 控制器 profile 可能对不上（⚠️ 需真机验证，见 5.6）

`actions.py` 只声明了 `oculus/touch`、`valve/index`、`htc/vive`、`khr/simple` 四种 profile，且 A/B/X/Y、摇杆按下**只绑给 `touch`**。PICO 4S 的控制器是 `bytedance` 系的输入，经 SteamVR 暴露成什么 profile 需要实测。见 5.6 的分析与排查方法。

#### ④ 性能与画面（本机硬件限制，不是 bug）

- GPU 是 **Intel Arc B390 核显**，SteamVR 已经把渲染分辨率自动压到 0.58、PICO Connect 串流用的是最低档 `sd` + 72 Hz。也就是说当前"能跑但糊"；
- Blender XR 要渲染双眼，核显上 EEVEE 实时合成会很吃紧：建议 VR 里用 **Solid / Workbench 视口着色**，别在 VR 会话中开 EEVEE/Cycles；
- `mesh.pick_element` / `brush_select` 是**全量遍历**网格（拾取 10 Hz、刷选 20 Hz），顶点数大时 CPU 端会先卡。建议编辑对象控制在**几万顶点**以内；
- 机器上有 `OrayIddDriver Device` / `RemoteControl Virtual Display` 两个虚拟显示器（远程控制软件），PICO Connect 的硬件自检已经把它误当成显卡并报 `unknown`。**启动 VR 前建议关掉远程控制软件/虚拟显示器**，避免合成器抢 GPU。

#### ⑤ XR 绘制回调会让 Blender 直接崩溃（✅ 已复现并修复，本次最严重的问题）

本机 4.4.3 上，只要注册并触发了 `SpaceView3D.draw_handler_add(..., "XR", "POST_VIEW")` 的 Python 回调，Blender 的全局 `bpy.context` 就会指向一个失效的绘制上下文。后果：

- 回调**内部**访问 `bpy.context.window_manager` → 当场 EXCEPTION_ACCESS_VIOLATION（用户第一次点"开始 VR"崩的就是这个）；
- 即使回调本身完全不碰 context，**下一个定时器**里访问 `bpy.context.window_manager` 也会崩（修复第一处后暴露出来的第二次崩溃）。

崩溃特征：`EXCEPTION_ACCESS_VIOLATION`、`Parameters[0]=0 / Parameters[1]=8`、栈顶 `rna_Context_manager_get → Context_window_manager_get → RNA_property_pointer_get → pyrna_struct_getattro`，外层是 `wm_xr_draw_view → GHOST_XrSession::draw`（第一次）或 `py_timer_execute → XrSessionState_is_running_call`（第二次）。源码可以对上：`rna_XrSessionState_is_running()` 的实现是 `return WM_xr_session_exists(&wm->xr);`，**对 `CTX_wm_manager()` 没有判空**。

最小复现（`blender --factory-startup`，与本插件无关）：启动 XR → 注册一个空的 `def draw(): pass` XR 绘制回调 → 定时器里读 `bpy.context.window_manager` → 崩。反过来，**不注册** XR 绘制回调时，同样的定时器跑 8~10 秒完全正常。另外，"等会话完全启动后再注册"也不可靠：本机测试里这样不再崩溃，但很可能是因为 XR 的绘制回调在会话启动时就被收集、晚注册不再生效（等于没有 overlay）——这一点没有继续深究，直接放弃该方案。

**修复方式**：overlay 不再用 XR 绘制回调，改成**场景物体**——3 个曲线环（grip 环 / 刷子环 / 笔尖点，`bevel_depth` 做线宽）＋ 2 个网格（选中边、选中面），全部 `hide_select` / `hide_render` / `show_in_front`，每个 tick 更新几何。这样 `bpy.context` 全程有效，`tick`、HUD、保存、撤销都恢复正常。代价：overlay 是真实物体（VR 会话中保存 `.blend` 会被一起存进去，和 HUD 一样），且没有屏幕空间恒定线宽。

#### ⑥ 双扳机旋转：停手后场景还在自转（✅ 已复现并修复）

现象：双手捏合旋转场景，手停下来后场景继续转。

根因是**反馈环**。Blender 源码 `wm_xr_session_controller_pose_calc()` 里控制器姿态按
`nav_mat @ base_mat @ raw_pose` 计算，所以 `controller_grip_location_get()` / `aim_location_get()`
返回的已经是**经过导航变换的世界坐标**。插件原来在世界坐标里测量两只手柄的连线方向：

- 导航一转 → 手柄连线跟着转 → 下一帧测到更大的角度 → 再叠加一次旋转 → 正反馈，手停下也继续转；
- 平移同理（`delta = mid - start_mid` 也会随导航漂移），只是没有旋转那么明显。

修复：把当前手柄姿态换算回 **base 空间**再测量（`base = nav_rot⁻¹ · (world - nav_loc) / nav_scale`），
在 base 空间算出双手旋转后再写回导航：
`nav_rot_new = nav_rot_start · R_base⁻¹`、`nav_loc_new = viewer_start - s · (nav_rot_new · (p_viewer + Δ_base))`。

验证：在真实 XR 会话里伪造双手（世界坐标随导航变化），手转到 40° 后停住，6 s→12 s 四个采样
`nav_rot` 全程 `40.00°`、`pinch` 角度 `39.99996°`，**零漂移**；纯数学仿真里手停下后再跑 20 步，
导航旋转漂移 `0.000000 rad`。

**旋转 gizmo**：旋转场景时在中点沿旋转轴画轴线（总长 0.38 m）、一段 12°–160° 的扫掠弧 + 箭头，
并在旁边显示 `旋转 40°` 文字；三者都是场景物体，随会话启动创建、停止时清理。
### 5.6 输入链路（本机）与 profile 风险详解

本机的 XR 链路是：

```text
Blender 4.4.3 ──OpenXR──> SteamVR（ActiveRuntime，vrclient_x64.dll）
                              │
                              └── external driver: D:\APP\Pico\PICO Connect\openvr_driver（driver 名 "pico"）
                                        │
                                        └── PICO Connect 串流 ──> PICO 4S
```

也就是说：**Blender 看到的从来不是 PICO 的驱动，而是 SteamVR 的 OpenXR 实现**。那 SteamVR 会把 PICO 手柄按哪个交互 profile 暴露给应用？我查到的线索：

- `PICO Connect\openvr_driver\resources\input\pico_4s_controller_profile.json` 里声明 `controller_type = "pico_controller"`，同时带
  `"compatibility_mode_controller_type": "oculus_touch"`；
- 同目录 `pico_controller_remapping.json` 里有一张 `oculus_touch → pico_controller` 的重映射表（`simulate_controller_type: true`）；
- SteamVR 的 OpenXR 运行时 `bin\vrclient_x64.dll` 里能同时找到 `oculus/touch_controller`、`valve/index_controller`、`htc/vive_controller`、`khr/simple_controller` 以及 `pico_controller` 这些字符串。
- **实测证据**（2026-11-21 22:28 与 22:32 的 SteamVR `vrserver.txt`）：
  `[Remapping] Completed remapping from controller type: oculus_touch to controller type: pico_controller.`、
  `[Workshop] Successfully auto-remapped binding file from oculus_touch to pico_controller`，
  应用同时加载了 `oculus_touch / khr_simple_controller / vive_controller / knuckles` 四套默认绑定。
  → **SteamVR 确实把 PICO 手柄按 Oculus Touch 兼容模式喂给 OpenXR 应用**，插件现有的 `touch` 绑定（含摇杆/A/B/X/Y）理论上可用，剩下只需真机确认摇杆数值。

**结论（SteamVR 侧已基本确认）**：兼容重映射确实发生了，所以插件的 `touch` 绑定会生效。剩下唯一不确定的是 PICO 手柄的摇杆/按键有没有被重映射到对应 OpenXR 组件路径、数值方向是否正确 —— 必须戴头显实测一次（看 `vrtweak-input.log` 的 `stick=`）。

真机验证方法（30 秒）：

1. 按第 5.4 节装好扩展，进 VR；
2. 看 `%TEMP%\vrtweak-actions.log` 里是否有 `ensure OK`；
3. 看 `%TEMP%\vrtweak-input.log`：`stick=(x, y)` 是否随摇杆变化，`trg` / `sq` 是否随扳机/握把变化；
4. 头显里试：左摇杆能不能移动、右 A 能不能平滑、左 X 能不能切模式。

如果只有扳机有值（摇杆恒为 0）：

- 先试 **PICO Connect 的手柄兼容设置**（若当前版本 UI 提供"模拟 Oculus Touch / 兼容模式"之类的开关）；
- 若 SteamVR 只给 `khr/simple_controller`，可给插件补 PICO 原生 profile（**仅在直接用 PICO 原生 OpenXR 运行时时才生效**）：

  ```python
  # actions.py
  PROFILES = {
      "touch":  ("/interaction_profiles/oculus/touch_controller", "/input/squeeze/value"),
      "pico":   ("/interaction_profiles/bytedance/pico4_controller", "/input/squeeze/value"),  # 路径以 PICO 文档为准
      "index":  ("/interaction_profiles/valve/index_controller", "/input/squeeze/value"),
      "vive":   ("/interaction_profiles/htc/vive_controller", "/input/squeeze/click"),
      "simple": ("/interaction_profiles/khr/simple_controller", "/input/select/click"),
  }
  TOUCH_LIKE = {"touch", "pico"}      # 新增
  # ...
  if name in TOUCH_BUTTONS and key not in TOUCH_LIKE:   # 原来是 key != "touch"
      continue
  ```

- 兜底方案（工作量大）：绕开 OpenXR action map，改用 OpenVR / SteamVR Input 读手柄（PICO 驱动自带 `legacy_bindings_pico_controller.json`，与 PICO 驱动原生兼容），需要额外依赖（如 Python 版 `openvr`）。

### 5.7 验收清单（本机）

| # | 步骤 | 期望 |
| --- | --- | --- |
| 1 | PICO 4S 开机，PICO Connect 连接（优先 USB 3.x 数据线；Wi-Fi 建议 6/5 GHz） | PICO Connect 窗口显示已连接 |
| 2 | 启动 SteamVR | 头显里进 SteamVR 大厅，设备显示 PICO 4S |
| 3 | 打开 Blender 4.4.3，载入要在 VR 里编辑的 `.blend` | 3D 视图正常（OpenGL 后端） |
| 4 | 选中网格 → `Tab` 编辑模式 → `N` →「VR Tweak」→ 开始 VR 微调 | 进入 VR 视图；`Status` 从 `waiting for XR session` 变成正常 |
| 5 | 头显里观察 | 能看到 grip 环 + 笔尖刷子环（顶点模式橙色/边绿色/面紫色）+ 选中高亮 + HUD 文本 |
| 6 | 右扳机刷选 | 顶点被选中并高亮；面板 `Selected: N verts` 增长 |
| 7 | 右握把拖动 | 选中顶点跟随手移动；松开后 `Status` 变 `moved`，左握把可撤销 |
| 8 | 右 A 按住 / 左 X 单击 / 右 B 单击 | 平滑生效 / 模式循环 + 中文 toast / 保存成功 + 震动 |
| 9 | 左摇杆移动、右摇杆转身、双扳机捏合 | 视点移动 / 30° 转身 / 缩放或视野变化 |
| 10 | 看两个日志 | `vrtweak-actions.log` 有 `ensure OK`；`vrtweak-input.log` 数值随操作变化 |

### 5.8 排错

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `vrtweak.start` 报 `VR Tweak start failed: ...` | SteamVR 未启动 / 头显未连接 / OpenXR runtime 不是 SteamVR | 先启动 SteamVR 并确认头显已识别；再查 `ActiveRuntime` 注册表 |
| 头显里看不到环 | `overlay.add()` 没执行（`session.start` 中途抛错）/ 会话没真正启动 | 看 Blender 系统控制台的 XR 报错；看 `Status` 是否已离开 `waiting for XR session` |
| 环能看到但刷选不动 | 不在编辑模式 / 当前选择模式不对 / 网格太远或笔尖朝向不对 | 确认 `Tab` 编辑模式；试 `tip_source = GRIP`；调大 `brush_radius` |
| 扳机能用、摇杆/ABXY 全无 | 交互 profile 没对上（见 5.6） | 查 `vrtweak-input.log` 的 `stick`；试 PICO 兼容模式或补 profile |
| HUD 文字发灰不亮 | 中文界面下材质设置失效（5.5 ①） | 本仓库已修；若仍发灰，确认安装的是修复后的 `session.py` |
| 拖拽延迟、掉帧 | 核显 + 串流 + 大网格 | 降面数；视口用 Solid；SteamVR 分辨率别上调；PICO Connect 保持 `sd/hd` |
| 移动/转身方向相反 | PICO/SteamVR 把摇杆轴反相（插件本身方向与 Blender 自身 VR 导航一致） | 面板勾 `Invert Stick X` / `Invert Stick Y` 试；转身方向跟 X 轴一起翻 |
| 双手视图旋转/平移方向相反 | 抓取式导航的期望方向不同 | 勾 `Invert Two-Hand View` |
| 双扳机停手后场景还在转 | 世界坐标测量导致导航自反馈（见 5.5 ⑥） | 已修；若仍出现，把带 `pinch=` 字段的 `vrtweak-input.log` 发我 |
| 移动太快/太慢 | 默认 0.5 m/s（原 1.5） | 面板 `Move Speed` 调 0.1–3.0；若 `.blend` 存过旧值需手动改 |
| 存到哪了 | 有 `.blend` 存原文件；新建工程会 `copy` 到 `~/Desktop/vr-tweak-autosave.blend` | 本机即 `C:\Users\enlig\Desktop\vr-tweak-autosave.blend` |
| 左握把撤销"撤过头/撤不到" | 插件撤销栈与 Blender 全局 undo 不同步 | 只用插件内撤销；重大改动前手动保存 |
| 中文 toast 显示正常吗 | 正常（Blender 自带 CJK 回退字体，✅ 实测） | 无需处理 |
| 点"开始 VR"后 Blender 卡住/闪退 | ① XR 绘制回调破坏 `bpy.context`（见 5.5 ⑤，**已修**）；② 会话运行中创建 action set（作者注释） | 确认装的是 overlay 为场景物体的版本（`overlay.py` 里不应再有 `draw_handler_add`）；action set 仍由 `xr_session_start_pre` 处理器创建 |

### 5.9 本机安装记录（已完成）

- 安装位置：`%APPDATA%\Blender Foundation\Blender\4.4\extensions\user_default\blender_vr_tweak\`
- 模块名：`bl_ext.user_default.blender_vr_tweak`，已写入偏好设置并启用
- 校验结果：`ADDONS` 含该模块、`session_pre` 处理器已挂、5 个 operator 可见、`Scene.vrtweak` 存在、中文界面下 HUD 材质发光色已生效（`Emission Color = (1,1,1)`、`Emission Strength = 2.0`）
- 2026-11-21 22:39 更新：overlay 改为场景物体（修复 XR 绘制回调崩溃，见 5.5 ⑤），已重新打包安装
- 修复后本机自动实测（脚本启动 XR 会话，跑 18 秒后自动退出）：`running=True`、`tick` 连续写日志 111 行、`overlay._FRAME` 有 tip/grip 与 8 点/72 线、**无崩溃**（`blender.crash.txt` 未再更新）
- 2026-11-21 22:48 导航校准版：新增 `Invert Stick X` / `Invert Stick Y` / `Invert Two-Hand View` 三个面板开关；`move_speed` 默认 1.5 → 0.5，并按 `base_scale × navigation_scale` 缩放（对齐 Blender 自身 fly 导航的做法）
- 日志观察（用户首次成功会话）：左摇杆用满量程，**右摇杆全程为 0**（可能没推，或右摇杆映射待查）；双扳机峰值 0.53/0.56，未触发双手捏合（阈值 0.55）
- 2026-11-21 23:10 双扳机修复版：控制器姿态改在 base 空间测量，消除"停手后继续自转"；新增旋转中轴/角度/方向箭头 gizmo；输入日志新增 `pinch=角度` 字段；仿真验证 40° 零漂移
- 2026-11-21 23:30 面板版 0.0.3：左手悬浮面板（快捷方式 + 10 个编辑按钮，右手射线点击，左Y 开关）；启动不再强制要求选中网格；离线与真实 XR 会话仿真验证按钮点击（全选：0 → 8 个顶点选中）

改代码后如何更新（扩展目录里是安装时的副本，改仓库不会自动同步）：

```powershell
& $blender --command extension build --source-dir $repo --output-dir $out
& $blender --command extension install-file -r user_default -e "$out\blender_vr_tweak-0.0.3.zip"
```

卸载：`Preferences → Get Extensions` 里找到 VR Tweak 卸载，或直接删掉上面那个目录。

---

## 6. 已知限制

1. 只支持**编辑模式下的网格**；曲线、雕刻模式、多用户不支持。
2. 撤销是插件自己的坐标栈（上限 50 步，只存顶点坐标），**拓扑变化无法回退**（`undo.py` 注释里也说明了后续才用 `bm.to_mesh()` 做拓扑快照）。
3. 拾取与刷选是全量遍历，O(顶点数)，大网格上 20 Hz 循环会掉帧。
4. 双扳机捏合是"缩放 + 平移 + 以手柄连线为轴的旋转"的合力，没有独立的手腕旋转/缩放分离。
5. HUD 与 toast 是场景里的 FONT 对象（不参与渲染的选择与清理逻辑还不算完善，见 5.5 ②）。
6. 触觉反馈依赖运行时；经 SteamVR 的 PICO 4S 上可能收不到。
7. 没有按键映射配置界面，也没有运行时 profile 自动探测；profile 写错时 OpenXR 不报错，只是静默失效。
8. 没有自动化测试；没有 `LICENSE` 文件（清单里声明了 GPL-3.0-or-later）。
9. 面板与提示语是中文硬编码；日志固定写到系统临时目录。
10. 原始清单声明的最低版本是 5.2（作者环境）；本仓库已按第 5 节放宽到 4.4.0，并在 4.4.3 上实测可用。
11. 会话期间插件把 active action set 切成自建的 `vrtweak`，Blender 内置的 VR 交互（默认动作集）是否还能共存，代码里没做处理，需实测。
12. overlay 已改为场景物体（grip 环 / 刷子环 / 选中边面网格）：VR 会话中保存 `.blend` 会把它们和 HUD 一起写进文件；停止 VR 时会删除。
13. 悬浮面板同样是场景物体（26 个对象：背景/边框/标题/速查文本/10 按钮+10 标签/激光），VR 会话中保存会写入文件，停止 VR 时删除。

## 7. 下一步建议（P2+）

- **性能**：用 `mathutils.bvhtree` 做拾取/刷选加速，选中元素批处理缓存；
- **撤销**：支持拓扑快照（`bm.to_mesh()` / `bmesh.ops` 差分）；
- **输入**：profile 自动探测 + 按键映射配置面板；PICO/Index/WMR 各自的最佳实践绑定；
- **交互**：分离的双手缩放/旋转手势、HUD 显示位移与倍率数值、笔尖偏移一键校准流程；
- **测试**：把 `actions.value()` / `pose()` monkeypatch 成假输入，在后台模式跑 `tick()` 状态机；
- **工程**：补 `LICENSE`、加 `.gitignore` 里的 `dist/`、CI 里跑 `blender --command extension validate`。

---

## 附录 A：本机适配的实测输出摘录

打包（原清单，5.2.0）——能打出来，但装不进 4.4.3：

```text
building: blender_vr_tweak-0.0.3.zip
created: "...\blender_vr_tweak-0.0.3.zip", 24435
```

安装（4.4.3，隔离用户目录）：

```text
Package should have been installed but not found: blender_vr_tweak
```

改 `blender_version_min = "4.4.0"` 后重新打包并安装，然后启用：

```text
$ blender --command extension build   → created: blender_vr_tweak-0.0.3.zip
$ blender --command extension install-file -r user_default -e ...zip
$ blender --background --python check.py
ADDONS [... 'bl_ext.user_default.blender_vr_tweak']
ENABLE_OK
XRTWEAK_HANDLERS ['session_pre']
OP True  SCENE_PROP True
VR_SETTINGS RIGHT AIM
PANEL_CATEGORY VR Tweak
```

HUD 材质问题的复现（中文界面）：

```text
mat.node_tree.nodes → [('原理化 BSDF', 'ShaderNodeBsdfPrincipled'), ('材质输出', ...)]
nodes.get("Principled BSDF") → None      # 于是发光色没设置
```

XR 绘制回调崩溃（本机 4.4.3，第一次崩溃的直接原因）：

```text
ExceptionCode : EXCEPTION_ACCESS_VIOLATION
Parameters    : 0x0 / 0x8
Stack: ... cb_region_draw -> pyrna_struct_getattro -> RNA_property_pointer_get
       -> Context_window_manager_get -> rna_Context_manager_get   (crash)
       <- wm_xr_draw_view <- GHOST_XrSession::draw <- wm_xr_session_surface_draw
```

修复第一处后暴露的第二次崩溃（定时器里）：

```text
Stack: ... py_timer_execute -> PyObject_CallObject -> PyEval_EvalFrameDefault
       -> pyrna_func_call -> RNA_function_call -> XrSessionState_is_running_call  (crash)
```

最小复现（`--factory-startup`，无插件）：注册空的 `def draw(): pass` XR 绘制回调后，定时器读 `bpy.context.window_manager` 即崩；
不注册回调时同样的定时器 8~10 秒正常；会话启动后延迟注册则不再崩溃（但很可能回调也不再被执行）。

双扳机旋转端到端仿真（真实 XR 会话 + 伪造双手，转到 40° 后停手）：

```text
[SIM2] HANDS_STOPPED 40.0
[SIM2] s1 status= two-hand grab: view nav_rot=40.00 pinch= 39.99996 gizmo_axis= True text= 旋转 40°
[SIM2] s2 ... s4  nav_rot=40.00（手停住后 4 秒内零漂移）
```

overlay 改为场景物体后的自动验收：

```text
[TEST] XR_START_OK running= True
[TEST] check1 running= True ... tip= True grip= True pts= 8 lines= 72 mode= VERT
[TEST] check2 ... check3 ...
vrtweak-input.log: 111 行（tick 持续运行）
blender.crash.txt: 未再更新（无崩溃）
```

CJK 字形验证（默认字体就有中文）：

```text
latin_default ("AB")  = 117 顶点
cjk_default   ("保存") = 325 顶点
cjk_msyh      ("保存") = 328 顶点
```

## 附录 B：文件清单

```text
P9-VRBlender/
├── __init__.py              # 扩展入口（面板 / operator / 注册）
├── actions.py               # OpenXR action set + 读取封装
├── session.py               # 会话状态机 + 20Hz tick
├── mesh.py                  # bmesh 编辑操作
├── undo.py                  # 插件内撤销栈
├── overlay.py               # XR 绘制
├── tip.py                   # 笔尖位置
├── blender_manifest.toml    # 扩展清单
├── .gitignore
└── README.md                # 本文件
```
