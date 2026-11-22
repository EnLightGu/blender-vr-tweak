# SPDX-License-Identifier: GPL-3.0-or-later
"""VR Tweak — P0 add-on entry point.

P0 scope: start an XR session, draw the controller tip + brush ring, and log
every action value so the real Pico mapping can be measured.
"""
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import actions, mesh, overlay, session, undo


class VRTweakSettings(PropertyGroup):
    running: BoolProperty(name="Running", default=False)
    status: StringProperty(name="Status", default="idle")
    hand: EnumProperty(
        name="Hand",
        items=[("RIGHT", "Right", "Use the right controller"), ("LEFT", "Left", "Use the left controller")],
        default="RIGHT",
    )
    tip_offset: FloatVectorProperty(
        name="Tip Offset",
        description="Offset from the grip pose to the controller tip (grip space, meters)",
        size=3,
        default=(0.0, 0.0, -0.055),
        subtype="TRANSLATION",
    )
    tip_source: EnumProperty(
        name="Tip Source",
        description="Where the orange brush ring is anchored",
        items=[
            ("AIM", "Aim axis", "Follow Blender's aim pose (tri-color axis)"),
            ("GRIP", "Grip origin", "Follow the grip pose (white ring)"),
            ("OFFSET", "Grip + offset", "Follow the calibrated offset"),
        ],
        default="AIM",
    )
    vertical_move: BoolProperty(
        name="Vertical Move",
        description="Left stick up/down moves vertically instead of forward/back",
        default=False,
    )
    move_speed: FloatProperty(
        name="Move Speed",
        description="Left stick locomotion speed (m/s, scaled by the XR base/navigation scale)",
        default=0.5,
        min=0.1,
        max=3.0,
    )
    invert_stick_x: BoolProperty(
        name="Invert Stick X",
        description="Flip the thumbstick left/right axis (strafe + snap turn); use when they go the wrong way",
        default=False,
    )
    invert_stick_y: BoolProperty(
        name="Invert Stick Y",
        description="Flip the thumbstick forward/back axis",
        default=False,
    )
    invert_grab: BoolProperty(
        name="Invert Two-Hand View",
        description="Flip the translation/rotation direction of two-handed view navigation",
        default=False,
    )
    pinch_gain: FloatProperty(
        name="Pinch Gain",
        description="Scale change per meter of hand movement",
        default=2.0,
        min=0.2,
        max=10.0,
    )
    view_pinch_gain: FloatProperty(
        name="View Pinch Gain",
        description="Separate zoom gain for the scene view",
        default=0.25,
        min=0.05,
        max=5.0,
    )
    pinch_invert: BoolProperty(
        name="Invert View Pinch",
        description="Invert the view zoom direction when pinching",
        default=True,
    )
    turn_angle: FloatProperty(
        name="Turn Angle",
        description="Right stick snap turn (degrees)",
        default=30.0,
        min=10.0,
        max=90.0,
    )
    smooth_strength: FloatProperty(
        name="Smooth Strength",
        description="Laplacian smoothing strength while A is held",
        default=0.5,
        min=0.05,
        max=1.0,
    )
    brush_multi: BoolProperty(
        name="Brush Multi-Select",
        description="Keep adding vertices/edges/faces while the trigger is held",
        default=True,
    )
    brush_radius: FloatProperty(
        name="Brush Radius",
        description="P0 visualization only",
        default=0.02,
        min=0.002,
        max=0.2,
        subtype="DISTANCE",
    )


class VRTWEAK_OT_start(Operator):
    bl_idname = "vrtweak.start"
    bl_label = "Start VR Tweak (P0)"
    bl_description = "Start XR, draw the controller tip and log all inputs"

    @classmethod
    def poll(cls, context):
        try:
            return not bpy.types.XrSessionState.is_running(context)
        except Exception:  # noqa: BLE001
            return False

    def execute(self, context):
        try:
            session.start(context)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"VR Tweak start failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"VR Tweak P0 started, log: {session.LOG_PATH}")
        return {"FINISHED"}


class VRTWEAK_OT_stop(Operator):
    bl_idname = "vrtweak.stop"
    bl_label = "Stop VR Tweak"
    bl_description = "Stop the XR session and clean up the P0 overlay"

    @classmethod
    def poll(cls, context):
        try:
            return bpy.types.XrSessionState.is_running(context)
        except Exception:  # noqa: BLE001
            return False

    def execute(self, context):
        session.stop(context)
        self.report({"INFO"}, "VR Tweak stopped")
        return {"FINISHED"}


class VRTWEAK_OT_undo(Operator):
    bl_idname = "vrtweak.undo"
    bl_label = "Undo (VR Tweak)"
    bl_description = "Undo the last VR translate"

    @classmethod
    def poll(cls, context):
        return bool(mesh.objects_in_edit(context))

    def execute(self, context):
        ok = undo.undo(context)
        self.report({"INFO"} if ok else {"WARNING"}, "Undone" if ok else "Nothing to undo")
        return {"FINISHED"}


class VRTWEAK_OT_redo(Operator):
    bl_idname = "vrtweak.redo"
    bl_label = "Redo (VR Tweak)"
    bl_description = "Redo the last undone VR translate"

    @classmethod
    def poll(cls, context):
        return bool(mesh.objects_in_edit(context))

    def execute(self, context):
        ok = undo.redo(context)
        self.report({"INFO"} if ok else {"WARNING"}, "Redone" if ok else "Nothing to redo")
        return {"FINISHED"}


class VRTWEAK_OT_save(Operator):
    bl_idname = "vrtweak.save"
    bl_label = "Save"
    bl_description = "Save the current .blend file"

    def execute(self, context):
        try:
            bpy.ops.wm.save_mainfile()
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "Saved")
        return {"FINISHED"}


class VRTWEAK_PT_panel(Panel):
    bl_label = "VR Tweak (P0)"
    bl_idname = "VRTWEAK_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "VR Tweak"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vrtweak
        if not settings.running:
            col = layout.column(align=True)
            col.label(text="1. 选中一个网格物体（可多选）", icon="INFO")
            col.label(text="2. 点下面按钮进入 VR", icon="INFO")
            col.label(text="3. 头显里：右扳机刷选，右握把拖动", icon="INFO")
            layout.operator("vrtweak.start", text="开始 VR 微调", icon="PLAY")
        else:
            layout.operator("vrtweak.stop", text="停止 VR", icon="PAUSE")
        layout.label(text=f"Status: {settings.status}")
        try:
            sel = mesh.selection(context)
            layout.label(text=f"Selected: {sum(len(v) for v in sel.values())} verts / {len(sel)} objects")
        except Exception:  # noqa: BLE001
            pass
        box = layout.box()
        box.label(text="Controller tip")
        box.prop(settings, "hand")
        box.prop(settings, "tip_source")
        box.prop(settings, "tip_offset")
        box.prop(settings, "brush_multi")
        box.prop(settings, "brush_radius")
        box.prop(settings, "smooth_strength")
        box.prop(settings, "vertical_move")
        box.prop(settings, "move_speed")
        box.prop(settings, "turn_angle")
        box.prop(settings, "invert_stick_x")
        box.prop(settings, "invert_stick_y")
        box.prop(settings, "invert_grab")
        box.prop(settings, "pinch_gain")
        box.prop(settings, "view_pinch_gain")
        box.prop(settings, "pinch_invert")
        row = layout.row(align=True)
        row.operator("vrtweak.undo", icon="LOOP_BACK")
        row.operator("vrtweak.redo", icon="LOOP_FORWARDS")
        row.operator("vrtweak.save", icon="FILE_TICK")
        layout.label(text=f"Log: {session.LOG_PATH}")


def _on_load(*_args):
    """Re-register the XR start handler: loading a .blend can clear handlers."""
    if actions.session_pre not in bpy.app.handlers.xr_session_start_pre:
        bpy.app.handlers.xr_session_start_pre.append(actions.session_pre)


def _header(self, context):
    self.layout.operator("vrtweak.start", text="VR Tweak", icon="VIEW_CAMERA")


def _menu(self, context):
    self.layout.separator()
    self.layout.operator("vrtweak.start", text="VR Tweak (微调)")


classes = (
    VRTweakSettings,
    VRTWEAK_OT_start,
    VRTWEAK_OT_stop,
    VRTWEAK_OT_undo,
    VRTWEAK_OT_redo,
    VRTWEAK_OT_save,
    VRTWEAK_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vrtweak = bpy.props.PointerProperty(type=VRTweakSettings)
    if actions.session_pre not in bpy.app.handlers.xr_session_start_pre:
        bpy.app.handlers.xr_session_start_pre.append(actions.session_pre)
    bpy.app.handlers.load_post.append(_on_load)
    _on_load()
    bpy.types.VIEW3D_HT_header.append(_header)
    bpy.types.VIEW3D_MT_view.append(_menu)


def unregister():
    try:
        session.stop(bpy.context)
    except Exception:  # noqa: BLE001
        pass
    overlay.remove()
    if actions.session_pre in bpy.app.handlers.xr_session_start_pre:
        bpy.app.handlers.xr_session_start_pre.remove(actions.session_pre)
    try:
        if _on_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_load)
        bpy.types.VIEW3D_HT_header.remove(_header)
        bpy.types.VIEW3D_MT_view.remove(_menu)
    except Exception:  # noqa: BLE001
        pass
    del bpy.types.Scene.vrtweak
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
