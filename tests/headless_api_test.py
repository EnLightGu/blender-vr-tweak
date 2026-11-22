# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless self-test for the VR Tweak automation API.

Run with the add-on on ``sys.path`` (installed extension or a staged copy)::

    blender --background --factory-startup --python tests/headless_api_test.py

Prints one line per check and exits non-zero on the first failure.
"""
import importlib
import json
import sys

import bmesh
import bpy
from mathutils import Quaternion, Vector

Candidate = ("blender_vr_tweak", "bl_ext.user_default.blender_vr_tweak")
package = None
api = None
for name in Candidate:
    try:
        pkg = importlib.import_module(name)
        api_mod = importlib.import_module(name + ".api")
        package, api = pkg, api_mod
        break
    except Exception:  # noqa: BLE001
        continue
if package is None or api is None:
    raise SystemExit("VR Tweak module (with api.py) not found on sys.path")

registered = getattr(bpy.context.preferences.addons, "get", lambda _k: None)
if package.__name__ not in bpy.context.preferences.addons:
    try:
        package.register()
    except Exception:  # noqa: BLE001
        pass

failures = []


def check(name, condition, detail=""):
    ok = bool(condition)
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def make_cube():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh_data = bpy.data.meshes.new("test_cube")
    obj = bpy.data.objects.new("test_cube", mesh_data)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh_data)
    bm.free()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def main():
    make_cube()
    check("enter_edit", api.enter_edit() is True, bpy.context.mode)

    check("select_all", api.select_all() == 8, api.status()["selected_verts"])
    check("deselect_all", api.deselect_all() == 0)
    check("invert", api.invert_selection() == 8)
    check("select_linked", api.select_linked() == 8)

    api.deselect_all()
    picked = api.pick((0.5, 0.5, 0.5), 0.3)
    check("pick", picked is not None, picked)
    count = api.select_sphere((0.5, 0.5, 0.5), 0.3)
    check("select_sphere", count >= 1, count)

    before = api.status()["selected_verts"]
    api.translate_selection((0.1, 0.0, 0.0))
    check("translate", api.status()["selected_verts"] == before)
    check("undo", api.undo_once() is True)
    check("redo", api.redo_once() is True)
    check("smooth", api.smooth_selection(0.5, 1) is True)
    check("merge", isinstance(api.merge_selected(1e-4), int))

    api.deselect_all()

    # --- two-hand view: same math as VR, must not drift when hands stop ---
    api.sim_reset()
    handle = api.two_hand_begin()
    last = None
    for angle in (10, 20, 30, 40):
        last = api.two_hand_to(handle, angle)
        check("two_hand_%d" % angle, abs(last["hand_angle_deg"] - angle) < 0.5, last)
    hold = api.two_hand_to(handle, 40)
    check("no_drift_rotation", abs(hold["nav_rotation_deg"] - last["nav_rotation_deg"]) < 0.01,
          {"before": last["nav_rotation_deg"], "after": hold["nav_rotation_deg"]})
    check("nav_matches_hands", abs(hold["nav_rotation_deg"] - 40.0) < 0.5, hold["nav_rotation_deg"])
    api.two_hand_to(handle, 55)
    check("two_hand_55", abs(api.two_hand_to(handle, 55)["hand_angle_deg"] - 55.0) < 0.5)

    # --- panel dispatch ---
    api.enter_edit()
    api.deselect_all()
    check("panel_buttons", "select_all" in api.panel_buttons(), api.panel_buttons())
    check("panel_click_select_all", api.panel_click("select_all") is True and api.status()["selected_verts"] == 8,
          api.status()["selected_verts"])
    check("panel_click_deselect", api.panel_click("deselect") is True and api.status()["selected_verts"] == 0)
    check("panel_click_invert", api.panel_click("invert") is True and api.status()["selected_verts"] == 8)

    print("STATUS " + json.dumps(api.status(), ensure_ascii=False))
    if failures:
        print("FAILURES " + ", ".join(failures))
        sys.exit(1)
    print("ALL_OK")


main()
