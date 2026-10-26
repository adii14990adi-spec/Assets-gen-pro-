"""Stylized humanoid character assembler (A-pose body archetypes).

Composes athletic male/female combatant silhouettes from anatomical lofts:
torso, arms with articulated hands, legs, boots, sculpted hair, armour vest,
and survival backpack. The hero Mid-Poly Female T-Pose character is built by
``character_tpose.py`` and routed through ``build_humanoid`` below.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .character_tpose import build_midpoly_female_tpose_parts
from .meshkit import (
    Quality,
    SceneBuilder,
    box,
    cylinder_y,
    rotate_mesh,
    sphere,
    tube,
)


def build_humanoid(scene: SceneBuilder, cfg: dict[str, Any], q: Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset_id = str(cfg.get("preset_id", ""))
    pose = str(p.get("pose", "t_pose" if preset_id == "midpoly_character" else "a_pose"))
    polygon_budget = int(cfg.get("polygon_budget", 2200))

    if preset_id == "midpoly_character" or pose == "t_pose":
        tpose_parts = build_midpoly_female_tpose_parts(
            target_faces=polygon_budget,
            height=float(p.get("height", 1.72)),
            rng=rng,
            parameters=p,
        )
        for part_name, slot_name, mesh in tpose_parts:
            resolved_slot = slot_name if slot_name in scene.materials else "skin"
            scene.add(part_name, resolved_slot, mesh)

        H = float(p.get("height", 1.72))
        chest_y = 0.725 * H
        if bool(p.get("include_armor", False)):
            scene.add("Armor", "metal", sphere((0.105 * H, 0.095 * H, 0.072 * H), (0, chest_y, 0.012 * H), max(1, q.sphere_subdiv - 1)))
        if bool(p.get("include_backpack", False)):
            scene.add("Backpack", "accent", box((0.16 * H, 0.22 * H, 0.085 * H), (0, chest_y, -0.095 * H)))
        return

    H = float(p.get("height", 1.78))
    muscle = float(p.get("musculature", 0.55))
    female = str(p.get("gender", "male")) == "female"
    shoulder_s = float(p.get("shoulder_width", 1.0)) * (0.94 if female else 1.05)
    hip_s = float(p.get("hip_width", 1.0)) * (1.06 if female else 0.97)
    limb_s = float(p.get("limb_length_scale", 1.0))
    clothing = bool(p.get("include_clothing", True))
    hair_on = bool(p.get("include_hair", True))
    shoes = bool(p.get("include_shoes", True))
    armor = bool(p.get("include_armor", False))
    backpack = bool(p.get("include_backpack", False))

    sub = q.sphere_subdiv
    sub_small = max(1, sub - 1)
    limb_r = (0.045 + 0.028 * muscle) * H

    hip_y = 0.525 * H * limb_s
    waist_y = 0.60 * H
    chest_y = 0.725 * H
    shoulder_y = 0.815 * H
    neck_y = 0.845 * H
    head_r = 0.072 * H
    head_cy = 0.92 * H
    half_hip = 0.088 * H * hip_s
    half_sh = 0.128 * H * shoulder_s

    def limb(part: str, slot: str, a: tuple[float, float, float], b: tuple[float, float, float], r: float) -> None:
        scene.add(part, slot, tube(a, b, r, q.radial))
        scene.add(part, slot, sphere((r, r, r), a, sub_small))
        scene.add(part, slot, sphere((r, r, r), b, sub_small))

    # Core body
    chest_rx = half_sh * (0.92 + 0.18 * muscle)
    waist_rx = chest_rx * (0.72 if female else 0.82)
    torso_slot = "primary" if clothing else "skin"
    torso_part = "Shirt" if clothing else "Body"
    scene.add(torso_part, torso_slot, sphere((chest_rx, 0.115 * H, 0.062 * H * (1 + 0.2 * muscle)), (0, chest_y, 0), sub))
    scene.add(torso_part, torso_slot, sphere((waist_rx, 0.085 * H, 0.055 * H), (0, waist_y, 0), sub))
    scene.add("Body", "primary" if clothing else "skin", sphere((half_hip * 1.25, 0.075 * H, 0.06 * H), (0, hip_y, 0), sub))
    neck = cylinder_y(0.028 * H, 0.07 * H, q.radial, (0, neck_y, 0))
    scene.add("Body", "skin", neck)
    head = sphere((head_r * 0.92, head_r * 1.12, head_r), (0, head_cy, 0), sub)
    scene.add("Head", "skin", head)
    # Nose hint (keeps the silhouette readable at gameplay distance)
    scene.add("Head", "skin", sphere((head_r * 0.16, head_r * 0.22, head_r * 0.18), (0, head_cy - head_r * 0.08, head_r * 0.98), 1))
    if hair_on:
        cap = sphere((head_r * 1.0, head_r * 1.16, head_r * 1.06), (0, head_cy + head_r * 0.20, -head_r * 0.12), sub)
        scene.add("Hair", "hair", cap)
        if female:
            scene.add("Hair", "hair", sphere((head_r * 0.72, head_r * 1.7, head_r * 0.5), (0, head_cy - head_r * 0.7, -head_r * 0.85), sub_small))

    # Arms (A-pose, ~32 degrees from the torso) + hands
    for side in (-1.0, 1.0):
        sh = (side * half_sh, shoulder_y, 0.0)
        el = (side * (half_sh + 0.115 * H * limb_s), shoulder_y - 0.175 * H * limb_s, 0.012 * H)
        wr = (side * (half_sh + 0.185 * H * limb_s), shoulder_y - 0.335 * H * limb_s, 0.03 * H)
        upper_slot = "primary" if clothing else "skin"
        limb("Shirt" if clothing else "Body", upper_slot, sh, el, limb_r * (1.06 if clothing else 1.0))
        limb("Body", "skin", el, wr, limb_r * 0.82)
        hand_c = (wr[0] + side * 0.012 * H, wr[1] - 0.045 * H, wr[2] + 0.008 * H)
        scene.add("Hands", "skin", box((0.038 * H, 0.085 * H, 0.052 * H), hand_c))
        if q.fingers:
            for f in range(4):
                fx = hand_c[0] + (f - 1.5) * 0.011 * H
                base = (fx, hand_c[1] - 0.04 * H, hand_c[2] + 0.004 * H)
                tip = (fx, base[1] - 0.042 * H, base[2] + 0.006 * H)
                scene.add("Hands", "skin", tube(base, tip, 0.0045 * H, 5))
            thumb_base = (hand_c[0] - side * 0.016 * H, hand_c[1] - 0.01 * H, hand_c[2] + 0.02 * H)
            thumb_tip = (thumb_base[0] - side * 0.016 * H, thumb_base[1] - 0.028 * H, thumb_base[2] + 0.016 * H)
            scene.add("Hands", "skin", tube(thumb_base, thumb_tip, 0.005 * H, 5))

    # Legs + boots
    ankle_y = 0.062 * H
    knee_y = hip_y * 0.52
    for side in (-1.0, 1.0):
        hip = (side * half_hip, hip_y, 0.0)
        knee = (side * half_hip * 1.04, knee_y, 0.012 * H)
        ankle = (side * half_hip * 1.08, ankle_y, 0.0)
        leg_slot = "secondary" if clothing else "skin"
        leg_part = "Trousers" if clothing else "Body"
        limb(leg_part, leg_slot, hip, knee, limb_r * 1.28 * (1.05 if clothing else 1.0))
        limb(leg_part, leg_slot, knee, ankle, limb_r * 0.98 * (1.05 if clothing else 1.0))
        if shoes:
            scene.add("Boots", "trim", box((0.052 * H, 0.055 * H, 0.16 * H), (ankle[0], 0.028 * H, 0.035 * H)))
            scene.add("Boots", "trim", cylinder_y(limb_r * 0.95, 0.09 * H, q.radial, (ankle[0], ankle_y + 0.02 * H, 0)))
        else:
            scene.add("Feet", "skin", box((0.046 * H, 0.03 * H, 0.13 * H), (ankle[0], 0.015 * H, 0.03 * H)))

    if clothing:  # belt + collar trims
        scene.add("Belt", "trim", sphere((waist_rx * 1.04, 0.026 * H, 0.058 * H), (0, waist_y - 0.045 * H, 0), sub_small))
        scene.add("Belt", "accent", box((0.05 * H, 0.035 * H, 0.02 * H), (0, waist_y - 0.045 * H, 0.056 * H)))
    if armor:
        scene.add("Armor", "metal", sphere((chest_rx * 0.96, 0.10 * H, 0.070 * H), (0, chest_y - 0.01 * H, 0.012 * H), sub))
        scene.add("Armor", "metal", box((chest_rx * 1.1, 0.05 * H, 0.03 * H), (0, chest_y - 0.075 * H, 0.062 * H)))
        for side in (-1.0, 1.0):
            scene.add("Armor", "metal", sphere((limb_r * 1.5, limb_r * 1.15, limb_r * 1.5), (side * half_sh, shoulder_y + 0.012 * H, 0), sub_small))
    if backpack:
        scene.add("Backpack", "accent", box((0.17 * H, 0.24 * H, 0.09 * H), (0, chest_y, -0.105 * H)))
        roll = cylinder_y(0.04 * H, 0.17 * H, 10, (0, chest_y + 0.15 * H, -0.105 * H))
        rotate_mesh(roll, math.pi / 2.0, (0, 0, 1), (0, chest_y + 0.15 * H, -0.105 * H))
        scene.add("Backpack", "secondary", roll)
        for side in (-1.0, 1.0):
            scene.add("Backpack", "accent", box((0.055 * H, 0.09 * H, 0.06 * H), (side * 0.115 * H, chest_y - 0.04 * H, -0.105 * H)))
