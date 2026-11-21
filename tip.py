# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller tip pose.

P0 draws both the grip origin (white) and the offset tip (orange) so the
correct offset can be measured on the real headset instead of guessed.
"""
from mathutils import Vector

from . import actions


def tip_from_grip(grip_loc, grip_rot, offset):
    return grip_loc + grip_rot @ Vector(offset)


def read(context, hand, offset, source="AIM"):
    grip_loc, grip_rot = actions.pose(context, hand)
    if source == "AIM":
        aim_loc, _ = actions.aim_pose(context, hand)
        return aim_loc, grip_loc
    if grip_loc is None or grip_rot is None:
        return None, None
    if source == "GRIP":
        return grip_loc.copy(), grip_loc
    return tip_from_grip(grip_loc, grip_rot, offset), grip_loc
