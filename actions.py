# SPDX-License-Identifier: GPL-3.0-or-later
"""Own OpenXR action set for VR Tweak.

P0 only needs poses + every button/stick value, so the exact mapping can be
measured on the real headset instead of guessed.
"""
import os
import tempfile
import time

import bpy
from mathutils import Quaternion, Vector

SET = "vrtweak"
HANDS = ("/user/hand/left", "/user/hand/right")

# profile -> (interaction profile path, squeeze component path)
PROFILES = {
    "touch": ("/interaction_profiles/oculus/touch_controller", "/input/squeeze/value"),
    "index": ("/interaction_profiles/valve/index_controller", "/input/squeeze/value"),
    "vive": ("/interaction_profiles/htc/vive_controller", "/input/squeeze/click"),
    "simple": ("/interaction_profiles/khr/simple_controller", "/input/select/click"),
}

# name, type, default component path (None -> profile squeeze path)
ACTIONS = (
    ("grip_pose", "POSE", "/input/grip/pose", None),
    ("aim_pose", "POSE", "/input/aim/pose", None),
    ("trigger", "FLOAT", "/input/trigger/value", None),
    ("squeeze", "FLOAT", None, None),
    ("stick", "VECTOR2D", "/input/thumbstick", None),
    ("stick_click", "FLOAT", "/input/thumbstick/click", None),
    ("a_click", "FLOAT", "/input/a/click", "RIGHT"),
    ("b_click", "FLOAT", "/input/b/click", "RIGHT"),
    ("x_click", "FLOAT", "/input/x/click", "LEFT"),
    ("y_click", "FLOAT", "/input/y/click", "LEFT"),
    ("haptic", "VIBRATION", "/output/haptic", None),
)

# Buttons that only exist on touch/index controllers.
TOUCH_BUTTONS = {"stick_click", "a_click", "b_click", "x_click", "y_click"}

_ready = False
_ensured = False
_DBG = os.path.join(tempfile.gettempdir(), "vrtweak-actions.log")


def _log(msg):
    try:
        with open(_DBG, "a", encoding="utf-8") as h:
            h.write(msg + "\n")
    except Exception:  # noqa: BLE001
        pass


def reset():
    global _ready, _ensured
    _ensured = False
    _ready = False


def ready():
    return _ready


def ensure(context):
    """Create + activate the action set. Returns True on success."""
    global _ready, _ensured
    if _ready:
        return True
    if _ensured:
        return False
    _ensured = True
    state = context.window_manager.xr_session_state
    _log(f"ensure state={state is not None}")
    if state is None:
        return False

    try:
        amap = state.actionmaps.new(state, SET, replace_existing=True)
        _log(f"actionmap ok items={len(amap.actionmap_items)}")
    except Exception as exc:  # noqa: BLE001
        _log(f"actionmap FAIL {exc!r}")
        return False

    for name, kind, component, hand in ACTIONS:
        try:
            item = amap.actionmap_items.new(name, replace_existing=True)
        except Exception:  # noqa: BLE001
            continue
        item.type = kind
        item.pose_is_controller_grip = name == "grip_pose"
        item.pose_is_controller_aim = name == "aim_pose"
        hands = HANDS if hand is None else (HANDS[0 if hand == "LEFT" else 1],)
        for path in hands:
            try:
                item.user_paths.new(path)
            except Exception:  # noqa: BLE001
                pass

        for key, (profile, squeeze_path) in PROFILES.items():
            # simple controller: only select/click, no stick/buttons
            if key == "simple" and name in {"stick", "squeeze", "stick_click", "haptic"}:
                continue
            if key == "simple" and name in TOUCH_BUTTONS:
                continue
            if key == "vive" and name in TOUCH_BUTTONS:
                continue
            if name in TOUCH_BUTTONS and key != "touch":
                continue
            if name == "squeeze":
                path = squeeze_path
            elif key == "vive" and name == "stick":
                path = "/input/trackpad"
            elif key == "vive" and name == "stick_click":
                path = "/input/trackpad/click"
            elif key == "simple" and name == "trigger":
                path = "/input/select/click"
            else:
                path = component
            if not path:
                continue
            try:
                binding = item.bindings.new(key, replace_existing=True)
                binding.profile = profile
                binding.threshold = 0.55
                for _ in hands:
                    binding.component_paths.new(path)
            except Exception:  # noqa: BLE001
                continue

    try:
        ok = state.action_set_create(context, amap)
        _log(f"action_set_create {ok}")
        if not ok:
            return False
    except Exception as exc:  # noqa: BLE001
        _log(f"action_set_create FAIL {exc!r}")
        return False

    critical = {"grip_pose", "aim_pose", "trigger"}
    for item in amap.actionmap_items:
        _log(f"action_create begin {item.name} type={item.type}")
        try:
            created = state.action_create(context, amap, item)
        except Exception as exc:  # noqa: BLE001
            _log(f"action_create FAIL {item.name} {exc!r}")
            created = False
        _log(f"action_create done {item.name} -> {created}")
        if not created:
            if item.name in critical:
                return False
            continue
        for binding in item.bindings:
            _log(f"binding begin {item.name} profile={binding.profile}")
            try:
                state.action_binding_create(context, amap, item, binding)
            except Exception as exc:  # noqa: BLE001
                _log(f"binding FAIL {item.name} {exc!r}")
            _log(f"binding done {item.name}")

    try:
        poses = state.controller_pose_actions_set(context, SET, "grip_pose", "aim_pose")
        active = state.active_action_set_set(context, SET)
        _log(f"poses={poses} active={active}")
        if not poses or not active:
            return False
    except Exception as exc:  # noqa: BLE001
        _log(f"pose/active FAIL {exc!r}")
        return False

    _log("ensure OK")
    _ready = True
    return True


def session_pre(*_args):
    """Build the action set before the XR session starts.

    Creating it while a session is already running crashes Blender's XR layer,
    so this is registered on bpy.app.handlers.xr_session_start_pre.
    """
    _log("session_pre called")
    try:
        ok = ensure(bpy.context)
        _log(f"session_pre ensure={ok}")
    except Exception as exc:  # noqa: BLE001
        _log(f"session_pre FAIL {exc!r}")


def read(context, name, hand):
    try:
        return context.window_manager.xr_session_state.action_state_get(
            context, SET, name, HANDS[hand]
        )
    except Exception:  # noqa: BLE001
        return None


def value(context, name, hand):
    """Scalar value for FLOAT/BOOLEAN actions, 0.0 on failure."""
    data = read(context, name, hand)
    try:
        return float(data[0])
    except Exception:  # noqa: BLE001
        return 0.0


def vector(context, name, hand):
    data = read(context, name, hand)
    try:
        return (float(data[0]), float(data[1]))
    except Exception:  # noqa: BLE001
        return (0.0, 0.0)


def pose(context, hand):
    state = context.window_manager.xr_session_state
    try:
        loc = Vector(state.controller_grip_location_get(context, hand))
        rot = Quaternion(state.controller_grip_rotation_get(context, hand))
        return loc, rot
    except Exception as exc:  # noqa: BLE001
        if not hasattr(pose, "_last_err") or time.time() - pose._last_err > 1.0:
            pose._last_err = time.time()
            _log(f"pose ERR hand={hand} {exc!r}")
        return None, None


def aim_pose(context, hand):
    state = context.window_manager.xr_session_state
    try:
        loc = Vector(state.controller_aim_location_get(context, hand))
        rot = Quaternion(state.controller_aim_rotation_get(context, hand))
        return loc, rot
    except Exception:  # noqa: BLE001
        return None, None
