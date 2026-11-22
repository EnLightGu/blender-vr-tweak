# SPDX-License-Identifier: GPL-3.0-or-later
"""Programmatic API for VR Tweak: drive the add-on without VR controllers.

Two use cases:

* **AI / automation** - call the same operations the panel buttons and the
  brush use, from Python (BlenderMCP, scripts, tests).
* **Headless testing** - the ``sim_*`` and ``two_hand_*`` helpers reproduce the
  two-hand view math on a fake navigation state, so the interesting behaviour
  can be tested without a headset.

Quick start inside Blender (empty scene, any mode)::

    import importlib
    api = importlib.import_module("bl_ext.user_default.blender_vr_tweak.api")
    api.enter_edit()
    api.select_all()
    print(api.status())

Notes:
* Edit-mode operations need a mesh in edit mode; everything is bmesh based.
* ``sim_reset()`` gives a fake navigation state (the XR session state is not
  required), ``two_hand_begin()`` / ``two_hand_to()`` replay hand rotation.
* ``panel_click("select_all")`` runs the same dispatch table as the VR panel.
"""
import math

import bpy
from mathutils import Quaternion, Vector

from . import mesh, panel, session, undo


class SimNav:
    """Stand-in for ``window_manager.xr_session_state`` used by the sim helpers."""

    def __init__(self):
        self.navigation_location = Vector((0.0, 0.0, 0.0))
        self.navigation_rotation = Quaternion()
        self.navigation_scale = 1.0
        self.viewer_pose_location = Vector((0.0, 0.0, 1.6))
        self.viewer_pose_rotation = Quaternion()


_NAV = SimNav()


# ---------------------------------------------------------------------------
# Simulation state
# ---------------------------------------------------------------------------

def sim_reset():
    """Reset the fake navigation state and return it."""
    global _NAV
    _NAV = SimNav()
    return _NAV


def sim_nav():
    return _NAV


def sim_viewer(location=None, rotation=None):
    """Place the fake viewer (head) pose."""
    if location is not None:
        _NAV.viewer_pose_location = Vector(location)
    if rotation is not None:
        _NAV.viewer_pose_rotation = Quaternion(rotation)
    return _NAV


def status():
    """Snapshot of the add-on state (safe to call from anywhere)."""
    context = bpy.context
    settings = getattr(context.scene, "vrtweak", None)
    selection = mesh.selection(context)
    if context.tool_settings.mesh_select_mode[0]:
        select_mode = "VERT"
    elif context.tool_settings.mesh_select_mode[1]:
        select_mode = "EDGE"
    else:
        select_mode = "FACE"
    return {
        "mode": context.mode,
        "select_mode": select_mode,
        "edit_objects": [obj.name for obj in mesh.objects_in_edit(context)],
        "selected_verts": sum(len(verts) for verts in selection.values()),
        "status": settings.status if settings is not None else "",
        "panel_buttons": [key for key, _label, _col, _row in panel.BUTTONS],
        "nav_location": [round(v, 4) for v in _NAV.navigation_location],
        "nav_rotation_deg": round(math.degrees(_NAV.navigation_rotation.angle), 3),
        "nav_scale": round(_NAV.navigation_scale, 4),
    }


# ---------------------------------------------------------------------------
# Edit mode / selection
# ---------------------------------------------------------------------------

def enter_edit():
    return mesh.try_enter_edit(bpy.context)


def leave_edit():
    mesh.leave_edit(bpy.context)
    return bpy.context.mode


def select_all():
    mesh.select_all(bpy.context)
    return status()["selected_verts"]


def deselect_all():
    mesh.deselect_all(bpy.context)
    return status()["selected_verts"]


def invert_selection():
    mesh.invert_selection(bpy.context)
    return status()["selected_verts"]


def select_linked():
    mesh.select_linked(bpy.context)
    return status()["selected_verts"]


def merge_selected(dist=1e-4):
    return mesh.merge_selected(bpy.context, dist)


def delete_selected():
    return mesh.delete_selected(bpy.context)


def smooth_selection(strength=None, iterations=2):
    settings = bpy.context.scene.vrtweak
    value = settings.smooth_strength if strength is None else float(strength)
    mesh.smooth_selection(bpy.context, value, iterations)
    return True


def pick(point, radius=0.02):
    """Nearest element under a world-space point: {"object","kind","index"} or None."""
    obj, kind, index, distance = mesh.pick_element(bpy.context, Vector(point), radius)
    if obj is None:
        return None
    return {"object": obj.name, "kind": kind, "index": index, "distance": round(distance, 4)}


def select_sphere(point, radius=0.05, additive=True):
    """Brush-select everything inside a world-space sphere (returns count)."""
    return mesh.brush_select(bpy.context, Vector(point), float(radius), additive)


def translate_selection(delta):
    """Move the selected vertices by a world delta (pushes one undo step)."""
    context = bpy.context
    translate = mesh.Translate()
    if not translate.begin(context):
        return 0
    translate.apply(context, Vector(delta))
    undo.push_translate(context, translate)
    return status()["selected_verts"]


def scale_selection(factor):
    """Scale the selected vertices around their local center (pushes undo)."""
    context = bpy.context
    scale = mesh.Scale()
    if not scale.begin(context):
        return False
    scale.apply(context, float(factor))
    undo.push_base(context, scale.base)
    return True


def undo_once():
    return undo.undo(bpy.context)


def redo_once():
    return undo.redo(bpy.context)


# ---------------------------------------------------------------------------
# Two-hand view (replays the real VR math)
# ---------------------------------------------------------------------------

def _nav_world(base):
    nav = _NAV
    return (Quaternion(nav.navigation_rotation) @ Vector(base)) * float(nav.navigation_scale) + Vector(nav.navigation_location)


def two_hand_begin(angle_deg=0.0, span=0.2, height=1.2):
    """Start a synthetic two-hand grab with tips at +/-span around local Z.

    ``angle_deg`` rotates both hands about the vertical axis in base space.
    The returned handle can be fed to :func:`two_hand_to`.
    """
    nav = _NAV
    rotation = Quaternion(Vector((0.0, 0.0, 1.0)), math.radians(angle_deg))
    left = _nav_world(rotation @ Vector((-span, 0.0, height)))
    right = _nav_world(rotation @ Vector((span, 0.0, height)))
    nav_rot = Quaternion(nav.navigation_rotation)
    nav_loc = Vector(nav.navigation_location)
    scale = max(float(nav.navigation_scale), 1e-6)
    inverse = nav_rot.inverted()
    left_base = inverse @ (left - nav_loc) / scale
    right_base = inverse @ (right - nav_loc) / scale
    pinch = {
        "handler": None,
        "start_dist": max((left - right).length, 1e-4),
        "start_mid": (left + right) * 0.5,
        "nav_loc": nav_loc,
        "nav_scale": scale,
        "nav_rot": nav_rot,
        "viewer": Vector(nav.viewer_pose_location),
        "axis": (right - left).normalized(),
        "base_mid": (left_base + right_base) * 0.5,
        "base_axis": (right_base - left_base).normalized(),
        "base_viewer": inverse @ (Vector(nav.viewer_pose_location) - nav_loc) / scale,
        "angle": 0.0,
    }
    return {"pinch": pinch, "span": span, "height": height, "angle_deg": angle_deg}


def two_hand_to(handle, angle_deg):
    """Rotate both synthetic hands to ``angle_deg`` and apply the view transform."""
    nav = _NAV
    span = handle.get("span", 0.2)
    height = handle.get("height", 1.2)
    rotation = Quaternion(Vector((0.0, 0.0, 1.0)), math.radians(angle_deg))
    left = _nav_world(rotation @ Vector((-span, 0.0, height)))
    right = _nav_world(rotation @ Vector((span, 0.0, height)))
    hand_rot = session.apply_two_hand_view(handle["pinch"], left, right, nav, False)
    handle["angle_deg"] = angle_deg
    return {
        "hand_angle_deg": round(math.degrees(hand_rot.angle), 3) if hand_rot is not None else 0.0,
        "nav_rotation_deg": round(math.degrees(Quaternion(nav.navigation_rotation).angle), 3),
        "nav_location": [round(v, 4) for v in nav.navigation_location],
    }


def move_view(delta):
    """Shift the (fake) viewer by a world-space delta; returns its new location."""
    nav = _NAV
    nav.navigation_location = Vector(nav.navigation_location) + Vector(delta)
    return [round(v, 4) for v in nav.navigation_location]


# ---------------------------------------------------------------------------
# Floating panel
# ---------------------------------------------------------------------------

def select_mode(mode):
    return mesh.set_select_mode(bpy.context, str(mode).upper())


def subdivide_selected(cuts=1):
    return mesh.subdivide_selected(bpy.context, int(cuts))


def extrude_selected(distance=0.02):
    return mesh.extrude_selected(bpy.context, float(distance))


def flip_normals_selected():
    return mesh.flip_normals_selected(bpy.context)


def go_to_page(key):
    panel.go_to_page(key)
    return panel.page_key()


def panel_page():
    return panel.page_key()


def panel_buttons():
    return [item[0] for _key, _title, items in panel.PAGES for item in items]


def panel_click(button_id):
    """Run the same code path as clicking a panel button in VR."""
    dispatch = session._panel_dispatch(bpy.context)
    action = dispatch.get(button_id)
    if action is None:
        return False
    action(bpy.context)
    return True


# ---------------------------------------------------------------------------
# Real VR session (needs a 3D viewport + a running OpenXR runtime)
# ---------------------------------------------------------------------------

def _view3d_context():
    context = bpy.context
    area = getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        screen = getattr(context, "screen", None)
        area = next((a for a in screen.areas if a.type == "VIEW_3D"), None) if screen else None
    if area is None:
        return None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    window = getattr(context, "window", None) or bpy.context.window
    return window, area, region


def start_vr():
    """Start the XR session (same as the panel button); returns True on success."""
    found = _view3d_context()
    if found is None:
        return False
    window, area, region = found
    with bpy.context.temp_override(window=window, area=area, region=region):
        session.start(bpy.context)
    return True


def stop_vr():
    found = _view3d_context()
    if found is None:
        return False
    window, area, region = found
    with bpy.context.temp_override(window=window, area=area, region=region):
        session.stop(bpy.context)
    return True
