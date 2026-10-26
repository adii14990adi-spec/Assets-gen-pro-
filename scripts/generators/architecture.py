"""Rajasthani & modular architecture procedural generator.

Builds enterable thick-walled masonry structures, cusped multifoil arched
portals, cantilevered Jharokha balconies, sloped Chhajja eaves, ribbed lotus
domes with Kalash finials, and Kangura rooftop battlements entirely from
analytic Python geometry.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .meshkit import (
    Quality,
    SceneBuilder,
    box,
    cone_y,
    cylinder_y,
    rotate_mesh,
    sphere,
    tube,
)


def arch_ring(
    scene: SceneBuilder,
    part: str,
    slot: str,
    *,
    cx: float,
    cy: float,
    cz: float,
    radius: float,
    thickness: float,
    depth_t: float,
    segments: int,
) -> None:
    """Semicircular voussoir arch ring in the XY plane (facing +/-Z)."""
    segs = max(5, segments)
    arc_len = math.pi * radius / segs
    for k in range(segs):
        angle = math.pi * (k + 0.5) / segs
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        block = box((arc_len * 1.08, thickness, depth_t), (x, y, cz))
        rotate_mesh(block, angle - math.pi / 2.0, (0, 0, 1), (x, y, cz))
        scene.add(part, slot, block)


def merlon_run(
    scene: SceneBuilder,
    part: str,
    slot: str,
    *,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    size: tuple[float, float, float],
    spacing: float,
) -> None:
    a = np.array(start, dtype=float)
    b = np.array(end, dtype=float)
    length = float(np.linalg.norm(b - a))
    count = max(1, int(length / max(spacing, 0.1)))
    for k in range(count + 1):
        p = a + (b - a) * (k / count)
        scene.add(part, slot, box(size, (float(p[0]), float(p[1]), float(p[2]))))


def parapet(
    scene: SceneBuilder,
    *,
    w: float,
    d: float,
    top_y: float,
    detail: float,
    slot: str = "secondary",
) -> None:
    """Kangura battlement parapet around a rectangular roofline."""
    rail_h = 0.22
    scene.add("Parapet", slot, box((w, rail_h, 0.18), (0, top_y + rail_h / 2, d / 2 - 0.09)))
    scene.add("Parapet", slot, box((w, rail_h, 0.18), (0, top_y + rail_h / 2, -d / 2 + 0.09)))
    scene.add("Parapet", slot, box((0.18, rail_h, d), (w / 2 - 0.09, top_y + rail_h / 2, 0)))
    scene.add("Parapet", slot, box((0.18, rail_h, d), (-w / 2 + 0.09, top_y + rail_h / 2, 0)))
    spacing = 0.95 - 0.45 * float(np.clip(detail, 0.0, 1.0))
    merlon = (0.30, 0.34, 0.20)
    my = top_y + rail_h + merlon[1] / 2
    merlon_run(scene, "Parapet", slot, start=(-w / 2 + 0.3, my, d / 2 - 0.09), end=(w / 2 - 0.3, my, d / 2 - 0.09), size=merlon, spacing=spacing)
    merlon_run(scene, "Parapet", slot, start=(-w / 2 + 0.3, my, -d / 2 + 0.09), end=(w / 2 - 0.3, my, -d / 2 + 0.09), size=merlon, spacing=spacing)
    side = (0.20, 0.34, 0.30)
    merlon_run(scene, "Parapet", slot, start=(w / 2 - 0.09, my, -d / 2 + 0.3), end=(w / 2 - 0.09, my, d / 2 - 0.3), size=side, spacing=spacing)
    merlon_run(scene, "Parapet", slot, start=(-w / 2 + 0.09, my, -d / 2 + 0.3), end=(-w / 2 + 0.09, my, d / 2 - 0.3), size=side, spacing=spacing)


def pillar(
    scene: SceneBuilder,
    part: str,
    *,
    x: float,
    z: float,
    base_y: float,
    height: float,
    radius: float,
    segments: int,
) -> None:
    scene.add(part, "accent", box((radius * 2.6, 0.16, radius * 2.6), (x, base_y + 0.08, z)))
    scene.add(part, "primary", cylinder_y(radius, height, segments, (x, base_y + height / 2.0, z)))
    scene.add(part, "accent", box((radius * 2.7, 0.15, radius * 2.7), (x, base_y + height + 0.07, z)))


def front_wall_with_portal(
    scene: SceneBuilder,
    *,
    w: float,
    h: float,
    z: float,
    thickness: float,
    opening_w: float,
    opening_h: float,
    arch_segments: int,
    base_y: float = 0.0,
) -> None:
    """Front facade (facing +Z) with a genuine arched doorway opening."""
    side_w = max((w - opening_w) / 2.0, 0.05)
    spring_y = max(opening_h - opening_w / 2.0, opening_h * 0.55)
    for sx in (-1.0, 1.0):
        scene.add(
            "Facade",
            "primary",
            box(
                (side_w, h, thickness),
                (sx * (opening_w / 2.0 + side_w / 2.0), base_y + h / 2.0, z),
            ),
        )
    lintel_h = max(h - opening_h, 0.1)
    scene.add(
        "Facade",
        "primary",
        box((opening_w + 0.3, lintel_h, thickness), (0, base_y + opening_h + lintel_h / 2.0, z)),
    )
    arch_ring(
        scene,
        "Facade",
        "accent",
        cx=0,
        cy=base_y + spring_y,
        cz=z,
        radius=opening_w / 2.0 + 0.07,
        thickness=0.22,
        depth_t=thickness + 0.05,
        segments=arch_segments,
    )
    # Recessed timber door leaves inside the opening.
    door_h = spring_y
    for sx in (-1.0, 1.0):
        door = box((opening_w / 2.0 - 0.03, door_h, 0.09), (sx * opening_w / 4.0, base_y + door_h / 2.0, z - thickness * 0.35))
        rotate_mesh(door, sx * 0.12, (0, 1, 0), (sx * opening_w / 2.0, base_y + door_h / 2.0, z - thickness * 0.35))
        scene.add("Doors", "trim", door)


# ---------------------------------------------------------------------------
# PROPS builders

# ---------------------------------------------------------------------------
# Architecture asset builder
# ---------------------------------------------------------------------------

def build_architecture(scene: SceneBuilder, cfg: dict[str, Any], q: Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset = str(cfg["preset_id"])
    w, d = float(p["width"]), float(p["depth"])
    h, wt = float(p["height"]), float(p["wall_thickness"])
    ow, oh = float(p["opening_width"]), float(p["opening_height"])
    floors = int(p.get("floors", 1))
    arch_segs = int(p.get("arch_segments", 12))
    detail = float(p.get("decorative_detail", 0.75))

    if preset == "stone_arch_bridge":
        deck_y = h * 0.78
        scene.add("Deck", "primary", box((w, h * 0.18, d), (0, deck_y, 0)))
        scene.add("Roadway", "accent", box((w, 0.09, d * 0.8), (0, deck_y + h * 0.09 + 0.045, 0)))
        for sz in (-1.0, 1.0):
            scene.add("Parapet", "secondary", box((w, 0.55, 0.24), (0, deck_y + 0.45, sz * (d / 2 - 0.12))))
        n_spans = 3
        pier_xs = [-w / 2 + w * k / n_spans for k in range(n_spans + 1)]
        for px in pier_xs[1:-1]:
            scene.add("Piers", "primary", box((w * 0.055, deck_y, d * 0.92), (px, deck_y / 2.0, 0)))
            for sz in (-1.0, 1.0):  # triangular cutwaters (rotated square prisms)
                cut = cylinder_y(d * 0.16, deck_y * 0.7, 4, (px, deck_y * 0.35, sz * d * 0.52))
                scene.add("Cutwaters", "secondary", cut)
        for s in range(n_spans):
            cx = (pier_xs[s] + pier_xs[s + 1]) / 2.0
            span = (pier_xs[s + 1] - pier_xs[s]) * 0.46
            for sz in (-1.0, 1.0):
                arch_ring(scene, "Arches", "accent", cx=cx, cy=deck_y - span - 0.1, cz=sz * (d / 2 - 0.18), radius=span, thickness=0.30, depth_t=0.30, segments=arch_segs)
        for sx in (-1.0, 1.0):
            scene.add("Abutments", "primary", box((w * 0.07, deck_y + 0.3, d), (sx * (w / 2 - w * 0.035), (deck_y + 0.3) / 2.0, 0)))
        for lx in (-w * 0.3, 0.0, w * 0.3):
            for sz in (-1.0, 1.0):
                scene.add("LampPosts", "metal", tube((lx, deck_y + 0.6, sz * (d / 2 - 0.12)), (lx, deck_y + 1.55, sz * (d / 2 - 0.12)), 0.035, 6))
                scene.add("Lamps", "glass_lamp", sphere((0.11, 0.13, 0.11), (lx, deck_y + 1.62, sz * (d / 2 - 0.12)), 1))
        return

    if preset == "chhatri_pavilion":
        step_r = min(w, d) / 2.0
        scene.add("Plinth", "secondary", cylinder_y(step_r, 0.45, 8, (0, 0.225, 0)))
        scene.add("Plinth", "accent", cylinder_y(step_r * 0.88, 0.35, 8, (0, 0.625, 0)))
        pillar_h = h * 0.46
        ring_r = step_r * 0.76
        for k in range(8):
            ang = 2 * math.pi * k / 8 + math.pi / 8
            pillar(scene, "Pillars", x=ring_r * math.cos(ang), z=ring_r * math.sin(ang), base_y=0.8, height=pillar_h, radius=step_r * 0.075, segments=8)
        ent_y = 0.8 + pillar_h + 0.22
        scene.add("Entablature", "primary", cylinder_y(step_r * 0.96, 0.42, 8, (0, ent_y + 0.21, 0)))
        scene.add("Chhajja", "secondary", cylinder_y(step_r * 1.04, 0.16, 8, (0, ent_y + 0.5, 0)))
        drum_y = ent_y + 0.58
        scene.add("DomeDrum", "accent", cylinder_y(step_r * 0.55, 0.5, 12, (0, drum_y + 0.25, 0)))
        dome_r = step_r * 0.55
        scene.add("Dome", "primary", sphere((dome_r, dome_r * 1.05, dome_r), (0, drum_y + 0.45, 0), q.sphere_subdiv))
        scene.add("Finial", "accent", cone_y(0.14, 0.6, 8, (0, drum_y + 0.45 + dome_r * 1.05 + 0.2, 0)))
        scene.add("Finial", "accent", sphere((0.11, 0.11, 0.11), (0, drum_y + 0.45 + dome_r * 1.05 + 0.03, 0), 1))
        scene.add("LampChain", "metal", tube((0, ent_y, 0), (0, ent_y - 0.85, 0), 0.025, 6))
        scene.add("Lamp", "glass_lamp", sphere((0.22, 0.26, 0.22), (0, ent_y - 1.05, 0), 2))
        scene.add("FloorMedallion", "trim", cylinder_y(step_r * 0.34, 0.06, 8, (0, 0.83, 0)))
        return

    if preset == "pol_arched_gateway":
        tower_r = d * 0.34
        tower_x = w / 2 - tower_r * 0.9
        for sx in (-1.0, 1.0):
            scene.add("Towers", "primary", cylinder_y(tower_r, h, 8, (sx * tower_x, h / 2.0, 0)))
            scene.add("Towers", "secondary", cylinder_y(tower_r * 1.12, 0.4, 8, (sx * tower_x, h + 0.2, 0)))
            scene.add("TowerCaps", "accent", sphere((tower_r * 0.7, tower_r * 0.55, tower_r * 0.7), (sx * tower_x, h + 0.38, 0), 2))
            for wy in (0.45, 0.68):
                scene.add("ArrowSlits", "trim", box((0.14, 0.65, 0.1), (sx * tower_x, h * wy, tower_r * 0.95)))
        gallery_w = tower_x * 2
        scene.add("Gallery", "primary", box((gallery_w, h - oh - 0.25, d * 0.72), (0, oh + (h - oh) / 2.0 + 0.1, 0)))
        spring_y = max(oh - ow / 2.0, oh * 0.55)
        arch_ring(scene, "Portal", "accent", cx=0, cy=spring_y, cz=d * 0.37, radius=ow / 2 + 0.1, thickness=0.34, depth_t=0.34, segments=arch_segs + 4)
        arch_ring(scene, "Portal", "accent", cx=0, cy=spring_y, cz=-d * 0.37, radius=ow / 2 + 0.1, thickness=0.34, depth_t=0.34, segments=arch_segs + 4)
        scene.add("PortalWalls", "primary", box((0.3, spring_y, d * 0.72), (-ow / 2 - 0.12, spring_y / 2.0, 0)))
        scene.add("PortalWalls", "primary", box((0.3, spring_y, d * 0.72), (ow / 2 + 0.12, spring_y / 2.0, 0)))
        for sx in (-1.0, 1.0):
            door = box((ow / 2 - 0.04, spring_y, 0.12), (sx * ow / 4.0, spring_y / 2.0, d * 0.20))
            rotate_mesh(door, sx * 0.38, (0, 1, 0), (sx * ow / 2.0, spring_y / 2.0, d * 0.20))
            scene.add("Doors", "trim", door)
            for sy in (0.3, 0.55, 0.8):
                scene.add("DoorStuds", "metal", cylinder_y(0.05, 0.07, 6, (sx * ow * 0.24, spring_y * sy, d * 0.28)))
        parapet(scene, w=gallery_w * 0.98, d=d * 0.72, top_y=h + 0.15, detail=detail)
        return

    if preset == "rajput_fort_bastion":
        wall_t = max(wt, 0.7)
        scene.add("CurtainWall", "primary", box((w, h * 0.86, wall_t), (0, h * 0.43, -d * 0.18)))
        batter = box((w, h * 0.4, wall_t * 0.7), (0, h * 0.2, -d * 0.18 + wall_t * 0.75))
        rotate_mesh(batter, 0.42, (1, 0, 0), (0, h * 0.2, -d * 0.18 + wall_t * 0.75))
        scene.add("Batter", "secondary", batter)
        tower_r = d * 0.30
        scene.add("Bastion", "primary", cylinder_y(tower_r, h * 1.04, 8, (0, h * 0.52, d * 0.16)))
        scene.add("Bastion", "secondary", cylinder_y(tower_r * 1.14, 0.42, 8, (0, h * 1.04 + 0.2, d * 0.16)))
        scene.add("BastionCap", "accent", sphere((tower_r * 0.68, tower_r * 0.5, tower_r * 0.68), (0, h * 1.04 + 0.4, d * 0.16), 2))
        spring_y = max(oh - ow / 2.0, oh * 0.55)
        # Gate passage through the bastion front
        arch_ring(scene, "Gate", "accent", cx=0, cy=spring_y, cz=d * 0.16 + tower_r * 0.9, radius=ow / 2 + 0.08, thickness=0.32, depth_t=0.3, segments=arch_segs)
        scene.add("GateDoors", "trim", box((ow - 0.06, spring_y, 0.12), (0, spring_y / 2.0, d * 0.16 + tower_r * 0.55)))
        for sx in np.linspace(-0.42, 0.42, 7):
            if abs(sx) < 0.08:
                continue
            scene.add("ArrowSlits", "trim", box((0.15, 0.7, 0.1), (float(sx) * w, h * 0.62, -d * 0.18 + wall_t / 2 + 0.05)))
        merlon_run(scene, "Crenellation", "secondary", start=(-w / 2 + 0.3, h * 0.86 + 0.28, -d * 0.18), end=(w / 2 - 0.3, h * 0.86 + 0.28, -d * 0.18), size=(0.34, 0.42, 0.26), spacing=0.9 - 0.35 * detail)
        scene.add("WallWalk", "secondary", box((w, 0.18, wall_t + 0.5), (0, h * 0.86, -d * 0.18)))
        scene.add("Plinth", "secondary", box((w * 1.02, 0.5, d), (0, 0.25, 0)))
        return

    # Default: rajasthani_haveli — enterable courtyard house shell
    scene.add("Plinth", "secondary", box((w + 0.5, 0.45, d + 0.5), (0, 0.225, 0)))
    wall_h = h - 0.45
    base = 0.45
    # Back + side walls (solid), front wall with arched portal
    scene.add("Walls", "primary", box((w, wall_h, wt), (0, base + wall_h / 2, -d / 2 + wt / 2)))
    for sx in (-1.0, 1.0):
        scene.add("Walls", "primary", box((wt, wall_h, d), (sx * (w / 2 - wt / 2), base + wall_h / 2, 0)))
    front_wall_with_portal(scene, w=w, h=wall_h, z=d / 2 - wt / 2, thickness=wt, opening_w=ow, opening_h=min(oh, wall_h - 0.6), arch_segments=arch_segs, base_y=base)
    # Shift facade pieces up by plinth height: portal was authored at ground;
    # overlay a step so the doorway reads correctly from street level.
    scene.add("Steps", "accent", box((ow + 0.8, 0.22, 0.7), (0, 0.34, d / 2 + 0.45)))
    scene.add("Steps", "accent", box((ow + 0.4, 0.22, 0.5), (0, 0.45, d / 2 + 0.22)))
    scene.add("Floor", "secondary", box((w - wt, 0.12, d - wt), (0, base + 0.06, 0)))
    # Roof slab + chhajja eaves at each floor line
    roof_y = base + wall_h
    scene.add("Roof", "secondary", box((w, 0.22, d), (0, roof_y + 0.11, 0)))
    for f in range(max(1, floors)):
        fy = base + wall_h * (f + 1) / max(1, floors)
        for sz in (-1.0, 1.0):
            eave = box((w + 0.5, 0.10, 0.55), (0, min(fy, roof_y) + 0.05, sz * (d / 2 + 0.16)))
            rotate_mesh(eave, sz * 0.18, (1, 0, 0), (0, min(fy, roof_y) + 0.05, sz * (d / 2 + 0.16)))
            scene.add("Chhajja", "accent", eave)
    # Jharokha balcony (front, upper)
    jw, jh = min(2.2, w * 0.3), 1.15
    jy = base + wall_h * (0.58 if floors > 1 else 0.5)
    scene.add("Jharokha", "secondary", box((jw, 0.16, 0.75), (0, jy, d / 2 + 0.35)))
    for sx in (-1.0, 1.0):
        scene.add("Jharokha", "accent", cylinder_y(0.07, jh, 8, (sx * (jw / 2 - 0.09), jy + jh / 2, d / 2 + 0.62)))
    scene.add("Jharokha", "primary", box((jw, 0.14, 0.8), (0, jy + jh + 0.07, d / 2 + 0.35)))
    dome_ry = jw * 0.24
    scene.add("JharokhaDome", "accent", sphere((jw * 0.30, dome_ry, jw * 0.30), (0, jy + jh + 0.14 + dome_ry * 0.55, d / 2 + 0.35), 2))
    # Window insets with arch frames on front + sides
    n_win = 2 + int(detail * 3)
    for k in range(n_win):
        wx = -w * 0.36 + w * 0.72 * (k / max(1, n_win - 1)) if n_win > 1 else 0.0
        if abs(wx) < ow * 0.75 and floors == 1:
            continue
        wy = base + wall_h * (0.72 if floors > 1 else 0.55)
        scene.add("Windows", "trim", box((0.62, 0.92, 0.08), (wx, wy, d / 2 + 0.02)))
        arch_ring(scene, "Windows", "accent", cx=wx, cy=wy + 0.46, cz=d / 2 + 0.03, radius=0.34, thickness=0.10, depth_t=0.08, segments=7)
    parapet(scene, w=w, d=d, top_y=roof_y + 0.22, detail=detail)
    if detail > 0.5:  # corner chhatri kiosks
        for sx in (-1.0, 1.0):
            kx = sx * (w / 2 - 0.75)
            scene.add("Kiosks", "secondary", cylinder_y(0.62, 0.28, 8, (kx, roof_y + 0.36, d / 2 - 0.75)))
            scene.add("Kiosks", "accent", sphere((0.52, 0.42, 0.52), (kx, roof_y + 0.55, d / 2 - 0.75), 2))


# ---------------------------------------------------------------------------
# ENVIRONMENT builders
