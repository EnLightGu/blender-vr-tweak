# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit-mode mesh helpers.

All geometry writes go through bmesh: writing mesh.vertices while in edit mode
is silently discarded (verified by the P0 benchmark).
"""
import bpy
import bmesh
from mathutils import Vector


def objects_in_edit(context):
    try:
        objs = list(context.objects_in_mode)
    except Exception:  # noqa: BLE001
        objs = []
    if not objs:
        active = context.view_layer.objects.active
        if active is not None and active.mode == "EDIT":
            objs = [active]
    return [o for o in objs if o.type == "MESH"]


def ensure_edit(context):
    active = context.view_layer.objects.active
    if active is None or active.type != "MESH":
        raise RuntimeError("Select a mesh object first")
    if active.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    if not objects_in_edit(context):
        raise RuntimeError("No mesh in edit mode")


def leave_edit(context):
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:  # noqa: BLE001
        pass


def bm_for(obj):
    return bmesh.from_edit_mesh(obj.data)


def update(obj):
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)


def _segment_distance(point, a, b):
    ab = b - a
    length2 = ab.length_squared
    if length2 < 1e-12:
        return (point - a).length
    t = max(0.0, min(1.0, (point - a).dot(ab) / length2))
    return (point - (a + ab * t)).length


def _face_distance(point, face):
    from mathutils.geometry import closest_point_on_tri
    verts = list(face.verts)
    best = 1e9
    for i in range(1, len(verts) - 1):
        closest = closest_point_on_tri(point, verts[0].co, verts[i].co, verts[i + 1].co)
        best = min(best, (closest - point).length)
    return best


def pick_element(context, center, radius):
    """Return (object, kind, index, distance) for the nearest element under the tip."""
    mode = tuple(bool(v) for v in context.tool_settings.mesh_select_mode)
    kind = "VERT" if mode[0] else ("EDGE" if mode[1] else "FACE")
    best = (None, None, None, 1e9)
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        inv = obj.matrix_world.inverted()
        local = inv @ Vector(center)
        scale = max(obj.matrix_world.to_scale())
        if kind == "VERT":
            for vert in bm.verts:
                if vert.hide:
                    continue
                distance = (vert.co - local).length * scale
                if distance < best[3]:
                    best = (obj, kind, vert.index, distance)
        elif kind == "EDGE":
            for edge in bm.edges:
                if edge.hide:
                    continue
                distance = _segment_distance(local, edge.verts[0].co, edge.verts[1].co) * scale
                if distance < best[3]:
                    best = (obj, kind, edge.index, distance)
        else:
            for face in bm.faces:
                if face.hide:
                    continue
                distance = _face_distance(local, face) * scale
                if distance < best[3]:
                    best = (obj, kind, face.index, distance)
    return best if best[0] is not None and best[3] <= radius else (None, None, None, best[3])


def select_element(context, obj, kind, index, additive=True):
    bm = bm_for(obj)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.select_mode = {kind}
    if kind == "VERT":
        vert = bm.verts[index]
        vert.select = additive
    elif kind == "EDGE":
        edge = bm.edges[index]
        edge.select = additive
        for vert in edge.verts:
            vert.select = additive
    else:
        face = bm.faces[index]
        face.select = additive
        for vert in face.verts:
            vert.select = additive
    bm.select_flush_mode()
    update(obj)


def brush_select(context, center, radius, additive=True):
    """Select mesh elements within a world-space sphere, by current mode."""
    mode = tuple(bool(v) for v in context.tool_settings.mesh_select_mode)
    if mode[0]:
        kind = "VERT"
    elif mode[1]:
        kind = "EDGE"
    else:
        kind = "FACE"
    count = 0
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.select_mode = {kind}
        inv = obj.matrix_world.inverted()
        local = inv @ Vector(center)
        scale = max(obj.matrix_world.to_scale())
        r = radius / max(scale, 1e-6)

        if kind == "VERT":
            for vert in bm.verts:
                if vert.hide:
                    continue
                if (vert.co - local).length <= r:
                    vert.select = additive
                    count += 1
        elif kind == "EDGE":
            for edge in bm.edges:
                if edge.hide:
                    continue
                distance = _segment_distance(local, edge.verts[0].co, edge.verts[1].co)
                if distance <= r:
                    edge.select = additive
                    for vert in edge.verts:
                        vert.select = additive
                    count += 1
        else:
            for face in bm.faces:
                if face.hide:
                    continue
                distance = _face_distance(local, face)
                if distance <= r:
                    face.select = additive
                    for vert in face.verts:
                        vert.select = additive
                    count += 1
        bm.select_flush_mode()
        update(obj)
    return count


def clear_selection(context):
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        for vert in bm.verts:
            vert.select = False
        for edge in bm.edges:
            edge.select = False
        for face in bm.faces:
            face.select = False
        bm.select_flush_mode()
        update(obj)


def capture_selection(context):
    """Copy selected vertex coordinates for undo, keyed by object name."""
    base = {}
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        coords = {v.index: v.co.copy() for v in bm.verts if v.select and not v.hide}
        if coords:
            base[obj.name] = coords
    return base


def cycle_select_mode(context):
    modes = [(True, False, False), (False, True, False), (False, False, True)]
    current = tuple(bool(v) for v in context.tool_settings.mesh_select_mode)
    index = modes.index(current) if current in modes else 0
    index = (index + 1) % len(modes)
    context.tool_settings.mesh_select_mode = modes[index]
    names = ("VERT", "EDGE", "FACE")
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.select_mode = {names[index]}
        bm.select_flush_mode()
        update(obj)
    return names[index]


def smooth_selection(context, strength=0.5, iterations=1):
    strength = max(0.0, min(1.0, strength))
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        for _ in range(max(1, iterations)):
            updates = {}
            for vert in bm.verts:
                if not vert.select or vert.hide:
                    continue
                neighbours = [e.other_vert(vert) for e in vert.link_edges]
                neighbours = [n for n in neighbours if n.is_valid and not n.hide]
                if not neighbours:
                    continue
                average = Vector((0.0, 0.0, 0.0))
                for n in neighbours:
                    average += n.co
                average /= len(neighbours)
                weight = 0.5 if any(not n.select for n in neighbours) else 1.0
                updates[vert.index] = vert.co.lerp(average, strength * weight)
            for index, co in updates.items():
                vert = bm.verts[index]
                if vert.is_valid:
                    vert.co = co
        update(obj)


def selection(context):
    """Return {object_name: set(vertex_index)} for selected vertices."""
    result = {}
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        idx = {v.index for v in bm.verts if v.select and not v.hide}
        if idx:
            result[obj.name] = idx
    return result


def selection_center(context):
    total = Vector((0.0, 0.0, 0.0))
    n = 0
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        for vert in bm.verts:
            if vert.select and not vert.hide:
                total += obj.matrix_world @ vert.co
                n += 1
    return (total / n) if n else None


class Scale:
    """Scale selected vertices around their local center."""

    def __init__(self):
        self.base = {}
        self.center = {}

    def begin(self, context):
        self.base = {}
        self.center = {}
        for obj in objects_in_edit(context):
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            coords = {v.index: v.co.copy() for v in bm.verts if v.select and not v.hide}
            if not coords:
                continue
            center = Vector((0.0, 0.0, 0.0))
            for co in coords.values():
                center += co
            center /= len(coords)
            self.base[obj.name] = coords
            self.center[obj.name] = center
        return bool(self.base)

    def apply(self, context, factor):
        for obj in objects_in_edit(context):
            coords = self.base.get(obj.name)
            if not coords:
                continue
            center = self.center[obj.name]
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            for index, base in coords.items():
                vert = bm.verts[index]
                if vert.is_valid:
                    vert.co = center + (base - center) * factor
            update(obj)


class Pinch:
    """Two-hand grab: translate + scale selected vertices around their center."""

    def __init__(self):
        self.base = {}
        self.center = {}

    def begin(self, context):
        self.base = {}
        self.center = {}
        for obj in objects_in_edit(context):
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            coords = {v.index: v.co.copy() for v in bm.verts if v.select and not v.hide}
            if not coords:
                continue
            center = Vector((0.0, 0.0, 0.0))
            for co in coords.values():
                center += co
            center /= len(coords)
            self.base[obj.name] = coords
            self.center[obj.name] = center
        return bool(self.base)

    def apply(self, context, world_delta, factor, rotation=None):
        for obj in objects_in_edit(context):
            coords = self.base.get(obj.name)
            if not coords:
                continue
            center = self.center[obj.name]
            inv = obj.matrix_world.inverted().to_3x3()
            local_delta = inv @ Vector(world_delta)
            local_rotation = None
            if rotation is not None:
                obj_rot = obj.matrix_world.to_quaternion()
                local_rotation = obj_rot.inverted() @ rotation @ obj_rot
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            for index, base in coords.items():
                vert = bm.verts[index]
                if vert.is_valid:
                    offset = (base - center) * factor
                    if local_rotation is not None:
                        offset = local_rotation @ offset
                    vert.co = center + offset + local_delta
            update(obj)


class Translate:
    """Baseline coordinates for a live translate, all in bmesh space."""

    def __init__(self):
        self.base = {}  # obj.name -> {index: Vector}

    def begin(self, context):
        self.base = {}
        for obj in objects_in_edit(context):
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            coords = {v.index: v.co.copy() for v in bm.verts if v.select and not v.hide}
            if coords:
                self.base[obj.name] = coords
        return bool(self.base)

    def apply(self, context, world_delta):
        for obj in objects_in_edit(context):
            coords = self.base.get(obj.name)
            if not coords:
                continue
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            inv = obj.matrix_world.inverted().to_3x3()
            local_delta = inv @ Vector(world_delta)
            for index, base in coords.items():
                vert = bm.verts[index]
                if vert.is_valid:
                    vert.co = base + local_delta
            update(obj)

    def cancel(self, context):
        for obj in objects_in_edit(context):
            coords = self.base.get(obj.name)
            if not coords:
                continue
            bm = bm_for(obj)
            bm.verts.ensure_lookup_table()
            for index, base in coords.items():
                vert = bm.verts[index]
                if vert.is_valid:
                    vert.co = base.copy()
            update(obj)
        self.base = {}

def selection_geometry(context, max_points=4000, max_lines=8000, max_tris=12000):
    """World-space points / edge segments / face triangles for the selection.

    Computed by the 20 Hz timer (session.tick) and cached for the XR draw
    handler: draw callbacks must not touch bpy.context on Windows (see
    overlay.py), and rebuilding the batches once per tick is cheaper than
    once per eye per frame.
    """
    points = []
    lines = []
    tris = []
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        matrix = obj.matrix_world
        for vert in bm.verts:
            if vert.select and not vert.hide:
                points.append(tuple(matrix @ vert.co))
                if len(points) >= max_points:
                    break
        for edge in bm.edges:
            if edge.select and not edge.hide:
                lines.append(tuple(matrix @ edge.verts[0].co))
                lines.append(tuple(matrix @ edge.verts[1].co))
                if len(lines) >= max_lines:
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
            if len(tris) >= max_tris or len(lines) >= max_lines:
                break
    return points, lines, tris

# ---------------------------------------------------------------------------
# Floating-panel / view-only helpers
# ---------------------------------------------------------------------------

def try_enter_edit(context):
    """Enter edit mode on a sensible mesh; return False instead of raising."""
    active = context.view_layer.objects.active
    meshes = []
    if active is not None and active.type == "MESH":
        meshes = [active]
    if not meshes:
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
    if not meshes:
        candidates = [o for o in context.scene.objects if o.type == "MESH"]
        if len(candidates) == 1:
            meshes = candidates
    if not meshes:
        return False
    target = meshes[0]
    try:
        context.view_layer.objects.active = target
        target.select_set(True)
        if target.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")
    except Exception:  # noqa: BLE001
        return False
    return bool(objects_in_edit(context))


def toggle_edit_mode(context):
    if context.mode == "EDIT":
        leave_edit(context)
        return False
    return try_enter_edit(context)


def select_all(context):
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        for vert in bm.verts:
            vert.select = True
        for edge in bm.edges:
            edge.select = True
        for face in bm.faces:
            face.select = True
        bm.select_flush_mode()
        update(obj)


def deselect_all(context):
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        for vert in bm.verts:
            vert.select = False
        for edge in bm.edges:
            edge.select = False
        for face in bm.faces:
            face.select = False
        bm.select_flush_mode()
        update(obj)


def invert_selection(context):
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        for vert in bm.verts:
            if not vert.hide:
                vert.select = not vert.select
        for edge in bm.edges:
            if not edge.hide:
                edge.select = not edge.select
        for face in bm.faces:
            if not face.hide:
                face.select = not face.select
        bm.select_flush_mode()
        update(obj)


def select_linked(context):
    """Select the whole connected component of every selected vertex."""
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        bm.verts.ensure_lookup_table()
        stack = [v for v in bm.verts if v.select and not v.hide]
        if not stack:
            continue
        visited = set(stack)
        while stack:
            vert = stack.pop()
            for edge in vert.link_edges:
                other = edge.other_vert(vert)
                if other not in visited and not other.hide:
                    visited.add(other)
                    other.select = True
                    stack.append(other)
        bm.select_flush_mode()
        update(obj)


def merge_selected(context, dist=1e-4):
    removed = 0
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        verts = [v for v in bm.verts if v.select and not v.hide]
        if len(verts) < 2:
            continue
        before = len(bm.verts)
        try:
            bmesh.ops.remove_doubles(bm, verts=verts, dist=dist)
        except Exception:  # noqa: BLE001
            continue
        removed += before - len(bm.verts)
        bm.select_flush_mode()
        update(obj)
    return removed


def delete_selected(context):
    removed = 0
    for obj in objects_in_edit(context):
        bm = bm_for(obj)
        verts = [v for v in bm.verts if v.select and not v.hide]
        if not verts:
            continue
        removed += len(verts)
        try:
            bmesh.ops.delete(bm, geom=verts, context="VERTS")
        except Exception:  # noqa: BLE001
            continue
        update(obj)
    return removed