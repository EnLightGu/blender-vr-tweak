# SPDX-License-Identifier: GPL-3.0-or-later
"""P0/P1 session: XR input, tip brush, select + move + undo.

All geometry writes go through bmesh (mesh.py); undo stores bmesh coordinates.
"""
import math
import os
import tempfile
import time

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import actions, mesh, overlay, panel, tip, undo

LOG_PATH = os.path.join(tempfile.gettempdir(), "vrtweak-input.log")

_STATE = {
    "timer": None,
    "last": 0.0,
    "trigger_r": False,
    "squeeze_r": False,
    "squeeze_l": False,
    "grabbing": False,
    "grab_start": None,
    "translate": None,
    "turn_armed": True,
    "stick_click_l": False,
    "pinch": None,
    "smoothing": False,
    "smooth_base": None,
    "a_click": False,
    "b_click": False,
    "x_click": False,
    "hud": None,
    "preselect": None,
    "sel": ((), (), ()),
    "sel_t": 0.0,
    "mode_name": "VERT",
    "panel_visible": True,
    "ui_hover": False,
    "y_click": False,
    "view_placed": False,
    "ensure_t": 0.0,
    "ensure_tries": 0,
    "debug": None,
    "not_running": 0,
}



def _ensure_hud(context):
    if _STATE["hud"] is not None:
        return _STATE["hud"]
    try:
        curve = bpy.data.curves.new("vrtweak_hud", "FONT")
        curve.body = ""
        curve.size = 0.045
        for font_path in (
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ):
            if os.path.exists(font_path):
                try:
                    curve.font = bpy.data.fonts.load(font_path)
                    break
                except Exception:  # noqa: BLE001
                    continue
        obj = bpy.data.objects.new("vrtweak_hud", curve)
        obj.hide_select = True
        obj.hide_render = True
        context.scene.collection.objects.link(obj)
        _STATE["hud"] = obj
        return obj
    except Exception:  # noqa: BLE001
        return None


def _update_hud(context, text, tint=(1.0, 1.0, 1.0, 1.0)):
    obj = _STATE["hud"]
    if obj is None:
        return
    try:
        obj.data.body = text
        obj.data.materials.clear()
        mat = bpy.data.materials.get("vrtweak_hud_mat")
        if mat is None:
            mat = bpy.data.materials.new("vrtweak_hud_mat")
            mat.use_nodes = True
            bsdf = next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
            if bsdf:
                bsdf.inputs["Base Color"].default_value = tint
                bsdf.inputs["Emission Color"].default_value = tint
                bsdf.inputs["Emission Strength"].default_value = 2.0
        obj.data.materials.append(mat)
        state = context.window_manager.xr_session_state
        loc = Vector(state.viewer_pose_location)
        rot = Quaternion(state.viewer_pose_rotation)
        forward = rot @ Vector((0.0, 0.0, -1.0))
        right = rot @ Vector((1.0, 0.0, 0.0))
        up = rot @ Vector((0.0, 1.0, 0.0))
        obj.location = loc + forward * 0.6 - right * 0.22 + up * 0.16
        obj.rotation_euler = (loc - obj.location).to_track_quat("Z", "Y").to_euler()
    except Exception:  # noqa: BLE001
        pass


def _remove_hud():
    obj, _STATE["hud"] = _STATE["hud"], None
    if obj is not None:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:  # noqa: BLE001
            pass


def _stick(context, hand):
    """Stick vector with the per-axis panel inversion applied."""
    x, y = actions.vector(context, "stick", hand)
    settings = context.scene.vrtweak
    if actions.session_pre not in bpy.app.handlers.xr_session_start_pre:
        bpy.app.handlers.xr_session_start_pre.append(actions.session_pre)
    if settings.invert_stick_x:
        x = -x
    if settings.invert_stick_y:
        y = -y
    return Vector((x, y))


def _move_speed(context, state):
    """User speed scaled like Blender's own VR fly navigation."""
    settings = context.scene.vrtweak
    scale = 1.0
    try:
        scale = float(state.navigation_scale)
    except Exception:  # noqa: BLE001
        pass
    try:
        scale *= float(context.window_manager.xr_session_settings.base_scale)
    except Exception:  # noqa: BLE001
        pass
    return settings.move_speed * max(0.05, min(10.0, scale))


def _stick_delta(rotation, stick, dt, speed):
    amount = Vector((stick[0], stick[1]))
    magnitude = amount.length
    if magnitude <= 0.15:
        return Vector()
    forward = rotation @ Vector((0.0, 0.0, -1.0))
    forward.z = 0.0
    if forward.length < 1e-6:
        right = rotation @ Vector((1.0, 0.0, 0.0))
        right.z = 0.0
        if right.length < 1e-6:
            return Vector()
        forward = Vector((0.0, 0.0, 1.0)).cross(right.normalized())
    forward.normalize()
    right = forward.cross(Vector((0.0, 0.0, 1.0)))
    strength = (min(magnitude, 1.0) - 0.15) / 0.85
    amount *= strength / magnitude
    return (right * amount.x + forward * amount.y) * min(max(dt, 0.0), 0.1) * speed


def _turn(state, angle_deg):
    turn = Quaternion(Vector((0.0, 0.0, 1.0)), math.radians(angle_deg))
    offset = Vector(state.navigation_location)
    pivot = Vector(state.viewer_pose_location)
    relative = pivot - offset
    state.navigation_location = offset + relative - turn @ relative
    state.navigation_rotation = turn @ Quaternion(state.navigation_rotation)


def _navigate(context, state, dt):
    settings = context.scene.vrtweak
    stick = _stick(context, 0)
    speed = _move_speed(context, state)
    rotation = Quaternion(state.viewer_pose_rotation)
    if settings.vertical_move:
        right = rotation @ Vector((1.0, 0.0, 0.0))
        right.z = 0.0
        if right.length > 1e-6:
            right.normalize()
        strength = min(stick.length, 1.0) - 0.15
        amount = (max(strength, 0.0) / 0.85) if stick.length > 0.15 else 0.0
        name = stick.normalized() if stick.length > 1e-6 else Vector((0.0, 0.0))
        delta = (right * name.x + Vector((0.0, 0.0, 1.0)) * name.y) * amount * dt * speed
    else:
        delta = _stick_delta(rotation, stick, dt, speed)
    if delta.length:
        state.navigation_location = Vector(state.navigation_location) + delta
    # Right stick Y: pitch the world around the right controller, not around the
    # head: w' = P + q * (w - P) with P = right hand grip position.
    pitch_stick = _stick(context, 1).y
    if abs(pitch_stick) > 0.15:
        angle = math.radians(settings.turn_angle) * pitch_stick * dt * 2.5
        pivot = Vector(actions.pose(context, 1)[0] or state.viewer_pose_location)
        right_axis = rotation @ Vector((1.0, 0.0, 0.0))
        pitch_q = Quaternion(right_axis, angle)
        nav_rot = Quaternion(state.navigation_rotation)
        nav_loc = Vector(state.navigation_location)
        state.navigation_rotation = pitch_q @ nav_rot
        state.navigation_location = pivot + pitch_q @ (nav_loc - pivot)
    turn_stick = _stick(context, 1).x
    if abs(turn_stick) > 0.65:
        if _STATE["turn_armed"]:
            _STATE["turn_armed"] = False
            _turn(state, -math.copysign(settings.turn_angle, turn_stick))
    else:
        _STATE["turn_armed"] = True


def _is_running(context):
    try:
        return bpy.types.XrSessionState.is_running(context)
    except Exception:  # noqa: BLE001
        return False


def _toggle(context):
    area = getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        area = next((a for a in context.screen.areas if a.type == "VIEW_3D"), None)
    if area is None:
        raise RuntimeError("Open a 3D view first")
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    window = getattr(context, "window", None) or bpy.context.window
    result = None
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            result = bpy.ops.wm.xr_session_toggle()
    except Exception as exc:  # noqa: BLE001
        result = f"EXC {exc!r}"
        raise
    finally:
        try:
            with open(LOG_PATH + ".toggle", "a", encoding="utf-8") as fh:
                fh.write("%.1f result=%s running=%s mode=%s\n" % (
                    time.time(), result, _is_running(bpy.context), bpy.context.mode))
        except Exception:  # noqa: BLE001
            pass
    return result


def _cleanup(context):
    if _STATE["grabbing"] and _STATE["translate"] is not None:
        try:
            _STATE["translate"].cancel(context)
        except Exception:  # noqa: BLE001
            pass
    _STATE["grabbing"] = False
    _STATE["translate"] = None
    if _STATE["timer"] is not None:
        try:
            bpy.app.timers.unregister(_STATE["timer"])
        except Exception:  # noqa: BLE001
            pass
        _STATE["timer"] = None
    panel.remove()
    overlay.remove()
    _remove_hud()
    _remove_debug()
    _remove_axis_cube()
    actions.reset()
    try:
        context.scene.vrtweak.running = False
    except Exception:  # noqa: BLE001
        pass


def _purge_stale_objects():
    """Delete vrtweak_* objects saved inside a .blend by an earlier session."""
    for obj in list(bpy.data.objects):
        if obj.name.startswith("vrtweak_"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass
    # A deleted object can still be the active one, which breaks mode_set and XR ops.
    try:
        active = bpy.context.view_layer.objects.active
        if active is None or active.name.startswith("vrtweak_"):
            candidate = next(
                (o for o in bpy.context.scene.objects
                 if o.type == "MESH" and not o.name.startswith("vrtweak_")),
                None,
            )
            bpy.context.view_layer.objects.active = candidate
    except Exception:  # noqa: BLE001
        pass




def _remove_debug():
    obj = _STATE.get("debug")
    _STATE["debug"] = None
    if obj is None:
        return
    try:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.curves.remove(data)
    except Exception:  # noqa: BLE001
        pass


def _ensure_debug(context):
    if _STATE.get("debug") is not None:
        return _STATE["debug"]
    try:
        curve = bpy.data.curves.new("vrtweak_debug", "FONT")
        curve.size = 0.010
        curve.align_x = "LEFT"
        curve.align_y = "TOP"
        curve.space_line = 0.9
        for font_path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
            if os.path.exists(font_path):
                try:
                    curve.font = bpy.data.fonts.load(font_path)
                except Exception:  # noqa: BLE001
                    pass
                break
        curve.materials.append(overlay._material("vrtweak_debug_mat", (1.0, 1.0, 1.0, 1.0), 1.0))
        obj = bpy.data.objects.new("vrtweak_debug", curve)
        context.scene.collection.objects.link(obj)
        obj.hide_select = True
        obj.hide_render = False
        obj.show_in_front = True
        obj.rotation_mode = "QUATERNION"
        _STATE["debug"] = obj
        return obj
    except Exception:  # noqa: BLE001
        return None


def _update_debug(context, lines, state):
    """Pin the debug text to the top-left of the viewer's field of view."""
    obj = _STATE.get("debug") or _ensure_debug(context)
    if obj is None or state is None:
        return
    try:
        rot = Quaternion(state.viewer_pose_rotation)
        loc = Vector(state.viewer_pose_location)
        forward = rot @ Vector((0.0, 0.0, -1.0))
        right = rot @ Vector((1.0, 0.0, 0.0))
        up = rot @ Vector((0.0, 1.0, 0.0))
        obj.data.body = "\n".join(lines)
        obj.location = loc + forward * 1.0 + right * (-0.55) + up * 0.32
        obj.rotation_quaternion = rot
        obj.hide_viewport = False
    except Exception:  # noqa: BLE001
        pass

def _register_xr_handler():
    """Loading a .blend clears Python XR handlers, so register it again on start."""
    try:
        if actions.session_pre not in bpy.app.handlers.xr_session_start_pre:
            bpy.app.handlers.xr_session_start_pre.append(actions.session_pre)
    except Exception:  # noqa: BLE001
        pass


def _begin(context):
    settings = context.scene.vrtweak
    try:
        context.window_manager.xr_session_settings.controller_draw_style = "LIGHT"
    except Exception:  # noqa: BLE001
        pass
    for suffix in (".hb", ".err"):
        try:
            os.remove(LOG_PATH + suffix)
        except OSError:
            pass
    overlay.add(context)
    panel.add(context)
    _ensure_hud(context)
    _ensure_debug(context)
    _ensure_axis_cube(context)
    _STATE.update({
        "last": 0.0,
        "trigger_r": False,
        "squeeze_r": False,
        "squeeze_l": False,
        "grabbing": False,
        "grab_start": None,
        "translate": None,
        "view_placed": False,
        "ensure_tries": 0,
        "started_at": time.time(),
    })
    _STATE["timer"] = bpy.app.timers.register(tick, first_interval=0.05, persistent=True)
    settings.running = True
    settings.status = "运行中 / running"


def _restart_session():
    """Reopen the XR session so that xr_session_start_pre runs again."""
    context = bpy.context
    try:
        _register_xr_handler()
        actions.reset()
        _toggle(context)
        _begin(context)
    except Exception as exc:  # noqa: BLE001
        context.scene.vrtweak.status = f"重启失败 / restart failed: {exc}"
    return None


def start(context):
    overlay.remove()
    panel.remove()
    _purge_stale_objects()
    settings = context.scene.vrtweak
    undo.clear()
    with open(LOG_PATH, "w", encoding="utf-8") as handle:
        handle.write("# vrtweak input log\n")
    actions.reset()
    _register_xr_handler()
    running = _is_running(context)
    if running and actions.ready():
        _begin(context)          # already healthy: just attach
        if not mesh.try_enter_edit(context):
            settings.status = "view only / 仅查看（左Y → 编辑）"
        return
    if running:
        # A stale session was opened by something else: the action set can only be
        # built in xr_session_start_pre, so close and reopen it (about half a second).
        settings.status = "重启连接 / reopening session"
        try:
            _toggle(context)
        except Exception:  # noqa: BLE001
            pass
        bpy.app.timers.register(_restart_session, first_interval=0.6, persistent=True)
        return
    _toggle(context)
    _begin(context)
    # Edit mode only after the session exists: switching mode first made the XR
    # toggle return without opening a session.
    if not mesh.try_enter_edit(context):
        settings.status = "view only / 仅查看（左Y → 编辑）"


def stop(context):
    _cleanup(context)
    if _is_running(context):
        try:
            _toggle(context)
        except Exception:  # noqa: BLE001
            pass
    mesh.leave_edit(context)
    try:
        context.scene.vrtweak.status = "stopped"
    except Exception:  # noqa: BLE001
        pass


def _toast(text):
    """Spawn a short-lived text object in front of the viewer."""
    try:
        context = bpy.context
        scene = context.scene
        curve = bpy.data.curves.new("vrtweak_toast", "FONT")
        curve.body = text
        curve.size = 0.06
        obj = bpy.data.objects.new("vrtweak_toast", curve)
        scene.collection.objects.link(obj)
        state = context.window_manager.xr_session_state
        loc = Vector(state.viewer_pose_location)
        rot = Quaternion(state.viewer_pose_rotation)
        forward = rot @ Vector((0.0, 0.0, -1.0))
        up = rot @ Vector((0.0, 1.0, 0.0))
        obj.location = loc + forward * 0.55 + up * 0.12
        obj.rotation_euler = (loc - obj.location).to_track_quat("Z", "Y").to_euler()

        def _remove():
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass
            return None

        bpy.app.timers.register(_remove, first_interval=2.0, persistent=False)
    except Exception:  # noqa: BLE001
        pass


def _haptic(context, hand=1, amplitude=0.6):
    try:
        state = context.window_manager.xr_session_state
        state.haptic_action_apply(context, actions.SET, "haptic",
                                  actions.HANDS[hand], 0.05, 0.0, amplitude)
    except Exception:  # noqa: BLE001
        pass


def _save_async():
    try:
        if bpy.data.filepath:
            bpy.ops.wm.save_mainfile()
        else:
            path = os.path.expanduser("~/Desktop/vr-tweak-autosave.blend")
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        print("VR TWEAK saved")
        _toast("已保存")
        _haptic(bpy.context, 1, 0.8)
    except Exception as exc:  # noqa: BLE001
        print("VR TWEAK save failed:", exc)
        _toast("保存失败")
    return None


def _fmt(value):
    return f"{value:+.3f}"


def _log_line(context, hand, label):
    settings = context.scene.vrtweak
    tip_loc, grip_loc = tip.read(context, hand, settings.tip_offset, settings.tip_source)
    sel = mesh.selection(context)
    count = sum(len(v) for v in sel.values())
    parts = [
        label,
        f"grip={tuple(round(v, 3) for v in grip_loc) if grip_loc else None}",
        f"tip={tuple(round(v, 3) for v in tip_loc) if tip_loc else None}",
        f"trg={_fmt(actions.value(context, 'trigger', hand))}",
        f"sq={_fmt(actions.value(context, 'squeeze', hand))}",
        f"stick={tuple(round(v, 2) for v in actions.vector(context, 'stick', hand))}",
        f"sel={count}",
        f"grab={_STATE['grabbing']}",
        f"pinch={(_STATE['pinch'].get('angle', 0.0) if _STATE['pinch'] else 0.0):.1f}",
    ]
    return " ".join(parts)


def _queue_save():
    bpy.app.timers.register(_save_async, first_interval=0.01)




_AXIS = {}


def _axis_label(name, body, x, y, z, rot):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = 0.020
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    for font_path in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"):
        if os.path.exists(font_path):
            try:
                cu.font = bpy.data.fonts.load(font_path)
            except Exception:  # noqa: BLE001
                pass
            break
    cu.materials.append(overlay._material("vrtweak_axistext_mat", (1.0, 1.0, 1.0, 1.0), 1.5))
    obj = bpy.data.objects.new(name, cu)
    obj.color = (1.0, 1.0, 1.0, 1.0)
    obj.location = (x, y, z)
    return obj


def _make_hand_box(context, name, color, size=(0.032, 0.032, 0.070)):
    sx, sy, sz = size
    mesh = bpy.data.meshes.new(name)
    verts = [(x * sx, y * sy, z * sz) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(overlay._material(name + "_mat", color, 1.0))
    obj = bpy.data.objects.new(name, mesh)
    obj.color = color
    obj.hide_select = True
    obj.hide_render = False
    context.scene.collection.objects.link(obj)
    return obj


def _ensure_axis_cube(context):
    return None


def _update_axis_cube(context, hand=0):
    """Draw a solid box on both controllers (covers Blender's fallback spheres)."""
    if _AXIS.get("left") is None:
        _ensure_axis_cube(context)
    try:
        state = context.window_manager.xr_session_state
        if state is None:
            return
        for index, key in ((0, "left"), (1, "right")):
            obj = _AXIS.get(key)
            if obj is None:
                continue
            loc = Vector(state.controller_grip_location_get(context, index))
            rot = state.controller_grip_rotation_get(context, index)
            if rot is None or loc.length < 1e-4:
                pose = actions.pose(context, index)
                if pose[0] is None or pose[1] is None:
                    obj.hide_viewport = True
                    continue
                loc = Vector(pose[0])
                rot = pose[1]
            quat = Quaternion(rot)
            world = Matrix.Translation(loc) @ quat.to_matrix().to_4x4()
            obj.matrix_world = world
            obj.hide_viewport = False
            if key == "left" and (time.time() - _STATE.get("started_at", time.time())) < 20.0:
                billboard = Quaternion(state.viewer_pose_rotation).to_matrix().to_4x4()
                for index in range(6):
                    item = _AXIS.get("lbl_%d" % index)
                    if item is None:
                        continue
                    label, offset = item
                    label.matrix_world = Matrix.Translation(world @ offset) @ billboard
                    label.hide_viewport = False
    except Exception as exc:  # noqa: BLE001
        import traceback
        _axis_log("EXC %r\n%s" % (exc, traceback.format_exc()))


def _hide_axis_labels():
    return


def _remove_axis_cube():
    for key in ("left", "right"):
        obj = _AXIS.pop(key, None)
        if obj is None:
            continue
        data = getattr(obj, "data", None)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        except Exception:  # noqa: BLE001
            pass


def _axis_log(text):
    try:
        with open(LOG_PATH + ".axis", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:  # noqa: BLE001
        pass



def _place_view(context):
    """Put the viewer 2 m in front of the origin, looking at it (once per session)."""
    try:
        state = context.window_manager.xr_session_state
        if state is None:
            return False
        view_loc = Vector(state.viewer_pose_location)
        if view_loc.length < 0.1:
            # Tracking has not produced a real pose yet: retry on the next frame,
            # otherwise the navigation gets a bogus offset and the view ends up far.
            return False
        view_rot = Quaternion(state.viewer_pose_rotation)
        nav_loc = Vector(state.navigation_location)
        nav_rot = Quaternion(state.navigation_rotation)
        base_rot = nav_rot.inverted() @ view_rot
        target_loc = Vector((0.0, -2.0, 1.7))
        target_rot = (Vector((0.0, 0.0, 0.0)) - target_loc).to_track_quat("-Z", "Y")
        new_nav_rot = target_rot @ base_rot.inverted()
        offset = nav_rot.inverted() @ (view_loc - nav_loc)
        state.navigation_rotation = new_nav_rot
        state.navigation_location = target_loc - new_nav_rot @ offset
        state.navigation_scale = 1.0
        context.scene.vrtweak.status = "视角已归位 / view placed"
        return True
    except Exception:  # noqa: BLE001
        return False


def _reset_view(context):
    state = context.window_manager.xr_session_state
    if state is None:
        return False
    state.navigation_location = Vector((0.0, 0.0, 0.0))
    state.navigation_rotation = Quaternion()
    state.navigation_scale = 1.0
    return True


def _set_panel_visible(visible):
    _STATE["panel_visible"] = bool(visible)
    if not visible:
        panel.hide()
    return _STATE["panel_visible"]


def _panel_dispatch(context):
    """Map floating-panel button ids to mesh operations."""
    settings = context.scene.vrtweak

    def wrap(action, label):
        def _run(ctx):
            try:
                result = action(ctx)
                settings.status = f"panel: {label}"
                return result
            except Exception as exc:  # noqa: BLE001
                settings.status = f"panel {label} 失败: {exc}"
                return None
        return _run

    return {
        "select_all": wrap(mesh.select_all, "全选"),
        "deselect": wrap(mesh.deselect_all, "取消选择"),
        "invert": wrap(mesh.invert_selection, "反选"),
        "linked": wrap(mesh.select_linked, "选择相连"),
        "merge": wrap(mesh.merge_selected, "合并顶点"),
        "delete": wrap(mesh.delete_selected, "删除顶点"),
        "smooth": wrap(lambda ctx: mesh.smooth_selection(ctx, settings.smooth_strength, 2), "平滑"),
        "undo": wrap(lambda ctx: undo.undo(ctx), "撤销"),
        "save": wrap(lambda ctx: _queue_save(), "保存"),
        "editmode": wrap(mesh.toggle_edit_mode, "编辑模式"),
        "mode_vert": wrap(lambda ctx: mesh.set_select_mode(ctx, "VERT"), "顶点模式"),
        "mode_edge": wrap(lambda ctx: mesh.set_select_mode(ctx, "EDGE"), "边模式"),
        "mode_face": wrap(lambda ctx: mesh.set_select_mode(ctx, "FACE"), "面模式"),
        "subdivide": wrap(mesh.subdivide_selected, "细分"),
        "extrude": wrap(mesh.extrude_selected, "挤出"),
        "flip_normals": wrap(mesh.flip_normals_selected, "法线翻转"),
        "reset_view": wrap(_reset_view, "重置视角"),
        "hide_panel": wrap(lambda ctx: _set_panel_visible(False), "隐藏面板"),
        "help": wrap(lambda ctx: panel.go_to_page("help"), "帮助"),
    }


def apply_two_hand_view(pinch, left_tip, right_tip, state, invert=False):
    """Apply the two-hand view transform, measured in base space.

    Controller poses come back world-space (navigation applied), so the hand
    transform is derived in base space to avoid feeding our own navigation
    back in (that caused the endless spin, see README 5.5 6).

    Updates ``state.navigation_rotation`` / ``state.navigation_location`` and
    returns the base-space hand rotation (or None). The caller handles scale.
    """
    nav_rot_now = Quaternion(state.navigation_rotation)
    nav_loc_now = Vector(state.navigation_location)
    scale_now = max(float(state.navigation_scale), 1e-6)
    inv_rot = nav_rot_now.inverted()
    inv_scale = 1.0 / scale_now
    left_base = inv_rot @ (left_tip - nav_loc_now) * inv_scale
    right_base = inv_rot @ (right_tip - nav_loc_now) * inv_scale
    base_mid_now = (left_base + right_base) * 0.5
    delta_base = base_mid_now - pinch["base_mid"]
    base_axis_now = None
    if (right_base - left_base).length > 1e-5:
        base_axis_now = (right_base - left_base).normalized()
    hand_rot = None
    if pinch.get("base_axis") is not None and base_axis_now is not None:
        hand_rot = pinch["base_axis"].rotation_difference(base_axis_now)
    if invert:
        delta_base = -delta_base
        if hand_rot is not None:
            hand_rot = hand_rot.inverted()
    if hand_rot is not None:
        new_rot = (pinch["nav_rot"] @ hand_rot.inverted()).normalized()
    else:
        new_rot = pinch["nav_rot"].copy()
    if pinch["base_viewer"] is not None:
        new_loc = pinch["viewer"] - (new_rot @ (pinch["base_viewer"] + delta_base)) * pinch["nav_scale"]
    else:
        new_loc = nav_loc_now
    state.navigation_rotation = new_rot
    state.navigation_location = new_loc
    return hand_rot


def tick():
    """Timer entry point: never let one bad frame unregister the timer."""
    try:
        return _tick_body()
    except Exception:  # noqa: BLE001
        try:
            import traceback
            with open(LOG_PATH + ".err", "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%H:%M:%S ") + traceback.format_exc() + "\n")
        except Exception:  # noqa: BLE001
            pass
        return 0.05


def _tick_body():
    context = bpy.context
    if not _is_running(context):
        # A freshly requested session needs a few frames before is_running() flips
        # to True. Cleaning up on the first frame used to kill the timer, which left
        # the panel invisible and every button dead.
        _STATE["not_running"] = _STATE.get("not_running", 0) + 1
        if _STATE["not_running"] > 80:
            _cleanup(context)
            return None
        return 0.05
    _STATE["not_running"] = 0

    settings = context.scene.vrtweak
    settings.running = True
    state = context.window_manager.xr_session_state

    _update_axis_cube(context, 0)
    if state is not None and not _STATE.get("view_placed"):
        if _place_view(context):
            _STATE["view_placed"] = True
    if state is not None and not actions.ready():
        now_e = time.time()
        if now_e - _STATE.get("ensure_t", 0.0) > 0.5 and _STATE.get("ensure_tries", 0) < 20:
            _STATE["ensure_t"] = now_e
            _STATE["ensure_tries"] = _STATE.get("ensure_tries", 0) + 1
            try:
                if actions.ensure(context):
                    settings.status = "动作集就绪 / action set ready"
            except Exception:  # noqa: BLE001
                pass

    _STATE["frames"] = _STATE.get("frames", 0) + 1
    if time.time() - _STATE.get("hb", 0.0) > 0.5:
        _STATE["hb"] = time.time()
        try:
            with open(LOG_PATH + ".hb", "a", encoding="utf-8") as fh:
                fh.write(
                    "frames=%d ready=%s trigger=%s y=%s panel_vis=%s panel_objs=%s gripL=%s box=%s\n" % (
                        _STATE["frames"], actions.ready(),
                        actions.value(context, "trigger", 1),
                        actions.value(context, "y_click", 0),
                        _STATE.get("panel_visible"),
                        sum(1 for o in getattr(panel, "_ALL_OBJECTS", []) if not o.hide_viewport)
                        if getattr(panel, "_ALL_OBJECTS", None) else -1,
                        tuple(round(v, 2) for v in actions.pose(context, 0)[0]) if actions.pose(context, 0)[0] else None,
                        tuple(round(v, 2) for v in _AXIS["root"].matrix_world.translation) if _AXIS.get("root") else None,
                    )
                )
        except Exception:  # noqa: BLE001
            pass

    hand = 1 if settings.hand == "RIGHT" else 0
    tip_loc, grip_loc = tip.read(context, hand, settings.tip_offset, settings.tip_source)
    left_tip, _ = tip.read(context, 0, settings.tip_offset, settings.tip_source)
    right_tip, _ = tip.read(context, 1, settings.tip_offset, settings.tip_source)

    # Publish draw data for the XR draw handler. It must not touch bpy.context
    # itself (Blender 4.4.3 on Windows crashes on context.window_manager there).
    now = time.time()
    if now - _STATE["sel_t"] >= 0.1:
        _STATE["sel_t"] = now
        try:
            _STATE["sel"] = mesh.selection_geometry(context)
        except Exception:  # noqa: BLE001
            _STATE["sel"] = ((), (), ())
    _STATE["mode_name"] = (
        "VERT" if context.tool_settings.mesh_select_mode[0]
        else ("EDGE" if context.tool_settings.mesh_select_mode[1] else "FACE")
    )
    points, lines, tris = _STATE["sel"]
    try:
        overlay._prune()
    except Exception:  # noqa: BLE001
        pass
    overlay.update(
        tip=tip_loc,
        grip=grip_loc,
        radius=settings.brush_radius,
        mode=_STATE["mode_name"],
        vertical=settings.vertical_move,
        points=points,
        lines=lines,
        tris=tris,
    )

    trigger_l = actions.value(context, "trigger", 0) > 0.55
    trigger_r = actions.value(context, "trigger", 1) > 0.55

    # Floating panel (left hand) + right aim ray picking.
    y_click = actions.value(context, "y_click", 0) > 0.55
    if y_click and not _STATE["y_click"]:
        _STATE["panel_visible"] = not _STATE["panel_visible"]
        _toast("面板显示 / Panel on" if _STATE["panel_visible"] else "面板隐藏 / Panel off")
    _STATE["y_click"] = y_click
    ui = {"hover": False, "clicked": None}
    if state is not None and not (trigger_l and trigger_r):
        try:
            grip_pose = actions.pose(context, 0)
            if grip_pose[0] is None or grip_pose[1] is None:
                # action-state read can be empty; the raw controller pose is reliable
                grip_pose = (
                    Vector(state.controller_grip_location_get(context, 0)),
                    Quaternion(state.controller_grip_rotation_get(context, 0)),
                )
            aim_pose = actions.aim_pose(context, 1)
            if aim_pose[0] is None or aim_pose[1] is None:
                aim_pose = (
                    Vector(state.controller_aim_location_get(context, 1)),
                    Quaternion(state.controller_aim_rotation_get(context, 1)),
                )
            try:
                panel._prune()
            except Exception:  # noqa: BLE001
                pass
            ui = panel.update(
                context,
                viewer=Vector(state.viewer_pose_location),
                grip_loc=grip_pose[0],
                grip_rot=grip_pose[1],
                aim_loc=aim_pose[0],
                aim_rot=aim_pose[1],
                trigger=trigger_r,
                visible=_STATE["panel_visible"],
                dispatch=_panel_dispatch(context),
            )
        except Exception as exc:  # noqa: BLE001
            import traceback
            try:
                with open(LOG_PATH + ".err", "a", encoding="utf-8") as fh:
                    fh.write(traceback.format_exc() + "\n")
            except Exception:  # noqa: BLE001
                pass
            settings.status = f"panel error: {exc}"
            ui = {"hover": False, "clicked": None}
    else:
        panel.hide()
    _STATE["ui_hover"] = bool(ui.get("hover"))
    if ui.get("clicked"):
        settings.status = f"面板 / panel: {ui['clicked']}"

    try:
        squeeze_l = actions.value(context, "squeeze", 0)
        squeeze_r = actions.value(context, "squeeze", 1)
        a_click = actions.value(context, "a_click", 1)
        b_click = actions.value(context, "b_click", 1)
        x_click = actions.value(context, "x_click", 0)
        panel_objects = getattr(panel, "_ALL_OBJECTS", None)
        panel_visible = sum(1 for o in panel_objects if not o.hide_viewport) if panel_objects else -1
        _update_debug(context, [
            "VR Tweak 调试 / debug",
            f"帧 / frames {_STATE.get('frames', 0)}  动作集 / set {actions.ready()}",
            f"扳机 / trigger L{trigger_l:.2f} R{trigger_r:.2f}",
            f"握把 / grip L{squeeze_l:.2f} R{squeeze_r:.2f}",
            f"按钮 / buttons Y{int(y_click)} A{int(a_click)} B{int(b_click)} X{int(x_click)}",
            f"面板 / panel vis{int(bool(_STATE.get('panel_visible')))} objs{panel_visible} hover{int(bool(ui.get('hover')))}",
            f"左手 / gripL {tuple(round(v,2) for v in state.controller_grip_location_get(context, 0))}",
            f"方块 / box {tuple(round(v,2) for v in _AXIS['root'].matrix_world.translation) if _AXIS.get('root') else None}",
            f"状态 / status {settings.status}",
        ], state)
    except Exception:  # noqa: BLE001
        pass

    if _STATE["hud"] is not None and tip_loc is not None and not _STATE["grabbing"] and _STATE["pinch"] is None:
        if time.time() - _STATE.get("last_pick", 0.0) > 0.1:
            _STATE["last_pick"] = time.time()
            try:
                obj, kind, index, _dist = mesh.pick_element(context, tip_loc, settings.brush_radius)
                _STATE["preselect"] = (obj, kind, index) if obj is not None else None
            except Exception:  # noqa: BLE001
                _STATE["preselect"] = None
        if not mesh.objects_in_edit(context):
            text = "未进入编辑模式（左Y 面板 → 编辑/物体）"
        else:
            mode = "顶点/Vertex" if context.tool_settings.mesh_select_mode[0] else ("边/Edge" if context.tool_settings.mesh_select_mode[1] else "面/Face")
            preselect = _STATE["preselect"]
            if preselect and preselect[0] is not None:
                text = f"预选 / Preview: {preselect[0].name} / {mode}"
            else:
                text = f"预选 / Preview: 无 / none ({mode})"
        _update_hud(context, text)
    elif _STATE["hud"] is not None:
        _update_hud(context, "移动中" if _STATE["pinch"] is None else "双手操作中")
    if trigger_l and trigger_r and left_tip is not None and right_tip is not None:
        mid = (left_tip + right_tip) * 0.5
        distance = (left_tip - right_tip).length
        pinch = _STATE["pinch"]
        if pinch is None:
            handler = mesh.Pinch()
            grabbed = handler.begin(context)
            nav_rot = Quaternion(state.navigation_rotation) if state is not None else Quaternion()
            nav_loc = Vector(state.navigation_location) if state is not None else Vector()
            nav_scale = float(state.navigation_scale) if state is not None else 1.0
            viewer = Vector(state.viewer_pose_location) if state is not None else None
            base_mid = base_axis = base_viewer = None
            if state is not None:
                # Controller poses are returned world-space (navigation applied), so undo
                # the current nav transform to measure the hands in base space. Measuring
                # in world space would feed our own navigation back in (endless spin).
                inv_rot = nav_rot.inverted()
                inv_scale = 1.0 / max(nav_scale, 1e-6)
                left_base = inv_rot @ (left_tip - nav_loc) * inv_scale
                right_base = inv_rot @ (right_tip - nav_loc) * inv_scale
                base_mid = (left_base + right_base) * 0.5
                if (right_base - left_base).length > 1e-5:
                    base_axis = (right_base - left_base).normalized()
                base_viewer = inv_rot @ (viewer - nav_loc) * inv_scale
            _STATE["pinch"] = {
                "handler": handler if grabbed else None,
                "start_dist": max(distance, 1e-4),
                "start_mid": mid.copy(),
                "nav_loc": nav_loc,
                "nav_scale": nav_scale,
                "nav_rot": nav_rot,
                "viewer": viewer,
                "axis": (right_tip - left_tip).normalized() if (right_tip - left_tip).length > 1e-5 else None,
                "base_mid": base_mid,
                "base_axis": base_axis,
                "base_viewer": base_viewer,
                "angle": 0.0,
            }
            settings.status = "双手-选中 / grab selection" if grabbed else "双手-视图 / grab view"
        else:
            shift = distance - pinch["start_dist"]
            factor = max(0.2, min(5.0, 1.0 + shift * settings.pinch_gain))
            delta = mid - pinch["start_mid"]
            rotation = None
            axis = (right_tip - left_tip)
            if pinch.get("axis") is not None and axis.length > 1e-5:
                rotation = pinch["axis"].rotation_difference(axis.normalized())
            if pinch["handler"] is not None:
                pinch["handler"].apply(context, delta, factor, rotation)
                overlay.hide_rotation()
            elif state is not None:
                view_factor = max(0.2, min(5.0, 1.0 + shift * settings.view_pinch_gain))
                nav_rot_before = Quaternion(state.navigation_rotation)
                hand_rot = apply_two_hand_view(pinch, left_tip, right_tip, state, settings.invert_grab)
                applied = (1.0 / view_factor) if settings.pinch_invert else view_factor
                state.navigation_scale = max(0.1, min(10.0, pinch["nav_scale"] * applied))

                angle_deg = math.degrees(hand_rot.angle) if hand_rot is not None else 0.0
                pinch["angle"] = angle_deg
                axis_world = None
                if hand_rot is not None and angle_deg >= 0.5:
                    axis_world = (nav_rot_before @ hand_rot.axis).normalized()
                overlay.show_rotation(mid, axis_world, angle_deg, pinch["viewer"])
        _STATE["trigger_r"] = True
        return 0.05
    if _STATE["pinch"] is not None:
        pinch, _STATE["pinch"] = _STATE["pinch"], None
        overlay.hide_rotation()
        if pinch["handler"] is not None:
            try:
                undo.push_base(context, pinch["handler"].base)
                settings.status = "已提交 / committed"
            except Exception as exc:  # noqa: BLE001
                settings.status = f"pinch commit error: {exc}"
        else:
            settings.status = "视图已移动 / view moved"
        _STATE["trigger_r"] = False
        return 0.05

    stick_click = actions.value(context, "stick_click", 0) > 0.55
    if stick_click and not _STATE["stick_click_l"]:
        settings.vertical_move = not settings.vertical_move
        settings.status = "move: vertical" if settings.vertical_move else "move: horizontal"
        _toast("垂直移动 / Vertical" if settings.vertical_move else "水平移动 / Horizontal")
    _STATE["stick_click_l"] = stick_click
    if state is not None and not _STATE["grabbing"]:
        try:
            _navigate(context, state, 0.05)
        except Exception as exc:  # noqa: BLE001
            settings.status = f"nav error: {exc}"

    trigger = actions.value(context, "trigger", hand) > 0.55
    squeeze_r = actions.value(context, "squeeze", 1) > 0.55
    squeeze_l = actions.value(context, "squeeze", 0) > 0.55
    fine = actions.value(context, "trigger", 0) > 0.55

    # 1) brush selection while the right trigger is held
    if tip_loc is not None and trigger and not _STATE["ui_hover"]:
        radius = settings.brush_radius
        try:
            if not _STATE["trigger_r"]:
                mesh.clear_selection(context)
                obj, kind, index, _dist = mesh.pick_element(context, tip_loc, radius)
                if obj is not None:
                    mesh.select_element(context, obj, kind, index, additive=True)
                    settings.status = f"selected {kind} on {obj.name}"
                else:
                    mesh.brush_select(context, tip_loc, radius, additive=True)
                    settings.status = "刷选中 / selecting"
            elif settings.brush_multi:
                mesh.brush_select(context, tip_loc, radius, additive=True)
        except Exception as exc:  # noqa: BLE001
            settings.status = f"select error: {exc}"
    _STATE["trigger_r"] = trigger

    # 2) grab selected vertices with the right squeeze
    if squeeze_r and not _STATE["squeeze_r"] and tip_loc is not None:
        sel = mesh.selection(context)
        if sel:
            _STATE["translate"] = mesh.Translate()
            if _STATE["translate"].begin(context):
                _STATE["grabbing"] = True
                _STATE["grab_start"] = tip_loc.copy()
                settings.status = "拖动中 / grabbing"
    if not squeeze_r and _STATE["squeeze_r"] and _STATE["grabbing"]:
        try:
            undo.push_translate(context, _STATE["translate"])
            settings.status = "已移动 / moved"
        except Exception as exc:  # noqa: BLE001
            settings.status = f"undo push error: {exc}"
        _STATE["grabbing"] = False
        _STATE["translate"] = None
    if _STATE["grabbing"] and tip_loc is not None and _STATE["grab_start"] is not None:
        delta = tip_loc - _STATE["grab_start"]
        if fine:
            delta *= 0.1
        try:
            _STATE["translate"].apply(context, delta)
        except Exception as exc:  # noqa: BLE001
            settings.status = f"move error: {exc}"
    _STATE["squeeze_r"] = squeeze_r

    # 3) right A = smooth selected, right B = save, left X = select mode
    a_click = actions.value(context, "a_click", 1) > 0.55
    b_click = actions.value(context, "b_click", 1) > 0.55
    x_click = actions.value(context, "x_click", 0) > 0.55

    if a_click and not _STATE["a_click"] and not _STATE["grabbing"] and _STATE["pinch"] is None:
        if mesh.selection(context):
            _STATE["smooth_base"] = mesh.capture_selection(context)
            _STATE["smoothing"] = True
            settings.status = "smoothing"
    if _STATE["smoothing"]:
        if a_click:
            try:
                mesh.smooth_selection(context, settings.smooth_strength, 1)
            except Exception as exc:  # noqa: BLE001
                settings.status = f"smooth error: {exc}"
        else:
            try:
                if _STATE["smooth_base"]:
                    undo.push_base(context, _STATE["smooth_base"])
                settings.status = "smoothed"
            except Exception as exc:  # noqa: BLE001
                settings.status = f"smooth commit error: {exc}"
            _STATE["smoothing"] = False
            _STATE["smooth_base"] = None
    _STATE["a_click"] = a_click

    if b_click and not _STATE["b_click"]:
        settings.status = "保存中 / saving..."
        bpy.app.timers.register(_save_async, first_interval=0.01)
    _STATE["b_click"] = b_click

    if x_click and not _STATE["x_click"]:
        try:
            mode = mesh.cycle_select_mode(context)
            settings.status = f"select mode: {mode}"
            _toast({"VERT": "顶点 / Vertex", "EDGE": "边 / Edge", "FACE": "面 / Face"}.get(mode, mode))
        except Exception as exc:  # noqa: BLE001
            settings.status = f"mode error: {exc}"
    _STATE["x_click"] = x_click

    # 4) left squeeze = undo
    if squeeze_l and not _STATE["squeeze_l"]:
        try:
            settings.status = "undo" if undo.undo(context) else "nothing to undo"
        except Exception as exc:  # noqa: BLE001
            settings.status = f"undo error: {exc}"
    _STATE["squeeze_l"] = squeeze_l

    now = time.time()
    if now - _STATE["last"] >= 0.25:
        _STATE["last"] = now
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(f"{now:.2f} " + _log_line(context, 0, "L") + "\n")
                handle.write(f"{now:.2f} " + _log_line(context, 1, "R") + "\n")
        except Exception:  # noqa: BLE001
            pass
    return 0.05
