# SPDX-License-Identifier: GPL-3.0-or-later
"""P0 overlay: grip origin + controller tip + brush ring.

Drawn in the XR draw handler, world space, no helper objects in the scene.
"""
import math

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import actions, tip

_handle = None
_shader = None


def _circle(center, radius, axis, n=48):
    a = Vector(axis[0]).normalized()
    b = Vector(axis[1]).normalized()
    c = Vector(center)
    return [tuple(c + a * (radius * math.cos(t)) + b * (radius * math.sin(t)))
            for t in (i * math.tau / n for i in range(n + 1))]


def _draw_ring(shader, center, radius, color, width=2.0):
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    for axis in (((1, 0, 0), (0, 1, 0)), ((1, 0, 0), (0, 0, 1)), ((0, 1, 0), (0, 0, 1))):
        pts = _circle(center, radius, axis)
        batch = batch_for_shader(shader, "LINE_STRIP", {"pos": pts})
        batch.draw(shader)


def _draw_selection(shader):
    from . import mesh as meshlib
    try:
        context = bpy.context
        points = []
        lines = []
        tris = []
        for obj in meshlib.objects_in_edit(context):
            bm = meshlib.bm_for(obj)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            matrix = obj.matrix_world
            for vert in bm.verts:
                if vert.select and not vert.hide:
                    points.append(tuple(matrix @ vert.co))
                    if len(points) > 4000:
                        break
            for edge in bm.edges:
                if edge.select and not edge.hide:
                    lines.append(tuple(matrix @ edge.verts[0].co))
                    lines.append(tuple(matrix @ edge.verts[1].co))
                    if len(lines) > 8000:
                        break
            for face in bm.faces:
                if not face.select or face.hide:
                    continue
                verts = [tuple(matrix @ v.co) for v in face.verts]
                for i in range(1, len(verts) - 1):
                    tris.extend((verts[0], verts[i], verts[i + 1]))
                for edge in face.edges:
                    lines.append(tuple(matrix @ edge.verts[0].co))
                    lines.append(tuple(matrix @ edge.verts[1].co))
                if len(tris) > 12000 or len(lines) > 12000:
                    break
        if tris:
            shader.bind()
            shader.uniform_float("color", (1.0, 0.85, 0.1, 0.28))
            batch = batch_for_shader(shader, "TRIS", {"pos": tris})
            batch.draw(shader)
        if points:
            try:
                gpu.state.point_size_set(7.0)
            except Exception:  # noqa: BLE001
                pass
            shader.bind()
            shader.uniform_float("color", (1.0, 0.85, 0.1, 1.0))
            batch = batch_for_shader(shader, "POINTS", {"pos": points})
            batch.draw(shader)
        if lines:
            gpu.state.line_width_set(3.5)
            shader.bind()
            shader.uniform_float("color", (0.0, 1.0, 1.0, 1.0))
            batch = batch_for_shader(shader, "LINES", {"pos": lines})
            batch.draw(shader)
    except Exception:  # noqa: BLE001
        pass


def draw():
    context = bpy.context
    state = getattr(context.window_manager, "xr_session_state", None)
    if state is None:
        return
    settings = getattr(context.scene, "vrtweak", None)
    if settings is None:
        return

    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")

    hand = 1 if settings.hand == "RIGHT" else 0
    offset = settings.tip_offset
    tip_loc, grip_loc = tip.read(context, hand, offset, settings.tip_source)

    if grip_loc is not None:
        grip_color = (0.2, 0.8, 1.0, 0.9) if settings.vertical_move else (1.0, 1.0, 1.0, 0.9)
        _draw_ring(_shader, grip_loc, 0.008, grip_color, 2.0)
    if tip_loc is not None:
        radius = settings.brush_radius
        mode = tuple(bool(v) for v in context.tool_settings.mesh_select_mode)
        if mode[0]:
            color = (1.0, 0.55, 0.1, 0.9)      # vertex: orange
        elif mode[1]:
            color = (0.2, 0.9, 0.3, 0.9)       # edge: green
        else:
            color = (0.85, 0.3, 1.0, 0.9)      # face: purple
        _draw_ring(_shader, tip_loc, radius, color, 3.0)
        _draw_ring(_shader, tip_loc, 0.006, (1.0, 0.45, 0.05, 1.0), 2.0)

    _draw_selection(_shader)

    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.line_width_set(1.0)


def add():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), "XR", "POST_VIEW")


def remove():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "XR")
        _handle = None
