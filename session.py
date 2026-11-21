# SPDX-License-Identifier: GPL-3.0-or-later
"""P0/P1 session: XR input, tip brush, select + move + undo.

All geometry writes go through bmesh (mesh.py); undo stores bmesh coordinates.
"""
import math
import os
import tempfile
import time

import bpy
from mathutils import Quaternion, Vector

from . import actions, mesh, overlay, tip, undo

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
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
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
    stick = Vector(actions.vector(context, "stick", 0))
    rotation = Quaternion(state.viewer_pose_rotation)
    if settings.vertical_move:
        right = rotation @ Vector((1.0, 0.0, 0.0))
        right.z = 0.0
        if right.length > 1e-6:
            right.normalize()
        strength = min(stick.length, 1.0) - 0.15
        amount = (max(strength, 0.0) / 0.85) if stick.length > 0.15 else 0.0
        name = stick.normalized() if stick.length > 1e-6 else Vector((0.0, 0.0))
        delta = (right * name.x + Vector((0.0, 0.0, 1.0)) * name.y) * amount * dt * settings.move_speed
    else:
        delta = _stick_delta(rotation, stick, dt, settings.move_speed)
    if delta.length:
        state.navigation_location = Vector(state.navigation_location) + delta
    turn_stick = actions.vector(context, "stick", 1)[0]
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
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.xr_session_toggle()


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
    overlay.remove()
    _remove_hud()
    actions.reset()
    try:
        context.scene.vrtweak.running = False
    except Exception:  # noqa: BLE001
        pass


def start(context):
    settings = context.scene.vrtweak
    mesh.ensure_edit(context)
    undo.clear()
    with open(LOG_PATH, "w", encoding="utf-8") as handle:
        handle.write("# vrtweak input log\n")
    actions.reset()
    _toggle(context)
    overlay.add()
    _ensure_hud(context)
    _STATE.update({
        "last": 0.0,
        "trigger_r": False,
        "squeeze_r": False,
        "squeeze_l": False,
        "grabbing": False,
        "grab_start": None,
        "translate": None,
    })
    _STATE["timer"] = bpy.app.timers.register(tick, first_interval=0.05, persistent=True)
    settings.running = True
    settings.status = "waiting for XR session"


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
    ]
    return " ".join(parts)


def tick():
    context = bpy.context
    if not _is_running(context):
        _cleanup(context)
        return None

    settings = context.scene.vrtweak
    settings.running = True
    state = context.window_manager.xr_session_state

    hand = 1 if settings.hand == "RIGHT" else 0
    tip_loc, _ = tip.read(context, hand, settings.tip_offset, settings.tip_source)
    left_tip, _ = tip.read(context, 0, settings.tip_offset, settings.tip_source)
    right_tip, _ = tip.read(context, 1, settings.tip_offset, settings.tip_source)

    trigger_l = actions.value(context, "trigger", 0) > 0.55
    trigger_r = actions.value(context, "trigger", 1) > 0.55
    if _STATE["hud"] is not None and tip_loc is not None and not _STATE["grabbing"] and _STATE["pinch"] is None:
        if time.time() - _STATE.get("last_pick", 0.0) > 0.1:
            _STATE["last_pick"] = time.time()
            try:
                obj, kind, index, _dist = mesh.pick_element(context, tip_loc, settings.brush_radius)
                _STATE["preselect"] = (obj, kind, index) if obj is not None else None
            except Exception:  # noqa: BLE001
                _STATE["preselect"] = None
        mode = "顶点" if context.tool_settings.mesh_select_mode[0] else ("边" if context.tool_settings.mesh_select_mode[1] else "面")
        preselect = _STATE["preselect"]
        if preselect and preselect[0] is not None:
            text = f"预选：{preselect[0].name} / {mode}"
        else:
            text = f"预选：无（{mode}）"
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
            _STATE["pinch"] = {
                "handler": handler if grabbed else None,
                "start_dist": max(distance, 1e-4),
                "start_mid": mid.copy(),
                "nav_loc": Vector(state.navigation_location) if state is not None else None,
                "nav_scale": float(state.navigation_scale) if state is not None else 1.0,
                "nav_rot": Quaternion(state.navigation_rotation) if state is not None else Quaternion(),
                "viewer": Vector(state.viewer_pose_location) if state is not None else None,
                "axis": (right_tip - left_tip).normalized() if (right_tip - left_tip).length > 1e-5 else None,
            }
            settings.status = "two-hand grab: selection" if grabbed else "two-hand grab: view"
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
            elif state is not None:
                view_factor = max(0.2, min(5.0, 1.0 + shift * settings.view_pinch_gain))
                offset = pinch["nav_loc"] + delta
                if rotation is not None and pinch["viewer"] is not None:
                    relative = pinch["viewer"] - offset
                    offset = offset + relative - rotation @ relative
                    state.navigation_rotation = rotation @ pinch["nav_rot"]
                else:
                    state.navigation_rotation = pinch["nav_rot"]
                state.navigation_location = offset
                applied = (1.0 / view_factor) if settings.pinch_invert else view_factor
                state.navigation_scale = max(0.1, min(10.0, pinch["nav_scale"] * applied))
        _STATE["trigger_r"] = True
        return 0.05
    if _STATE["pinch"] is not None:
        pinch, _STATE["pinch"] = _STATE["pinch"], None
        if pinch["handler"] is not None:
            try:
                undo.push_base(context, pinch["handler"].base)
                settings.status = "two-hand transform committed"
            except Exception as exc:  # noqa: BLE001
                settings.status = f"pinch commit error: {exc}"
        else:
            settings.status = "view moved"
        _STATE["trigger_r"] = False
        return 0.05

    stick_click = actions.value(context, "stick_click", 0) > 0.55
    if stick_click and not _STATE["stick_click_l"]:
        settings.vertical_move = not settings.vertical_move
        settings.status = "move: vertical" if settings.vertical_move else "move: horizontal"
        _toast("垂直移动" if settings.vertical_move else "水平移动")
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
    if tip_loc is not None and trigger:
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
                    settings.status = "selecting"
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
                settings.status = "grabbing"
    if not squeeze_r and _STATE["squeeze_r"] and _STATE["grabbing"]:
        try:
            undo.push_translate(context, _STATE["translate"])
            settings.status = "moved"
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
        settings.status = "saving..."
        bpy.app.timers.register(_save_async, first_interval=0.01)
    _STATE["b_click"] = b_click

    if x_click and not _STATE["x_click"]:
        try:
            mode = mesh.cycle_select_mode(context)
            settings.status = f"select mode: {mode}"
            _toast({"VERT": "顶点模式", "EDGE": "边模式", "FACE": "面模式"}.get(mode, mode))
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
