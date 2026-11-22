# VR Tweak（P9）

在 Blender 里戴着 VR 头显直接改网格：刷选、拖动、平滑、双手缩放旋转，配合贴在左手柄四个侧面的悬浮面板。

- 作者：人和大肥鱼
- 许可：GPL-3.0-or-later
- Blender：4.4+（清单最低版本 4.4.0）

## 安装

```bash
blender --command extension build --source-dir <仓库根目录> --output-dir dist
blender --command extension install-file -r user_default -e dist/blender_vr_tweak-0.0.4.zip
```

或 `Preferences → Get Extensions → Install from Disk…` 选 zip。

## 使用

1. 打开 Blender，3D 视图 → `N` 面板 →「VR Tweak」→「开始 VR 微调」
2. 先开 PICO Connect / SteamVR，头显与手柄连接正常
3. 会话会自动把视点放到原点前 2 m、朝原点

## 手柄操作

| 输入 | 动作 |
| --- | --- |
| 右扳机 | 刷选（按住累加） |
| 右握把 | 拖动选中顶点，松开提交一步撤销 |
| 左扳机 + 拖动 | 精细移动（×0.1） |
| 右 A | 按住平滑选中 |
| 右 B | 保存 |
| 左 X | 顶点/边/面模式循环 |
| 左握把 | 撤销 |
| 左摇杆 | 移动（按下切换垂直移动） |
| 右摇杆左右/上下 | 转身 / 俯仰（绕右手柄为支点） |
| 双手扳机 | 有选中→缩放旋转选中；无选中→缩放旋转平移视野 |
| 左 Y | 显示/隐藏悬浮面板 |

## 悬浮面板

- 四块面板分别贴在左手柄**四个侧面**（+Y / +X / -Y / -X），随手柄移动与旋转
- 面板平面严格贴合侧面（面内缩 4 mm、离面 4 mm）
- 页面"上方向"跟随手柄长轴；四块面板绕长轴分布，`« »` 点击切换页面组合
- 按钮黑色圆角 + 亮橙黄双语文字（8 mm），悬停变蓝并弹出说明框（在按钮上方）
- 右手柄射线指向按钮、扣右扳机触发；射线检测对四块面板都生效

## 常见问题

- **没有手柄模型**：`PICO → PICO Connect → SteamVR` 不提供控制器网格时，Blender 会画球体兜底；本版用方块代理对齐握持姿态（默认隐藏，可在 session.py 中恢复）
- **进 VR 没反应**：确认用面板「开始 VR 微调」启动；旧会话会先关闭再重开
- **方向反了**：面板内提供 Invert Stick X/Y、Invert Two-Hand View
- **日志**：`%TEMP%\vrtweak-input.log`（含 `.hb` 心跳、`.err` 异常、`.toggle` 会话开关记录）

## 更新日志

### 0.0.4

- 悬浮面板改为**四块分别贴在左手柄四个侧面**，面内缩/离面间距统一
- 面板文字改为中英双语、字号加倍（8 mm），标题 10.5 mm
- 页面上下方向跟随手柄长轴（已按实际握持方向对调），四块面板绕长轴排布
- `« »` 只在点击时翻页（修复悬停连翻）
- 悬停说明框改为跟随页面并在按钮上方显示
- 面板材质改为纯自发光哑光（metallic=0, roughness=1, specular=0），消除反光
- 隐藏手柄代理立方体及六面坐标标签
- 修复面板整块不显示/位置错误：`PAGE_Z` 未定义、Matrix+Vector 非法运算、法线被重复旋转、左手系导致文字镜像
- 修复射线检测只命中第一页导致其它页按钮点不到
- 启动时自动把视点放到原点前 2 m、朝原点；已运行会话会先关闭再重开
- 动作集只保留一次创建（避免同名 action 冲突导致会话无法启动）

### 0.0.3

- 初始公开版本：刷选、拖动、平滑、双手变换、手柄位姿与绑定

## 自动化 / 测试

`api.py` 提供选择、编辑、面板按钮、双手旋转数学等接口，可在 Blender 中直接调用：

```python
import importlib
api = importlib.import_module("bl_ext.user_default.blender_vr_tweak.api")
api.enter_edit(); api.select_all(); api.panel_click("smooth")
```

无头自测：`blender --background --factory-startup --python tests/headless_api_test.py`

## 代码结构

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 面板/操作符/属性，注册入口 |
| `actions.py` | OpenXR action set（手柄输入、位姿） |
| `session.py` | 20 Hz 会话循环：选择、拖动、双手、导航、面板派发 |
| `mesh.py` | bmesh 编辑操作（拾取/刷选/平滑/合并/挤出…） |
| `panel.py` | 左手四面悬浮面板（贴面、翻页、射线点击） |
| `overlay.py` | 场景物体 overlay（刷子环、选中高亮、旋转 gizmo） |
| `undo.py` / `tip.py` | 插件内撤销栈 / 笔尖位置 |
| `api.py` | 自动化接口 |
