# SPDX-License-Identifier: GPL-3.0-or-later
"""Floating shortcut / tool panel held by the left controller.

The panel is built from ordinary scene objects (text + quads) and updated every
tick: it billboards towards the viewer, and the right controller's aim ray picks
buttons. Pressing the right trigger while a button is hovered runs its action
instead of the brush.

This is deliberately *not* an XR draw-handler overlay: on Blender 4.4.3 (Windows)
Python draw handlers for the "XR" region corrupt ``bpy.context`` (see README 5.5).
"""
import bpy
from mathutils import Matrix, Vector

PANEL_W = 0.34
PANEL_H = 0.44
BUTTON_W = 0.15
BUTTON_H = 0.033
COL_X = (-0.083, 0.083)
ROW_Y0 = 0.015
ROW_STEP = 0.042

_BG_COLOR = (0.02, 0.02, 0.03, 1.0)
_BORDER_COLOR = (0.25, 0.30, 0.38, 1.0)
_TITLE_COLOR = (1.0, 0.95, 0.4, 1.0)
_TEXT_COLOR = (0.85, 0.88, 0.92, 1.0)
_IDLE_COLOR = (0.16, 0.18, 0.22, 1.0)
_HOVER_COLOR = (0.15, 0.65, 0.85, 1.0)
_LASER_COLOR = (0.2, 0.9, 1.0, 1.0)

LEGEND = [
    "右扳机 刷选 · 右握把 拖动",
    "左扳机+拖动 精细 · 右A 平滑",
    "左握把 撤销 · 右B 保存",
    "左X 选择模式 · 摇杆 移动",
    "右摇杆 转身 · 双手 缩放旋转",
    "左Y 显示/隐藏面板",
]

# key, label, column, row
BUTTONS = [
    ("select_all", "全选", 0, 0),
    ("deselect", "取消选择", 1, 0),
    ("invert", "反选", 0, 1),
    ("linked", "选择相连", 1, 1),
    ("merge", "合并顶点", 0, 2),
    ("delete", "删除顶点", 1, 2),
    ("smooth", "平滑", 0, 3),
    ("undo", "撤销", 1, 3),
    ("save", "保存", 0, 4),
    ("editmode", "编辑/物体", 1, 4),
]

_OBJECTS = {"root": None, "laser": None}
_BUTTON_OBJECTS = {}
_ALL_OBJECTS = []
_hover = None
_pressed = False


def _button_xy(col, row):
    return COL_X[col], ROW_Y0 - row * ROW_STEP


def _quad(name, w, h, color, z):
    verts = [(-w / 2, -h / 2, z), (w / 2, -h / 2, z), (w / 2, h / 2, z), (-w / 2, h / 2, z)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    mesh.materials.append(overlay_material(name + "_mat", color))
    return bpy.data.objects.new(name, mesh)


def _text(name, body, size, color, x, y):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    font = overlay_font()
    if font is not None:
        try:
            curve.font = font
        except Exception:  # noqa: BLE001
            pass
    curve.materials.append(overlay_material(name + "_mat", color, 1.0))
    obj = bpy.data.objects.new(name, curve)
    obj.location = (x, y, 0.002)
    return obj


def _line(name, count, bevel, color):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = bevel
    curve.bevel_resolution = 0
    curve.resolution_u = 1
    spline = curve.splines.new("POLY")
    spline.points.add(count - 1)
    curve.materials.append(overlay_material(name + "_mat", color, 1.5))
    return bpy.data.objects.new(name, curve)


def _attach(context, root, obj):
    context.scene.collection.objects.link(obj)
    obj.parent = root
    obj.hide_select = True
    obj.hide_render = True
    obj.show_in_front = True
    obj.hide_viewport = True
    _ALL_OBJECTS.append(obj)
    return obj


def add(context):
    if _OBJECTS["root"] is not None:
        return
    root = bpy.data.objects.new("vrtweak_panel_root", None)
    context.scene.collection.objects.link(root)
    root.hide_render = True
    root.hide_select = True
    root.show_in_front = True
    _OBJECTS["root"] = root
    _ALL_OBJECTS.append(root)

    _attach(context, root, _quad("vrtweak_panel_bg", PANEL_W, PANEL_H, _BG_COLOR, 0.0))
    _attach(context, root, _quad("vrtweak_panel_border", PANEL_W + 0.012, PANEL_H + 0.012, _BORDER_COLOR, -0.001))
    _attach(context, root, _text("vrtweak_panel_title", "VR Tweak  面板", 0.018, _TITLE_COLOR, 0.0, PANEL_H / 2 - 0.033))
    _attach(context, root, _text("vrtweak_panel_legend", "\n".join(LEGEND), 0.0105, _TEXT_COLOR, 0.0, 0.088))

    for key, label, col, row in BUTTONS:
        x, y = _button_xy(col, row)
        quad = _quad("vrtweak_btn_" + key, BUTTON_W, BUTTON_H, _IDLE_COLOR, 0.001)
        quad.location = (x, y, 0.001)
        _attach(context, root, quad)
        txt = _text("vrtweak_btn_" + key + "_label", label, 0.0115, _TEXT_COLOR, x, y)
        _attach(context, root, txt)
        _BUTTON_OBJECTS[key] = quad

    laser = _line("vrtweak_panel_laser", 2, 0.0015, _LASER_COLOR)
    context.scene.collection.objects.link(laser)
    _ALL_OBJECTS.append(laser)
    laser.hide_select = True
    laser.hide_render = True
    laser.show_in_front = True
    laser.hide_viewport = True
    _OBJECTS["laser"] = laser


def _set_visible(visible):
    for obj in _ALL_OBJECTS:
        obj.hide_viewport = not visible
    for obj in _BUTTON_OBJECTS.values():
        obj.hide_viewport = not visible
    laser = _OBJECTS.get("laser")
    if laser is not None:
        laser.hide_viewport = not visible


def _update_colors():
    for key, _label, _col, _row in BUTTONS:
        color = _HOVER_COLOR if key == _hover else _IDLE_COLOR
        overlay_material("vrtweak_btn_" + key + "_mat", color)


def _button_at(point):
    for key, _label, col, row in BUTTONS:
        x, y = _button_xy(col, row)
        if abs(point.x - x) <= BUTTON_W / 2 and abs(point.y - y) <= BUTTON_H / 2:
            return key
    return None


def _set_laser(start, end):
    laser = _OBJECTS.get("laser")
    if laser is None:
        return
    points = laser.data.splines[0].points
    points[0].co = tuple(start) + (1.0,)
    points[1].co = tuple(end) + (1.0,)
    laser.data.update_tag()
    laser.hide_viewport = False


def update(context, viewer, grip_loc, grip_rot, aim_loc, aim_rot, trigger, visible, dispatch):
    """Place the panel, pick a button with the right aim ray, run clicks.

    Returns ``{"hover": bool, "clicked": key|None}``; the caller uses ``hover``
    to swallow the brush trigger on that tick.
    """
    global _hover, _pressed
    result = {"hover": False, "clicked": None}
    root = _OBJECTS.get("root")
    if root is None:
        return result
    if not visible or viewer is None or grip_loc is None:
        _set_visible(False)
        _hover = None
        _pressed = False
        return result

    viewer = Vector(viewer)
    grip = Vector(grip_loc)
    to_viewer = viewer - grip
    if to_viewer.length < 1e-4:
        return result
    to_viewer.normalize()
    position = grip + to_viewer * 0.14 + Vector((0.0, 0.0, 0.06))
    rotation = (viewer - position).to_track_quat("Z", "Y")
    matrix = Matrix.Translation(position) @ rotation.to_matrix().to_4x4()
    root.matrix_world = matrix
    _set_visible(True)

    hit_key = None
    hit_world = None
    if aim_loc is not None and aim_rot is not None:
        inverse = matrix.inverted()
        origin = inverse @ Vector(aim_loc)
        direction = (inverse.to_3x3() @ (aim_rot @ Vector((0.0, 0.0, -1.0)))).normalized()
        if abs(direction.z) > 1e-6:
            distance = -origin.z / direction.z
            if distance > 0.0:
                point = origin + direction * distance
                if abs(point.x) <= PANEL_W / 2 and abs(point.y) <= PANEL_H / 2:
                    hit_key = _button_at(point)
                    hit_world = matrix @ point
        _set_laser(Vector(aim_loc), hit_world if hit_world is not None
                   else Vector(aim_loc) + (aim_rot @ Vector((0.0, 0.0, -1.0))) * 0.35)

    if hit_key != _hover:
        _hover = hit_key
        _update_colors()

    if hit_key is not None and trigger and not _pressed:
        _pressed = True
        action = dispatch.get(hit_key) if dispatch else None
        if action is not None:
            try:
                action(context)
            except Exception:  # noqa: BLE001
                pass
        result["clicked"] = hit_key
    if not trigger:
        _pressed = False
    result["hover"] = hit_key is not None
    return result


def hide():
    global _hover, _pressed
    _set_visible(False)
    _hover = None
    _pressed = False


def remove():
    global _hover, _pressed
    targets = list(_BUTTON_OBJECTS.values()) + list(_ALL_OBJECTS)
    for obj in targets:
        if obj is None:
            continue
        try:
            data = getattr(obj, "data", None)
        except Exception:  # noqa: BLE001
            data = None
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:  # noqa: BLE001
            continue
        try:
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
                elif isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
        except Exception:  # noqa: BLE001
            pass
    _BUTTON_OBJECTS.clear()
    _ALL_OBJECTS.clear()
    for key in list(_OBJECTS.keys()):
        _OBJECTS[key] = None
    _hover = None
    _pressed = False


def overlay_material(*args, **kwargs):
    from . import overlay
    return overlay._material(*args, **kwargs)


def overlay_font():
    from . import overlay
    return overlay._font()
