# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact four-faced panel mounted on the left controller.

The panel hangs 4.5 cm off the grip, follows the grip orientation (no
billboard), and the four pages sit around the handle like a ring; the page
arrows rotate the ring by 90 degrees. Buttons are small black rounded quads
with white text labels (Blender UI icons are not reachable from scene objects),
and hovering shows a small tooltip attached to the same face.

Scene objects only - an XR draw handler corrupts bpy.context on 4.4.3/Windows
(README 5.5).
"""
import math
import os
import time


import bpy
from mathutils import Matrix, Quaternion, Vector

FACE_W = 0.056
FACE_H = 0.132
BTN_DY = 0.0
BTN_W = 0.054
BTN_H = 0.013
BTN_GAP = 0.002
RADIUS = 0.14
PAGE_Z = 0.0
PANEL_TILT = 0.702
ARROW_W = 0.040
TIP_W = 0.145
TIP_H = 0.052

BG_COLOR = (0.016, 0.017, 0.020, 1.0)
BORDER_COLOR = (0.13, 0.14, 0.16, 1.0)
BTN_IDLE = (0.004, 0.004, 0.006, 1.0)
BTN_HOVER = (0.16, 0.40, 0.72, 1.0)
TEXT_COLOR = (1.0, 0.72, 0.10, 1.0)
TITLE_COLOR = (1.0, 0.82, 0.28, 1.0)
SUBTLE_COLOR = (1.0, 0.62, 0.12, 1.0)
TIP_BG = (0.010, 0.011, 0.013, 1.0)
TIP_BORDER = (0.16, 0.17, 0.19, 1.0)
TIP_NAME = (1.0, 1.0, 1.0, 1.0)
TIP_DESC = (0.72, 0.75, 0.79, 1.0)


EN_SHORT = {
    "select_all": "All", "deselect": "None", "invert": "Inv", "linked": "Linked",
    "mode_vert": "Vert", "mode_edge": "Edge", "mode_face": "Face", "editmode": "Edit",
    "merge": "Merge", "delete": "Del", "smooth": "Smooth", "subdivide": "Subdiv",
    "extrude": "Extrude", "flip_normals": "Flip", "undo": "Undo", "redo": "Redo",
    "reset_view": "Reset", "save": "Save", "hide_panel": "Hide", "help": "Help",
}

EN = {
    "select_all": "Select All", "deselect": "Deselect", "invert": "Invert",
    "linked": "Select Linked", "mode_vert": "Vertex", "mode_edge": "Edge",
    "mode_face": "Face", "editmode": "Edit/Object",
    "merge": "Merge", "delete": "Delete", "smooth": "Smooth",
    "subdivide": "Subdivide", "extrude": "Extrude", "flip_normals": "Flip Normals",
    "undo": "Undo", "redo": "Redo", "reset_view": "Reset View",
    "save": "Save", "hide_panel": "Hide Panel", "help": "Help",
}

LEGEND = (
    "右扳机 刷选 / 右握把 拖动\n"
    "左扳机+拖动 精细 / 右A 平滑\n"
    "右B 保存 / 左X 选择模式\n"
    "左Y 开关面板 / 摇杆 移动\n"
    "右摇杆 转身 / 双手缩放旋转"
)

PAGES = (
    ("select", "选择", (
        ("select_all", "全选", "选中当前网格的所有元素"),
        ("deselect", "取消", "清空当前选择"),
        ("invert", "反选", "反转当前选择"),
        ("linked", "相连", "从已选顶点扩展到连通区域"),
        ("mode_vert", "顶点", "顶点选择模式"),
        ("mode_edge", "边", "边选择模式"),
        ("mode_face", "面", "面选择模式"),
        ("editmode", "编辑", "切换编辑/物体模式"),
    )),
    ("edit", "编辑", (
        ("merge", "合并", "按 0.1mm 合并选中顶点"),
        ("delete", "删除", "删除选中顶点"),
        ("smooth", "平滑", "拉普拉斯平滑两次"),
        ("subdivide", "细分", "细分选中的边"),
        ("extrude", "挤出", "沿法线挤出面"),
        ("flip_normals", "翻法线", "翻转选中面的法线"),
    )),
    ("view", "视图", (
        ("undo", "撤销", "撤销上一步 VR 编辑"),
        ("redo", "重做", "重做被撤销的一步"),
        ("reset_view", "重置", "重置场景导航"),
        ("save", "保存", "保存当前 .blend"),
        ("hide_panel", "隐藏", "隐藏面板（左Y 打开）"),
        ("help", "帮助", "显示快捷键帮助"),
    )),
    ("help", "帮助", ()),
)

_OBJECTS = {"root": None, "carousel": None, "laser": None, "tip": None}
_FACES = {}          # page_key -> {"matrix": Matrix, "objects": [...], "buttons": {...}, "title": obj}
_ARROWS = {}         # (page_key, "prev"/"next") -> (quad, label)
_HOVER = None        # (page_key, button_key)
_PAGE_OBJECTS = set()
_PRESSED = False
_PAGE = 0
_TARGET_ANGLE = 0.0
_CURRENT_ANGLE = 0.0
_ALL_OBJECTS = []


def _rounded(name, w, h, r, color, seg=3):
    pts = []
    for cx, cy, a0, a1 in (
        (w / 2 - r, h / 2 - r, 0, 90), (-w / 2 + r, h / 2 - r, 90, 180),
        (-w / 2 + r, -h / 2 + r, 180, 270), (w / 2 - r, -h / 2 + r, 270, 360),
    ):
        for i in range(seg):
            a = math.radians(a0 + (a1 - a0) * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), 0.0))
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, [], [list(range(len(pts)))])
    me.update()
    me.materials.append(_mat(name + "_mat", color))
    obj = bpy.data.objects.new(name, me)
    obj.color = color
    return obj


def _text(name, body, size, color, x, y, z=0.002):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    f = _font()
    if f is not None:
        try:
            cu.font = f
        except Exception:  # noqa: BLE001
            pass
    cu.materials.append(_mat(name + "_mat", color))
    obj = bpy.data.objects.new(name, cu)
    obj.color = color
    obj.location = (x, y, z)
    return obj


def _line(name, count, bevel, color):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = bevel
    cu.bevel_resolution = 0
    cu.resolution_u = 1
    sp = cu.splines.new("POLY")
    sp.points.add(count - 1)
    cu.materials.append(_mat(name + "_mat", color))
    return bpy.data.objects.new(name, cu)


def _mat(name, color, emission=1.0):
    """Matte, non-reflective panel material (specular glints made the text unreadable)."""
    from . import overlay
    mat = overlay._material("panel_" + name, color, emission)
    try:
        mat.surface_render_method = "DITHERED"
        mat.metallic = 0.0
        mat.roughness = 1.0
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.bl_idname == "ShaderNodeBsdfPrincipled":
                    node.inputs["Metallic"].default_value = 0.0
                    node.inputs["Roughness"].default_value = 1.0
                    node.inputs["Specular IOR Level"].default_value = 0.0
    except Exception:  # noqa: BLE001
        pass
    return mat


_BOLD = None


def _font():
    """Bold CJK face: thin strokes were hard to read inside the headset."""
    global _BOLD
    if _BOLD is not None:
        return _BOLD
    for path in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(path):
            try:
                _BOLD = bpy.data.fonts.load(path)
                return _BOLD
            except Exception:  # noqa: BLE001
                continue
    from . import overlay
    return overlay._font()


def _link(context, parent, obj):
    context.scene.collection.objects.link(obj)
    obj.parent = parent
    obj.hide_select = True
    obj.hide_render = True
    obj.show_in_front = False
    obj.hide_viewport = True
    _ALL_OBJECTS.append(obj)
    return obj


def _face_matrix(index):
    """Local matrix of face ``index`` around the handle (ring of four)."""
    angle = math.radians(90.0 * index)
    rot = Matrix.Rotation(angle, 4, "Y")
    offset = Matrix.Translation((0.0, 0.0, RADIUS))
    return rot @ offset


def _layout(count):
    """Single column, starting below the title so nothing overflows the card."""
    cols = 1
    rows = count
    x0 = 0.0
    y_top = FACE_H / 2.0 - 0.022 - BTN_H / 2.0
    return cols, rows, x0, y_top


def _purge_stale(context):
    """Remove vrtweak_* objects saved by an earlier VR session."""
    for obj in list(bpy.data.objects):
        if obj.name.startswith("vrtweak_"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass



def _prune():
    for key, obj in list(_OBJECTS.items()):
        if obj is None:
            continue
        try:
            obj.name
        except ReferenceError:
            _OBJECTS[key] = None


def add(context):
    _prune()
    if _OBJECTS["root"] is not None:
        return
    _purge_stale(context)
    root = bpy.data.objects.new("vrtweak_panel_root", None)
    context.scene.collection.objects.link(root)
    root.hide_render = True
    root.hide_select = True
    root.show_in_front = True
    _OBJECTS["root"] = root
    _ALL_OBJECTS.append(root)

    carousel = bpy.data.objects.new("vrtweak_panel_carousel", None)
    context.scene.collection.objects.link(carousel)
    carousel.parent = root
    carousel.hide_render = True
    carousel.hide_select = True
    carousel.show_in_front = True
    _OBJECTS["carousel"] = carousel
    _ALL_OBJECTS.append(carousel)

    for index, (page_key, page_title, items) in enumerate(PAGES):
        face = bpy.data.objects.new("vrtweak_face_" + page_key, None)
        context.scene.collection.objects.link(face)
        face.parent = None

        face.hide_render = True
        face.hide_select = True
        face.show_in_front = True
        _ALL_OBJECTS.append(face)

        objects = [
            _link(context, face, _rounded("vrtweak_bg_" + page_key, FACE_W, FACE_H, 0.010, BG_COLOR)),
            _link(context, face, _rounded("vrtweak_border_" + page_key, FACE_W + 0.005, FACE_H + 0.005, 0.012, BORDER_COLOR)),
        ]
        objects[-1].location = (0.0, 0.0, -0.002)
        objects.append(_link(context, face, _text("vrtweak_title_" + page_key, page_title + " / " + {"select": "Select", "edit": "Edit", "view": "View", "help": "Help"}.get(page_key, ""), 0.0105, TITLE_COLOR, 0.0, FACE_H / 2 - 0.014)))

        buttons = {}
        if items:
            cols, rows, x0, y0 = _layout(len(items))
            for item_index, (key, label, desc) in enumerate(items):
                x = x0 + (item_index % cols) * (BTN_W + BTN_GAP)
                y = y0 - item_index * (BTN_H + BTN_GAP)
                quad = _link(context, face, _rounded("vrtweak_btn_" + page_key + "_" + key, BTN_W, BTN_H, 0.006, BTN_IDLE))
                quad.location = (x, y, 0.001)
                text = _link(context, face, _text("vrtweak_lbl_" + page_key + "_" + key, label + " " + EN_SHORT.get(key, EN.get(key, "")), 0.0080, TEXT_COLOR, x, y, 0.003))
                buttons[key] = (quad, text, desc, label)
                objects.extend((quad, text))
        else:
            _lines = LEGEND.split("\n")
            _cols = ("\n".join(_lines[:5]), "\n".join(_lines[5:]))
            for col, body in enumerate(_cols):
                help_text = _link(context, face, _text(
                    "vrtweak_help_%s_%d" % (page_key, col), body, 0.0048, TEXT_COLOR,
                    -FACE_W / 2 + 0.006 + col * (FACE_W / 2 + 0.010), FACE_H / 2 - 0.030))
                help_text.data.align_x = "LEFT"
                objects.append(help_text)

        for key, glyph, dx in (("prev", "«", -(FACE_W / 2 - 0.020)), ("next", "»", FACE_W / 2 - 0.020)):
            y = FACE_H / 2 - 0.018
            quad = _link(context, face, _rounded("vrtweak_arrow_" + page_key + key, ARROW_W, ARROW_W, 0.005, BTN_IDLE))
            quad.location = (dx, y, 0.001)
            label = _link(context, face, _text("vrtweak_arrowlbl_" + page_key + key, glyph, 0.014, TEXT_COLOR, dx, y, 0.003))
            _ARROWS[(page_key, key)] = (quad, label)
            objects.extend((quad, label))
        _FACES[page_key] = {"objects": objects, "buttons": buttons, "face": face}
        _PAGE_OBJECTS.update(objects)
        _PAGE_OBJECTS.add(face)

    _OBJECTS["tip"] = _link(context, root, _rounded("vrtweak_tip_bg", TIP_W, TIP_H, 0.008, TIP_BG))
    _OBJECTS["tip"].location = (0.0, FACE_H + 0.020, RADIUS + 0.002)
    _OBJECTS["tip_border"] = _link(context, root, _rounded("vrtweak_tip_border", TIP_W + 0.004, TIP_H + 0.004, 0.010, TIP_BORDER))
    _OBJECTS["tip_border"].location = (0.0, FACE_H + 0.020, RADIUS + 0.001)
    _OBJECTS["tip_name"] = _link(context, root, _text("vrtweak_tip_name", "", 0.0062, TIP_NAME, 0.0, FACE_H + 0.030, RADIUS + 0.006))
    _OBJECTS["tip_desc"] = _link(context, root, _text("vrtweak_tip_desc", "", 0.0050, TIP_DESC, 0.0, FACE_H + 0.012, RADIUS + 0.006))

    laser = _line("vrtweak_panel_laser", 2, 0.0012, (0.22, 0.62, 1.0, 1.0))
    context.scene.collection.objects.link(laser)
    laser.hide_select = True
    laser.hide_render = True
    laser.show_in_front = True
    laser.hide_viewport = True
    _OBJECTS["laser"] = laser
    _ALL_OBJECTS.append(laser)


def _visible(visible, active_key=None):
    """Show root-level objects only; page contents are toggled by the page loop."""
    for obj in _ALL_OBJECTS:
        if obj in _PAGE_OBJECTS:
            continue          # handled per page every frame
        name = obj.name
        if name.startswith("vrtweak_tip") or name.startswith("vrtweak_panel_laser"):
            obj.hide_viewport = True
            continue
        obj.hide_viewport = not visible


def _tip_visible(visible):
    for key in ("tip", "tip_border", "tip_name", "tip_desc"):
        obj = _OBJECTS.get(key)
        if obj is not None:
            obj.hide_viewport = not visible


def _tip(name, desc):
    _tip_visible(bool(name))
    if name:
        _OBJECTS["tip_name"].data.body = name
        _OBJECTS["tip_desc"].data.body = desc or ""




def _page_matrix(grip_mat, index, carousel_angle, viewer=None):
    """Exactly the box's +Y face: same centre, same width/height, same normal.

    Box half extents are (0.032, 0.032, 0.070); its +Y face is therefore a
    6.4 x 14.0 cm rectangle centred at grip + (grip_rot @ +Y) * 0.032.
    """
    rot = grip_mat.to_3x3()
    face_index = (index + _PAGE) % 4
    if face_index == 0:
        normal = (rot @ Vector((0.0, 1.0, 0.0))).normalized()    # +Y
    elif face_index == 1:
        normal = (rot @ Vector((1.0, 0.0, 0.0))).normalized()    # +X
    elif face_index == 2:
        normal = (rot @ Vector((0.0, -1.0, 0.0))).normalized()   # -Y
    else:
        normal = (rot @ Vector((-1.0, 0.0, 0.0))).normalized()   # -X
    center = grip_mat.translation + normal * (0.032 + 0.004)   # 4 mm off the face
    # up follows the handle's long axis, flipped so the text is not upside down
    y_axis = (-(rot @ Vector((0.0, 0.0, 1.0)))).normalized()
    x_axis = y_axis.cross(normal).normalized()
    basis = Matrix((x_axis, y_axis, normal)).transposed().to_4x4()
    return Matrix.Translation(center) @ basis


def _hit_face(matrix, origin, direction):
    inv = matrix.inverted()
    o = inv @ origin
    d = (inv.to_3x3() @ direction).normalized()
    if abs(d.z) < 1e-6:
        return None, None
    t = -o.z / d.z
    if t <= 0:
        return None, None
    p = o + d * t
    if abs(p.x) <= FACE_W / 2 and abs(p.y) <= FACE_H / 2:
        return p, t
    return None, None


def _button_at(page_key, point):
    data = _FACES.get(page_key)
    if not data:
        return None
    items = PAGES[[p[0] for p in PAGES].index(page_key)][2]
    if not items:
        return None
    cols, rows, x0, y0 = _layout(len(items))
    for index, (key, label, desc) in enumerate(items):
        x = x0 + (index % cols) * (BTN_W + BTN_GAP)
        y = y0 - index * (BTN_H + BTN_GAP)
        if abs(point.x - x) <= BTN_W / 2 and abs(point.y - y) <= BTN_H / 2:
            return key, label, desc
    return None


def _arrow_at(page_key, point):
    y = -0.090
    for key, dx in (("prev", -(FACE_W / 2 - 0.020)), ("next", FACE_W / 2 - 0.020)):
        if abs(point.x - dx) <= ARROW_W / 2 and abs(point.y - y) <= ARROW_W / 2:
            return key
    return None


def _set_color(obj, color):
    _mat(obj.data.materials[0].name, color)
    try:
        obj.color = color
    except Exception:  # noqa: BLE001
        pass


def _hover_visuals():
    for page_key, data in _FACES.items():
        for key, (quad, _text_obj, _desc, _label) in data["buttons"].items():
            active = _HOVER == (page_key, key)
            _set_color(quad, BTN_HOVER if active else BTN_IDLE)
    for (page_key, key), (quad, _label) in _ARROWS.items():
        _set_color(quad, BTN_HOVER if _HOVER == (page_key, "arrow_" + key) else BTN_IDLE)


def update(context, viewer, grip_loc, grip_rot, aim_loc, aim_rot, trigger, visible, dispatch):
    global _HOVER, _PRESSED, _TARGET_ANGLE, _CURRENT_ANGLE, _PAGE
    result = {"hover": False, "clicked": None}
    root = _OBJECTS.get("root")
    if root is None:
        return result
    if not visible or grip_loc is None or grip_rot is None:
        _visible(False)
        _HOVER = None
        _PRESSED = False
        return result

    grip_q = Quaternion(grip_rot)
    grip_mat = Matrix.Translation(Vector(grip_loc)) @ grip_q.to_matrix().to_4x4()
    root.matrix_world = grip_mat
    _visible(True, PAGES[_PAGE][0])

    # smooth 90-degree page rotation of the ring
    delta = _TARGET_ANGLE - _CURRENT_ANGLE
    if abs(delta) > 1e-4:
        _CURRENT_ANGLE += delta * 0.25
    else:
        _CURRENT_ANGLE = _TARGET_ANGLE
    _OBJECTS["carousel"].matrix_basis = Matrix.Identity(4)

    # Place the four pages on the box every frame, independent of the aim ray
    # (they used to be positioned only while a ray existed, which left them near
    # the origin whenever the aiming pose was missing).
    page_matrices = {}
    for index, (page_key, _title, _items) in enumerate(PAGES):
        face = _FACES[page_key]["face"]
        matrix = _page_matrix(grip_mat, index, 0.0, viewer=viewer)
        face.matrix_world = matrix
        page_matrices[page_key] = matrix
        face.hide_viewport = False
        for obj in _FACES[page_key]["objects"]:
            obj.hide_viewport = False

    hit_key = None
    hit_loc = None
    hover_point = None
    if aim_loc is not None and aim_rot is not None:
        direction = (Quaternion(aim_rot) @ Vector((0.0, 0.0, -1.0))).normalized()
        origin = Vector(aim_loc)
        best = None
        for page_key in (p[0] for p in PAGES):
            matrix = page_matrices[page_key]
            point, t = _hit_face(matrix, origin, direction)
            if point is None:
                continue
            if best is None or t < best[0]:
                best = (t, page_key, matrix, point)
        if best is not None:
            _t, page_key, matrix, point = best
            hit_loc = matrix @ point
            hover_point = point
            arrow = _arrow_at(page_key, point)
            if arrow is not None:
                hit_key = (page_key, "arrow_" + arrow)
            else:
                found = _button_at(page_key, point)
                if found is not None:
                    hit_key = (page_key, found[0])
                    if PAGES[[p[0] for p in PAGES].index(page_key)][0] != PAGES[_PAGE][0]:
                        pass
            _set_laser(origin, hit_loc if hit_loc is not None
                       else origin + direction * 0.30)
        else:
            _set_laser(origin, origin + direction * 0.30)
    else:
        laser = _OBJECTS.get("laser")
        if laser is not None:
            laser.hide_viewport = True

    if hit_key != _HOVER:
        _HOVER = hit_key
        _hover_visuals()
    if hit_key is not None:
        page_key = hit_key[0]
        page_matrix = page_matrices.get(page_key)
        if page_matrix is not None:
            anchor_x = hover_point.x if hover_point is not None else 0.0
            anchor_y = FACE_H / 2.0 + 0.050
            tip_matrix = (
                page_matrix
                @ Matrix.Translation((anchor_x, anchor_y + 0.055, 0.016))
            )
            for key_name in ("tip", "tip_border", "tip_name", "tip_desc"):
                obj = _OBJECTS.get(key_name)
                if obj is None:
                    continue
                offset = obj.name
                bom = Matrix.Identity(4)
                if key_name == "tip_border":
                    bom = Matrix.Translation((0.0, 0.0, -0.001))
                elif key_name == "tip_name":
                    bom = Matrix.Translation((0.0, TIP_H / 2.0 - 0.012, 0.004))
                elif key_name == "tip_desc":
                    bom = Matrix.Translation((0.0, -TIP_H / 2.0 + 0.014, 0.004))
                obj.matrix_world = tip_matrix @ bom
            _tip_visible(True)
    if hit_key is not None:
        page_key = hit_key[0]
        if hit_key[1].startswith("arrow_"):
            _tip("翻页 / page", "点击切换页面")
        else:
            data = _FACES[page_key]["buttons"].get(hit_key[1])
            if data is not None:
                _tip(data[3] + " / " + EN.get(hit_key[1], data[3]), data[2])
    else:
        _tip(None, None)

    if hit_key is not None and trigger and not _PRESSED:
        _PRESSED = True
        page_key, key = hit_key
        if key.startswith("arrow_"):
            step = -1 if key == "arrow_prev" else 1
            _PAGE = (_PAGE + step) % len(PAGES)
            _TARGET_ANGLE -= math.radians(90.0) * step
        else:
            action = dispatch.get(key) if dispatch else None
            if action is not None:
                try:
                    action(context)
                except Exception:  # noqa: BLE001
                    pass
        result["clicked"] = key
    if not trigger:
        _PRESSED = False
    result["hover"] = hit_key is not None
    return result


def _set_laser(start, end):
    laser = _OBJECTS.get("laser")
    if laser is None:
        return
    pts = laser.data.splines[0].points
    pts[0].co = tuple(start) + (1.0,)
    pts[1].co = tuple(end) + (1.0,)
    laser.data.update_tag()
    laser.hide_viewport = False


def page_key():
    return PAGES[_PAGE][0]


def go_to_page(key):
    global _PAGE, _TARGET_ANGLE
    for index, (page_key_value, _title, _items) in enumerate(PAGES):
        if page_key_value == key:
            step = index - _PAGE
            _PAGE = index
            _TARGET_ANGLE -= math.radians(90.0) * step
            return True
    return False


def next_page():
    return go_to_page(PAGES[(_PAGE + 1) % len(PAGES)][0])


def prev_page():
    return go_to_page(PAGES[(_PAGE - 1) % len(PAGES)][0])


def hide():
    global _HOVER, _PRESSED
    _visible(False)
    _HOVER = None
    _PRESSED = False


def remove():
    global _HOVER, _PRESSED
    for obj in list(_ALL_OBJECTS):
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
    _ALL_OBJECTS.clear()
    _FACES.clear()
    _ARROWS.clear()
    for key in list(_OBJECTS.keys()):
        _OBJECTS[key] = None
    _HOVER = None
    _PRESSED = False
