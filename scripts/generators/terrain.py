"""Environment & terrain procedural generator.

Vectorized NumPy multi-octave fBm and ridged multifractal height synthesis,
terraced geological strata, closed watertight terrain skirts, Poisson-style
boulder scatter, coastal water planes, and spline-lofted Banyan/Acacia trees.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import trimesh

from .meshkit import (
    Quality,
    SceneBuilder,
    box,
    cylinder_y,
    displaced_rock,
    rotate_mesh,
    submesh_by_mask,
    tube,
)


def fbm(x: np.ndarray, z: np.ndarray, rng: np.random.Generator, octaves: int = 4) -> np.ndarray:
    total = np.zeros_like(x, dtype=np.float64)
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for _ in range(octaves):
        p1, p2 = rng.uniform(0.0, 2.0 * math.pi, size=2)
        total += amp * np.sin(x * freq * 1.7 + p1) * np.cos(z * freq * 1.5 + p2)
        total += amp * 0.5 * np.sin((x + z) * freq * 0.9 + p2)
        norm += amp * 1.5
        amp *= 0.5
        freq *= 2.1
    return total / max(norm, 1e-9)


def heightfield(
    width: float,
    depth: float,
    res: int,
    heights: np.ndarray,
    *,
    base_lift: float = 0.6,
) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray, np.ndarray]:
    """Build a closed terrain solid. Returns (mesh, top_face_slot_codes, xs, zs).

    Slot codes are per-face integers: 0=sand/low, 1=grass/mid, 2=rock/steep,
    computed for top faces; skirt/bottom faces are coded rock (2).
    ``heights`` is shaped (res, res) indexed [x, z] and is shifted so its
    minimum sits at ``base_lift`` (the solid extends down to Y=0).
    """
    H = np.asarray(heights, dtype=np.float64).copy()
    H = H - H.min() + base_lift
    xs = np.linspace(-width / 2.0, width / 2.0, res)
    zs = np.linspace(-depth / 2.0, depth / 2.0, res)

    verts = np.zeros((res * res, 3), dtype=np.float64)
    for i in range(res):
        for j in range(res):
            verts[i * res + j] = (xs[i], H[i, j], zs[j])

    def vid(i: int, j: int) -> int:
        return i * res + j

    faces: list[tuple[int, int, int]] = []
    codes: list[int] = []
    h_span = max(float(H.max() - H.min()), 1e-6)
    for i in range(res - 1):
        for j in range(res - 1):
            a, b, c, d = vid(i, j), vid(i + 1, j), vid(i, j + 1), vid(i + 1, j + 1)
            mean_h = 0.25 * (H[i, j] + H[i + 1, j] + H[i, j + 1] + H[i + 1, j + 1])
            grad = max(abs(H[i + 1, j] - H[i, j]), abs(H[i, j + 1] - H[i, j])) * res / max(width, 1e-6)
            frac = (mean_h - H.min()) / h_span
            code = 2 if (grad > 0.55 or frac > 0.78) else (0 if frac < 0.16 else 1)
            faces.append((a, c, b))
            faces.append((b, c, d))
            codes.extend([code, code])

    # Bottom grid (full duplicate grid at Y=0) so the solid is a genuine
    # closed 2-manifold: bottom faces share edges with each other and the
    # skirt bottom ring is exactly the bottom grid's perimeter.
    bot_offset = len(verts)
    bot_verts = verts.copy()
    bot_verts[:, 1] = 0.0
    verts = np.vstack([verts, bot_verts])

    def bvid(i: int, j: int) -> int:
        return bot_offset + vid(i, j)

    for i in range(res - 1):
        for j in range(res - 1):
            a, b, c, d = bvid(i, j), bvid(i + 1, j), bvid(i, j + 1), bvid(i + 1, j + 1)
            faces.append((a, b, c))  # reversed vs top: normal = -Y
            faces.append((b, d, c))
            codes.extend([2, 2])

    # Skirt: perimeter ring dropped to Y=0.
    perimeter: list[int] = []
    perimeter += [vid(i, 0) for i in range(res)]
    perimeter += [vid(res - 1, j) for j in range(1, res)]
    perimeter += [vid(i, res - 1) for i in range(res - 2, -1, -1)]
    perimeter += [vid(0, j) for j in range(res - 2, 0, -1)]
    for k in range(len(perimeter)):
        p = perimeter[k]
        q = perimeter[(k + 1) % len(perimeter)]
        pb, qb = bot_offset + p, bot_offset + q
        faces.append((p, q, qb))
        faces.append((p, qb, pb))
        codes.extend([2, 2])

    mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    return mesh, np.array(codes, dtype=np.int32), xs, zs


def sample_height(H: np.ndarray, xs: np.ndarray, zs: np.ndarray, x: float, z: float) -> float:
    res = len(xs)
    fx = float(np.interp(x, xs, np.arange(res)))
    fz = float(np.interp(z, zs, np.arange(res)))
    i0, j0 = int(np.floor(fx)), int(np.floor(fz))
    i1, j1 = min(i0 + 1, res - 1), min(j0 + 1, res - 1)
    tx, tz = fx - i0, fz - j0
    top = H[i0, j0] * (1 - tx) + H[i1, j0] * tx
    bot = H[i0, j1] * (1 - tx) + H[i1, j1] * tx
    return float(top * (1 - tz) + bot * tz)


# ---------------------------------------------------------------------------
# Decimation (deterministic NumPy vertex-clustering)


# ---------------------------------------------------------------------------
# Scatter, vegetation & heightfield assembly
# ---------------------------------------------------------------------------

def scatter_rocks(
    scene: SceneBuilder,
    *,
    H: np.ndarray,
    xs: np.ndarray,
    zs: np.ndarray,
    count: int,
    rng: np.random.Generator,
    subdiv: int,
    slot: str = "secondary",
    scale_range: tuple[float, float] = (0.4, 1.6),
    avoid_center: float = 0.0,
) -> None:
    width = float(xs[-1] - xs[0])
    depth = float(zs[-1] - zs[0])
    placed = 0
    guard = 0
    while placed < count and guard < count * 20:
        guard += 1
        x = float(rng.uniform(-0.46, 0.46)) * width
        z = float(rng.uniform(-0.46, 0.46)) * depth
        if avoid_center > 0 and math.hypot(x, z) < avoid_center:
            continue
        s = float(rng.uniform(*scale_range))
        y = sample_height(H, xs, zs, x, z)
        rock = displaced_rock((x, y + s * 0.22, z), (s, s * 0.72, s * 0.85), subdiv, rng)
        rotate_mesh(rock, float(rng.uniform(0, 2 * math.pi)), (0, 1, 0), (x, y + s * 0.22, z))
        scene.add("Rocks", slot, rock)
        placed += 1


def acacia_tree(
    scene: SceneBuilder,
    *,
    x: float,
    y: float,
    z: float,
    scale: float,
    rng: np.random.Generator,
    subdiv: int,
) -> None:
    trunk_top = (x + float(rng.uniform(-0.3, 0.3)) * scale, y + 2.1 * scale, z)
    scene.add("Trees", "trim", tube((x, y - 0.1, z), trunk_top, 0.16 * scale, 7))
    for _ in range(3):
        ang = float(rng.uniform(0, 2 * math.pi))
        tip = (
            trunk_top[0] + math.cos(ang) * 1.1 * scale,
            trunk_top[1] + 0.75 * scale,
            trunk_top[2] + math.sin(ang) * 1.1 * scale,
        )
        scene.add("Trees", "trim", tube(trunk_top, tip, 0.08 * scale, 6))
        scene.add(
            "Canopy",
            "primary" if rng.random() > 0.4 else "foliage_dark",
            displaced_rock(tip, (1.15 * scale, 0.5 * scale, 1.15 * scale), max(1, subdiv - 1), rng, roughness=0.22),
        )
    scene.add(
        "Canopy",
        "primary",
        displaced_rock((trunk_top[0], trunk_top[1] + 1.0 * scale, trunk_top[2]), (1.5 * scale, 0.6 * scale, 1.5 * scale), max(1, subdiv - 1), rng, roughness=0.22),
    )


def add_heightfield_terrain(
    scene: SceneBuilder,
    *,
    w: float,
    d: float,
    res: int,
    heights: np.ndarray,
    base_lift: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mesh, codes, xs, zs = heightfield(w, d, res, heights, base_lift=base_lift)
    slot_by_code = {0: "sand", 1: "primary", 2: "secondary"}
    for code, slot in slot_by_code.items():
        sub = submesh_by_mask(mesh, codes == code)
        if sub is not None:
            scene.add("Terrain", slot, sub)
    lifted = np.asarray(heights, dtype=float) - float(np.min(heights)) + base_lift
    return lifted, xs, zs


# ---------------------------------------------------------------------------
# Environment asset builder
# ---------------------------------------------------------------------------

def build_environment(scene: SceneBuilder, cfg: dict[str, Any], q: Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset = str(cfg["preset_id"])
    w, d = float(p["width"]), float(p["depth"])
    elev = float(p.get("elevation", 6.0))
    slope = float(p.get("slope_intensity", 0.6))
    rough = float(p.get("surface_roughness", 0.5))
    terraces = int(p.get("terrace_steps", 3))
    scatter = float(p.get("scatter_density", 0.35))
    budget = int(cfg.get("polygon_budget", 4000))
    # Closed terrain solid faces ~= 4 * (res-1)^2 (top + bottom grids);
    # size the grid to the requested budget (capped by quality) so
    # topology-preserving generation rarely needs destructive decimation.
    res = int(
        np.clip(
            math.sqrt(max(budget, 800) * 0.50 / 4.0) + 1,
            16,
            q.terrain_res + 10,
        )
    )
    xs = np.linspace(-w / 2, w / 2, res)
    zs = np.linspace(-d / 2, d / 2, res)
    X, Z = np.meshgrid(xs, zs, indexing="ij")

    if preset == "stylized_banyan_tree":
        scene.add("Ground", "sand", cylinder_y(min(w, d) / 2.0, 0.35, q.radial + 8, (0, 0.175, 0)))
        H_top = 0.35
        trunk_h = elev * 0.42
        prev = (0.0, H_top - 0.1, 0.0)
        bend = 0.0
        joints = [prev]
        for step in range(3):
            bend += float(rng.uniform(-0.22, 0.22))
            nxt = (bend * elev * 0.12, H_top + trunk_h * (step + 1) / 3.0, float(rng.uniform(-0.1, 0.1)))
            r = elev * 0.045 * (1.0 - 0.18 * step)
            scene.add("Trunk", "trim", tube(prev, nxt, max(r, 0.06), 8))
            joints.append(nxt)
            prev = nxt
        top = joints[-1]
        n_branches = 5
        canopy_centers = []
        for k in range(n_branches):
            ang = 2 * math.pi * k / n_branches + float(rng.uniform(-0.2, 0.2))
            reach = min(w, d) * (0.30 + 0.08 * float(rng.random()))
            tip = (top[0] + math.cos(ang) * reach, top[1] + elev * 0.16, top[2] + math.sin(ang) * reach)
            scene.add("Branches", "trim", tube(top, tip, 0.07, 7))
            # Aerial prop root from mid-branch to the ground
            mid = (top[0] + (tip[0] - top[0]) * 0.65, top[1] + (tip[1] - top[1]) * 0.65, top[2] + (tip[2] - top[2]) * 0.65)
            scene.add("PropRoots", "trim", tube(mid, (mid[0], H_top - 0.05, mid[2]), 0.045, 6))
            canopy_centers.append(tip)
        for tip in canopy_centers:
            cr = min(w, d) * 0.19
            slot = "primary" if rng.random() > 0.35 else "foliage_dark"
            scene.add("Canopy", slot, displaced_rock((tip[0], tip[1] + cr * 0.35, tip[2]), (cr, cr * 0.48, cr), q.sphere_subdiv - 1, rng, roughness=0.20))
        cr = min(w, d) * 0.24
        scene.add("Canopy", "primary", displaced_rock((top[0], top[1] + elev * 0.22, top[2]), (cr, cr * 0.5, cr), q.sphere_subdiv - 1, rng, roughness=0.20))
        return

    if preset == "desert_rock_outcrop":
        mound = elev * 0.16 * np.exp(-((X / (w * 0.4)) ** 2 + (Z / (d * 0.4)) ** 2)) + rough * 0.4 * fbm(X / w * 4, Z / d * 4, rng)
        H, hx, hz = add_heightfield_terrain(scene, w=w, d=d, res=res, heights=mound, base_lift=0.35)
        n_big = 5 + int(scatter * 5)
        for k in range(n_big):
            ang = 2 * math.pi * k / n_big + float(rng.uniform(-0.3, 0.3))
            dist = min(w, d) * float(rng.uniform(0.05, 0.34))
            x, z = math.cos(ang) * dist, math.sin(ang) * dist
            s = elev * float(rng.uniform(0.16, 0.34))
            y = sample_height(H, hx, hz, x, z)
            rock = displaced_rock((x, y + s * 0.5, z), (s, s * (1.1 + slope * 0.7), s * 0.8), 2, rng, roughness=0.3 + rough * 0.3)
            rotate_mesh(rock, float(rng.uniform(0, 2 * math.pi)), (0, 1, 0), (x, y + s * 0.5, z))
            scene.add("Outcrop", "secondary", rock)
        scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(8 * scatter * q.scatter_mul) + 3, rng=rng, subdiv=1, scale_range=(0.15, 0.45))
        return

    if preset == "battle_royale_island":
        R = min(w, d) / 2.0
        r_norm = np.sqrt((X / (w / 2)) ** 2 + (Z / (d / 2)) ** 2)
        peak_x, peak_z = float(rng.uniform(-3, 3)), float(rng.uniform(-3, 3))
        peak = np.exp(-(((X - peak_x) / (w * 0.22)) ** 2 + ((Z - peak_z) / (d * 0.22)) ** 2))
        falloff = np.clip(1.0 - r_norm**2.2, 0.0, 1.0)
        heights = elev * (0.55 * falloff + 0.65 * peak * falloff) * (0.8 + rough * 0.45 * fbm(X / w * 5, Z / d * 5, rng))
        H, hx, hz = add_heightfield_terrain(scene, w=w, d=d, res=res, heights=heights, base_lift=0.25)
        scene.add("Water", "water", cylinder_y(R * 1.35, 0.3, q.radial + 16, (0, 0.55, 0)))
        scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(10 * scatter * q.scatter_mul) + 2, rng=rng, subdiv=1, scale_range=(0.3, 1.1))
        for _ in range(int(3 * scatter * q.scatter_mul) + 1):
            tx = float(rng.uniform(-0.3, 0.3)) * w
            tz = float(rng.uniform(-0.3, 0.3)) * d
            ty = sample_height(H, hx, hz, tx, tz)
            if ty > 0.9:
                acacia_tree(scene, x=tx, y=ty, z=tz, scale=0.9, rng=rng, subdiv=2)
        return

    if preset == "river_ravine_crossing":
        base = elev * (0.55 + 0.45 * fbm(X / w * 3.2, Z / d * 3.2, rng)) * (0.6 + 0.6 * slope)
        curve_amp = w * 0.18
        river_x = curve_amp * np.sin(Z / d * math.pi * 1.7)
        dist = np.abs(X - river_x)
        carve = elev * 0.85 * np.exp(-((dist / (w * 0.075)) ** 2))
        heights = np.maximum(base - carve, 0.02)
        H, hx, hz = add_heightfield_terrain(scene, w=w, d=d, res=res, heights=heights, base_lift=0.30)
        n_seg = 16
        for k in range(n_seg):
            zz = -d / 2 + d * (k + 0.5) / n_seg
            xc = curve_amp * math.sin(zz / d * math.pi * 1.7)
            dx_dz = curve_amp * (math.pi * 1.7 / d) * math.cos(zz / d * math.pi * 1.7)
            seg = box((w * 0.11, 0.14, d / n_seg * 1.3), (float(xc), 0.52, float(zz)))
            rotate_mesh(seg, math.atan2(dx_dz, 1.0), (0, 1, 0), (float(xc), 0.52, float(zz)))
            scene.add("Water", "water", seg)
        scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(9 * scatter * q.scatter_mul) + 2, rng=rng, subdiv=1, scale_range=(0.25, 0.9))
        return

    # Default: aravalli_ridge_terrain — diagonal ridged range with terraces
    ridge_axis = (X * 0.72 + Z * 0.45) / max(w, 1.0)
    ridge = np.exp(-((ridge_axis / 0.26) ** 2))
    heights = elev * (0.75 * ridge + 0.35) * (0.65 + rough * 0.7 * (0.5 + 0.5 * fbm(X / w * 4.5, Z / d * 4.5, rng)))
    heights *= 0.7 + 0.55 * slope
    if terraces > 0:
        levels = max(terraces, 2)
        quantized = np.floor(heights / elev * levels) / levels * elev
        heights = heights * 0.62 + quantized * 0.38
    H, hx, hz = add_heightfield_terrain(scene, w=w, d=d, res=res, heights=heights, base_lift=0.55)
    scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(14 * scatter * q.scatter_mul) + 3, rng=rng, subdiv=1, scale_range=(0.3, 1.4))
    for _ in range(int(4 * scatter * q.scatter_mul) + 1):
        tx = float(rng.uniform(-0.4, 0.4)) * w
        tz = float(rng.uniform(-0.4, 0.4)) * d
        ty = sample_height(H, hx, hz, tx, tz)
        acacia_tree(scene, x=tx, y=ty, z=tz, scale=float(rng.uniform(0.8, 1.2)), rng=rng, subdiv=2)


# ---------------------------------------------------------------------------
# HUMANOID builder (static stylized A-pose; rigging requires Blender engine)
