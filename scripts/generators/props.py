"""Gameplay props & vehicle procedural generator.

Hard-surface Battle Royale assets: chamfered supply crates with recessed
panels and corner brackets, corrugated fuel drums, tactical cover barriers,
and a two-seat off-road recon buggy with roll cage and treaded wheels.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .meshkit import (
    Quality,
    SceneBuilder,
    box,
    cylinder_y,
    rotate_mesh,
    torus_flat,
    tube,
)


def build_prop(scene: SceneBuilder, cfg: dict[str, Any], q: Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset = str(cfg["preset_id"])
    w, d, h = float(p["width"]), float(p["depth"]), float(p["height"])
    detail = float(p.get("panel_detail", 0.65))

    if preset == "explosive_fuel_barrel":
        r = min(w, d) / 2.0
        segs = q.radial + 10
        scene.add("Drum", "primary", cylinder_y(r, h, segs, (0, h / 2.0, 0)))
        for fy in (0.22, 0.5, 0.78):  # rolling chimes
            scene.add("Drum", "secondary", torus_flat(r, 0.022, (0, h * fy, 0), max(12, segs - 6), 5))
        scene.add("Drum", "accent", cylinder_y(r + 0.006, h * 0.16, segs, (0, h * 0.64, 0)))
        for sx in (-0.45, 0.45):  # bung caps
            scene.add("Caps", "metal", cylinder_y(0.045, 0.05, 10, (sx * r, h + 0.02, 0)))
        return

    if preset == "tactical_cover_barrier":
        scene.add("Barrier", "secondary", box((w, h * 0.72, d), (0, h * 0.36, 0)))
        cap = box((w, h * 0.34, d * 0.62), (0, h * 0.86, 0))
        scene.add("Barrier", "primary", cap)
        for sx in (-1.0, 1.0):  # angled deflection feet
            foot = box((w * 0.16, 0.16, d * 1.7), (sx * w * 0.36, 0.08, 0))
            scene.add("Feet", "secondary", foot)
        scene.add("ArmorPlate", "metal", box((w * 0.92, h * 0.4, 0.06), (0, h * 0.62, d / 2 + 0.03)))
        n_stripes = 3 + int(detail * 3)
        for k in range(n_stripes):
            x = -w * 0.36 + (w * 0.72) * (k / max(1, n_stripes - 1))
            stripe = box((0.12, h * 0.3, 0.02), (x, h * 0.62, d / 2 + 0.075))
            rotate_mesh(stripe, 0.5, (0, 0, 1), (x, h * 0.62, d / 2 + 0.075))
            scene.add("Hazard", "accent", stripe)
        for sx in (-0.3, 0.3):  # forklift slots (dark recess illusions)
            scene.add("Slots", "trim", box((w * 0.16, 0.14, d + 0.02), (sx * w, 0.09, 0)))
        rib_n = 4 + int(detail * 5)
        for k in range(rib_n):
            rx = -w * 0.44 + w * 0.88 * (k / max(1, rib_n - 1))
            for sz in (-1.0, 1.0):
                scene.add("Ribs", "primary", box((0.07, h * 0.58, 0.05), (rx, h * 0.38, sz * (d / 2 + 0.02))))
                bolt = cylinder_y(0.022, 0.04, 6, (rx, h * 0.62, sz * (d * 0.31 + 0.05)))
                rotate_mesh(bolt, math.pi / 2.0, (1, 0, 0), (rx, h * 0.62, sz * (d * 0.31 + 0.05)))
                scene.add("Bolts", "metal", bolt)
        return

    if preset == "desert_recon_buggy":
        wheel_r = h * 0.24
        ground_clear = wheel_r + 0.10
        scene.add("Chassis", "primary", box((w * 0.82, 0.22, d * 0.86), (0, ground_clear + 0.11, 0)))
        hood = box((w * 0.78, 0.20, d * 0.30), (0, ground_clear + 0.34, d * 0.30))
        rotate_mesh(hood, -0.10, (1, 0, 0), (0, ground_clear + 0.34, d * 0.30))
        scene.add("Hood", "primary", hood)
        scene.add("NoseArmor", "metal", box((w * 0.7, 0.30, 0.10), (0, ground_clear + 0.12, d * 0.47)))
        for sx in (-1.0, 1.0):
            scene.add("Seats", "trim", box((0.46, 0.12, 0.46), (sx * w * 0.21, ground_clear + 0.30, -d * 0.08)))
            scene.add("Seats", "trim", box((0.46, 0.55, 0.12), (sx * w * 0.21, ground_clear + 0.55, -d * 0.20)))
        cage_r = 0.045
        top_y = ground_clear + h * 0.62
        posts = [
            ((-w * 0.38, ground_clear, d * 0.16), (-w * 0.34, top_y, d * 0.06)),
            ((w * 0.38, ground_clear, d * 0.16), (w * 0.34, top_y, d * 0.06)),
            ((-w * 0.38, ground_clear, -d * 0.28), (-w * 0.34, top_y, -d * 0.20)),
            ((w * 0.38, ground_clear, -d * 0.28), (w * 0.34, top_y, -d * 0.20)),
            ((-w * 0.34, top_y, d * 0.06), (w * 0.34, top_y, d * 0.06)),
            ((-w * 0.34, top_y, -d * 0.20), (w * 0.34, top_y, -d * 0.20)),
            ((-w * 0.34, top_y, d * 0.06), (-w * 0.34, top_y, -d * 0.20)),
            ((w * 0.34, top_y, d * 0.06), (w * 0.34, top_y, -d * 0.20)),
        ]
        scene.add_many("RollCage", "metal", [tube(a, b, cage_r, 8) for a, b in posts])
        scene.add("Lightbar", "metal", box((w * 0.5, 0.09, 0.09), (0, top_y + 0.08, d * 0.07)))
        for k in range(3):
            lx = (k - 1) * w * 0.15
            lamp = cylinder_y(0.055, 0.06, 10, (lx, top_y + 0.08, d * 0.13))
            rotate_mesh(lamp, math.pi / 2.0, (1, 0, 0), (lx, top_y + 0.08, d * 0.13))
            scene.add("Lamps", "glass_lamp", lamp)
        for sx in (-1.0, 1.0):
            for sz, zz in ((1.0, d * 0.32), (-1.0, -d * 0.32)):
                tire = cylinder_y(wheel_r, 0.24, q.radial + 4, (sx * w * 0.46, wheel_r, zz))
                rotate_mesh(tire, math.pi / 2.0, (0, 0, 1), (sx * w * 0.46, wheel_r, zz))
                scene.add("Wheels", "trim", tire)
                hub = cylinder_y(wheel_r * 0.45, 0.26, 8, (sx * w * 0.46, wheel_r, zz))
                rotate_mesh(hub, math.pi / 2.0, (0, 0, 1), (sx * w * 0.46, wheel_r, zz))
                scene.add("Wheels", "metal", hub)
                if detail > 0.55:
                    for t in range(8):
                        ang = 2 * math.pi * t / 8
                        ty = wheel_r + math.sin(ang) * wheel_r
                        tz = zz + math.cos(ang) * wheel_r
                        scene.add("Treads", "trim", box((0.26, 0.09, 0.13), (sx * w * 0.46, ty, tz)))
        spare = cylinder_y(wheel_r * 0.92, 0.18, q.radial, (0, ground_clear + 0.45, -d * 0.47))
        rotate_mesh(spare, math.pi / 2.0, (1, 0, 0), (0, ground_clear + 0.45, -d * 0.47))
        scene.add("SpareWheel", "trim", spare)
        return

    # Default: br_supply_crate (also the fallback for any unknown prop preset)
    body_h = h * 0.78
    scene.add("Hull", "primary", box((w * 0.96, body_h, d * 0.96), (0, body_h / 2.0, 0)))
    scene.add("Lid", "primary", box((w, h * 0.24, d), (0, body_h + h * 0.11, 0)))
    cb = min(w, d, h) * 0.17
    for sx in (-1.0, 1.0):
        for sz in (-1.0, 1.0):
            scene.add("Corners", "metal", box((cb, cb, cb), (sx * (w / 2 - cb * 0.42), cb * 0.5, sz * (d / 2 - cb * 0.42))))
            scene.add("Corners", "metal", box((cb, cb * 0.9, cb), (sx * (w / 2 - cb * 0.42), h - cb * 0.42, sz * (d / 2 - cb * 0.42))))
    rib_count = max(2, int(round(2 + detail * 3)))
    for k in range(rib_count):
        t = -0.34 + 0.68 * (k / max(1, rib_count - 1))
        for sz in (-1.0, 1.0):
            scene.add("Ribs", "secondary", box((w * 0.055, body_h * 0.82, 0.035), (w * t, body_h * 0.48, sz * (d * 0.49))))
    for sx in (-0.28 * w, 0.28 * w):
        scene.add("Straps", "trim", box((w * 0.055, h * 1.01, d * 1.015), (sx, h * 0.5, 0)))
    if detail >= 0.25:
        for sx in (-0.22 * w, 0.22 * w):
            for sz in (-1.0, 1.0):
                scene.add("Latches", "accent", box((w * 0.09, h * 0.17, 0.045), (sx, body_h, sz * (d * 0.51))))
        bolt_n = 6 if detail > 0.6 else 4
        for k in range(bolt_n):
            bx = -w * 0.4 + w * 0.8 * (k / max(1, bolt_n - 1))
            for sz in (-1.0, 1.0):
                bolt = cylinder_y(0.018, 0.03, 6, (bx, body_h * 0.9, sz * d * 0.5))
                rotate_mesh(bolt, math.pi / 2.0, (1, 0, 0), (bx, body_h * 0.9, sz * d * 0.5))
                scene.add("Bolts", "metal", bolt)


# ---------------------------------------------------------------------------
# ARCHITECTURE builders
