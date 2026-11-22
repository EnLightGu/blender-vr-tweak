# SPDX-License-Identifier: GPL-3.0-or-later
"""XR overlay: brush rings, selection highlight and the two-hand rotation gizmo.

Drawn as ordinary scene objects (curves / meshes / text), **not** via an XR draw
handler.

Why: on Blender 4.4.3 (Windows), registering and invoking a Python draw handler
for the ``"XR"`` region leaves ``bpy.context`` pointing at a dead draw context.
The next timer that touches ``context.window_manager`` then crashes Blender with
an access violation in ``rna_Context_manager_get`` (NULL + 8). See README 5.5.
"""
import math
import os

import bpy
from mathutils import Matrix, Vector

_AXES = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
         ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
         ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))

_SEGMENTS = 32
_ARC_POINTS = 17

_MODE_COLORS = {
    "VERT": (1.0, 0.55, 0.1, 1.0),   # vertex: orange
    "EDGE": (0.2, 0.9, 0.3, 1.0),    # edge: green
    "FACE": (0.85, 0.3, 1.0, 1.0),   # face: purple
}

_HANDLE_COLOR = (1.0, 0.45, 0.05, 1.0)
_GRIP_COLOR = (1.0, 1.0, 1.0, 1.0)
_GRIP_COLOR_VERTICAL = (0.2, 0.8, 1.0, 1.0)
_SEL_LINE_COLOR = (0.0, 1.0, 1.0, 1.0)
_SEL_FACE_COLOR = (1.0, 0.85, 0.1, 0.35)
_AXIS_COLOR = (1.0, 0.9, 0.2, 1.0)
_ARC_COLOR = (1.0, 0.6, 0.1, 1.0)
_TEXT_COLOR = (1.0, 0.95, 0.4, 1.0)

_OBJECTS = {
    "grip": None,
    "brush": None,
    "handle": None,
    "sel_edges": None,
    "sel_faces": None,
    "rot_axis": None,
    "rot_arc": None,
    "rot_arrow": None,
    "rot_text": None,
}
_MATERIALS = {}
_FONT = None
_FRAME = {"tip": None, "grip": None, "radius": 0.02, "mode": "VERT",
          "vertical": False, "points": (), "lines": (), "tris": ()}


def _font():
    global _FONT
    if _FONT is not None:
        return _FONT
    for path in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        if os.path.exists(path):
            try:
                _FONT = bpy.data.fonts.load(path)
                break
            except Exception:  # noqa: BLE001
                continue
    return _FONT


def _material(name, color, emission=2.0):
    mat = _MATERIALS.get(name)
    if mat is None:
        mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        tree = mat.node_tree
        tree.nodes.clear()
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        emit = tree.nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = emission
        tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
        try:
            mat.surface_render_method = "BLENDED"
        except Exception:  # noqa: BLE001
            try:
                mat.blend_method = "BLEND"
            except Exception:  # noqa: BLE001
                pass
        _MATERIALS[name] = mat
    mat.diffuse_color = color
    tree = mat.node_tree
    if tree is not None:
        emit = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeEmission"), None)
        if emit is not None:
            emit.inputs["Color"].default_value = color
    return mat


def _link(context, obj):
    context.scene.collection.objects.link(obj)
    obj.hide_select = True
    obj.hide_render = True
    obj.show_in_front = True
    obj.hide_viewport = True
    return obj


def _new_ring(name, bevel, color):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = bevel
    curve.bevel_resolution = 0
    curve.resolution_u = 1
    for _axis in _AXES:
        spline = curve.splines.new("POLY")
        spline.points.add(_SEGMENTS)
    curve.materials.append(_material(name + "_mat", color))
    return bpy.data.objects.new(name, curve)


def _set_ring(obj, center, radius, color):
    if center is None or radius <= 0.0:
        obj.hide_viewport = True
        return
    obj.hide_viewport = False
    obj.location = Vector(center)
    _material(obj.data.materials[0].name, color)
    curve = obj.data
    for spline, (ax, ay) in zip(curve.splines, _AXES):
        points = spline.points
        for index in range(len(points)):
            angle = math.tau * index / _SEGMENTS
            px = (ax[0] * math.cos(angle) + ay[0] * math.sin(angle)) * radius
            py = (ax[1] * math.cos(angle) + ay[1] * math.sin(angle)) * radius
            pz = (ax[2] * math.cos(angle) + ay[2] * math.sin(angle)) * radius
            points[index].co = (px, py, pz, 1.0)
    curve.update_tag()


def _new_mesh(name, color, alpha=False):
    mesh = bpy.data.meshes.new(name)
    mesh.materials.append(_material(name + "_mat", color, 1.0 if alpha else 2.0))
    obj = bpy.data.objects.new(name, mesh)
    if alpha:
        try:
            obj.color = color
        except Exception:  # noqa: BLE001
            pass
    return obj


def _set_edges(obj, lines, color):
    mesh = obj.data
    mesh.clear_geometry()
    if lines:
        verts = [tuple(p) for p in lines]
        edges = [(i, i + 1) for i in range(0, len(verts) - 1, 2)]
        mesh.from_pydata(verts, edges, [])
        _material(mesh.materials[0].name, color)
        obj.hide_viewport = False
    else:
        obj.hide_viewport = True
    mesh.update()


def _set_faces(obj, tris, color):
    mesh = obj.data
    mesh.clear_geometry()
    if tris:
        verts = [tuple(p) for p in tris]
        faces = [(i, i + 1, i + 2) for i in range(0, len(verts) - 2, 3)]
        mesh.from_pydata(verts, [], faces)
        _material(mesh.materials[0].name, color)
        obj.hide_viewport = False
    else:
        obj.hide_viewport = True
    mesh.update()


def _new_poly_curve(name, points_count, bevel, color):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = bevel
    curve.bevel_resolution = 0
    curve.resolution_u = 1
    spline = curve.splines.new("POLY")
    spline.points.add(points_count - 1)
    curve.materials.append(_material(name + "_mat", color))
    return bpy.data.objects.new(name, curve)


def _new_arrow(name, color):
    verts = [(0.05, 0.0, 0.0), (0.0, 0.016, 0.0), (0.0, -0.008, 0.014), (0.0, -0.008, -0.014)]
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(_material(name + "_mat", color))
    return bpy.data.objects.new(name, mesh)


def _new_text(name, color):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = ""
    curve.size = 0.045
    font = _font()
    if font is not None:
        try:
            curve.font = font
        except Exception:  # noqa: BLE001
            pass
    curve.materials.append(_material(name + "_mat", color))
    return bpy.data.objects.new(name, curve)


def _hide_rotation():
    for name in ("rot_axis", "rot_arc", "rot_arrow", "rot_text"):
        obj = _OBJECTS.get(name)
        if obj is not None:
            obj.hide_viewport = True


def show_rotation(center, axis, angle_deg, viewer=None):
    """Show the two-hand rotation axis, the swept arc with an arrow, and the angle.

    Call every tick while the two-hand view transform is active; pass
    ``axis=None`` (or a tiny angle) to hide the gizmo again.
    """
    axis_obj = _OBJECTS["rot_axis"]
    if axis_obj is None:
        return
    if axis is None or abs(angle_deg) < 1.0:
        _hide_rotation()
        return

    axis = Vector(axis).normalized()
    center = Vector(center)

    half = 0.19
    line = axis_obj.data.splines[0].points
    line[0].co = tuple(center - axis * half) + (1.0,)
    line[1].co = tuple(center + axis * half) + (1.0,)
    axis_obj.data.update_tag()
    axis_obj.hide_viewport = False

    radius = 0.10
    sweep = math.radians(min(max(abs(angle_deg), 12.0), 160.0))
    u = axis.orthogonal().normalized()
    v = axis.cross(u).normalized()
    arc = _OBJECTS["rot_arc"].data.splines[0].points
    steps = len(arc) - 1
    for index, point in enumerate(arc):
        t = sweep * index / steps
        point.co = tuple(center + (u * math.cos(t) + v * math.sin(t)) * radius) + (1.0,)
    _OBJECTS["rot_arc"].data.update_tag()
    _OBJECTS["rot_arc"].hide_viewport = False

    end = center + (u * math.cos(sweep) + v * math.sin(sweep)) * radius
    tangent = (u * -math.sin(sweep) + v * math.cos(sweep)).normalized()
    arrow = _OBJECTS["rot_arrow"]
    arrow.matrix_world = Matrix.Translation(end) @ tangent.to_track_quat("X", "Z").to_matrix().to_4x4()
    arrow.hide_viewport = False

    text = _OBJECTS["rot_text"]
    text.data.body = f"旋转 {angle_deg:.0f}°"
    anchor = center + Vector((0.0, 0.0, 0.11))
    if viewer is not None:
        anchor = anchor + (Vector(viewer) - center).normalized() * 0.08
        text.rotation_euler = (Vector(viewer) - anchor).to_track_quat("Z", "Y").to_euler()
    text.location = anchor
    text.hide_viewport = False


def hide_rotation():
    _hide_rotation()



def _prune():
    """Forget objects that a file load / cleanup removed from bpy.data."""
    for key, obj in list(_OBJECTS.items()):
        if obj is None:
            continue
        try:
            obj.name
        except ReferenceError:
            _OBJECTS[key] = None


def add(context):
    """Create the overlay objects (called from session.start)."""
    _prune()
    if _OBJECTS["grip"] is not None:
        return
    _OBJECTS["grip"] = _link(context, _new_ring("vrtweak_grip_ring", 0.0011, _GRIP_COLOR))
    _OBJECTS["brush"] = _link(context, _new_ring("vrtweak_brush_ring", 0.0016, _MODE_COLORS["VERT"]))
    _OBJECTS["handle"] = _link(context, _new_ring("vrtweak_handle_ring", 0.0009, _HANDLE_COLOR))
    _OBJECTS["sel_edges"] = _link(context, _new_mesh("vrtweak_sel_edges", _SEL_LINE_COLOR))
    _OBJECTS["sel_faces"] = _link(context, _new_mesh("vrtweak_sel_faces", _SEL_FACE_COLOR, alpha=True))
    _OBJECTS["rot_axis"] = _link(context, _new_poly_curve("vrtweak_rot_axis", 2, 0.0018, _AXIS_COLOR))
    _OBJECTS["rot_arc"] = _link(context, _new_poly_curve("vrtweak_rot_arc", _ARC_POINTS, 0.0015, _ARC_COLOR))
    _OBJECTS["rot_arrow"] = _link(context, _new_arrow("vrtweak_rot_arrow", _ARC_COLOR))
    _OBJECTS["rot_text"] = _link(context, _new_text("vrtweak_rot_text", _TEXT_COLOR))


def update(tip=None, grip=None, radius=0.02, mode="VERT", vertical=False,
           points=(), lines=(), tris=()):
    """Publish one frame (called from session.tick, 20 Hz)."""
    _FRAME.update(tip=tip, grip=grip, radius=radius, mode=mode,
                  vertical=vertical, points=points, lines=lines, tris=tris)
    grip_obj = _OBJECTS["grip"]
    if grip_obj is None:
        return
    _set_ring(grip_obj, grip, 0.008, _GRIP_COLOR_VERTICAL if vertical else _GRIP_COLOR)
    _set_ring(_OBJECTS["brush"], tip, radius, _MODE_COLORS.get(mode, _MODE_COLORS["VERT"]))
    _set_ring(_OBJECTS["handle"], tip, 0.006, _HANDLE_COLOR)
    _set_edges(_OBJECTS["sel_edges"], lines, _SEL_LINE_COLOR)
    _set_faces(_OBJECTS["sel_faces"], tris, _SEL_FACE_COLOR)


def reset():
    for obj in _OBJECTS.values():
        if obj is not None:
            obj.hide_viewport = True
    _FRAME.update(tip=None, grip=None, radius=0.02, mode="VERT", vertical=False,
                  points=(), lines=(), tris=())
    _hide_rotation()


def remove():
    """Delete the overlay objects (called from session cleanup/unregister)."""
    for key, obj in list(_OBJECTS.items()):
        if obj is not None:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass
            _OBJECTS[key] = None
    reset()
