# SPDX-License-Identifier: GPL-3.0-or-later
"""VR-local undo stack.

Snapshots are bmesh vertex coordinates, never obj.data.copy(): in edit mode
that copy is stale (P0 benchmark). Topology snapshots will use bm.to_mesh().
"""
import bpy

from . import mesh

_LIMIT = 50
_undo = []
_redo = []


def clear():
    _undo.clear()
    _redo.clear()


def push_base(context, base_map):
    """Store before/after coordinates for any vertex edit."""
    before = {}
    after = {}
    for obj in mesh.objects_in_edit(context):
        base = base_map.get(obj.name)
        if not base:
            continue
        bm = mesh.bm_for(obj)
        bm.verts.ensure_lookup_table()
        before[obj.name] = {i: v.copy() for i, v in base.items()}
        after[obj.name] = {
            i: bm.verts[i].co.copy()
            for i in base
            if bm.verts[i].is_valid
        }
    if before:
        _undo.append(("VERTS", before, after))
        _redo.clear()
        while len(_undo) > _LIMIT:
            _undo.pop(0)


def push_translate(context, translate):
    return push_base(context, translate.base)


def _apply(data):
    changed = False
    for obj_name, coords in data.items():
        obj = bpy.data.objects.get(obj_name)
        if obj is None or obj.type != "MESH" or obj.mode != "EDIT":
            continue
        bm = mesh.bm_for(obj)
        bm.verts.ensure_lookup_table()
        for index, co in coords.items():
            vert = bm.verts[index]
            if vert.is_valid:
                vert.co = co.copy()
                changed = True
        mesh.update(obj)
    return changed


def undo(context):
    if not _undo:
        return False
    kind, before, after = _undo.pop()
    if kind == "VERTS" and _apply(before):
        _redo.append((kind, before, after))
        return True
    return False


def redo(context):
    if not _redo:
        return False
    kind, before, after = _redo.pop()
    if kind == "VERTS" and _apply(after):
        _undo.append((kind, before, after))
        return True
    return False


def can_undo():
    return bool(_undo)


def can_redo():
    return bool(_redo)
