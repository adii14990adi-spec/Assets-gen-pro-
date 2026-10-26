"""Procedural Mid-Poly Stylized Female T-Pose Character Generator.

Constructs a symmetrical, game-ready stylized female character in a true
horizontal T-pose purely from Python code using ``numpy``, ``scipy``
(cubic spline anatomical profiles & 3D curve frames), and ``trimesh``.

Articulated anatomical & outfit segments constructed:
  - Head (cranium, feminine jawline/chin, nose bridge, ears, stylized eyes)
  - Hair (sculpted crown cap, side-swept bangs, tie band, curved 3D ponytail)
  - Neck (tapered column with clavicular base flare)
  - Torso with athletic sports top & collar trim
  - Toned waist / midriff
  - Shorts / pelvis + fitted upper-thigh cuffs + waistband
  - Symmetrical T-pose deltoids, upper arms, elbows, and forearms (+X / -X)
  - Symmetrical T-pose hands (contoured palms, forward thumbs, articulated fingers)
  - Symmetrical thighs, knees, sculpted gastrocnemius calves, and ankles
  - Grounded athletic sneakers / feet planted cleanly at Y = 0.0
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import trimesh
from scipy.interpolate import CubicSpline
from scipy.spatial.transform import Rotation

HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DEFAULT_SKIN_HEX = "#e6a88a"
DEFAULT_OUTFIT_HEX = "#3b82f6"
DEFAULT_HAIR_HEX = "#2c1d18"


def parse_hex_color(value: str | None, fallback: str = DEFAULT_SKIN_HEX) -> tuple[float, float, float]:
    """Parse ``#RRGGBB`` or ``#RGB`` hex string into normalized sRGB ``(r, g, b)``."""
    raw = (value or "").strip()
    if not HEX_COLOR_RE.match(raw):
        raw = fallback
    h = raw.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


def normalize_hex_color(value: str | None, fallback: str) -> str:
    """Return canonical lowercase ``#rrggbb`` string, raising ValueError if invalid when provided."""
    if value is None or not str(value).strip():
        r, g, b = parse_hex_color(fallback, fallback)
        return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"
    raw = str(value).strip()
    if not HEX_COLOR_RE.match(raw):
        raise ValueError(f"Invalid hex color {value!r}; expected #RRGGBB or #RGB.")
    r, g, b = parse_hex_color(raw, fallback)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def _mix_rgb(
    a: tuple[float, float, float], b: tuple[float, float, float], t: float
) -> tuple[float, float, float]:
    return (
        float(np.clip(a[0] * (1.0 - t) + b[0] * t, 0.0, 1.0)),
        float(np.clip(a[1] * (1.0 - t) + b[1] * t, 0.0, 1.0)),
        float(np.clip(a[2] * (1.0 - t) + b[2] * t, 0.0, 1.0)),
    )


def build_character_palette(
    skin_color: str | None = None,
    outfit_color: str | None = None,
    hair_color: str | None = None,
) -> dict[str, tuple[tuple[float, float, float], float, float]]:
    """Return ``{slot: (srgb_tuple, metallic, roughness)}`` driven by hex colors."""
    skin_rgb = parse_hex_color(skin_color, DEFAULT_SKIN_HEX)
    outfit_rgb = parse_hex_color(outfit_color, DEFAULT_OUTFIT_HEX)
    hair_rgb = parse_hex_color(hair_color, DEFAULT_HAIR_HEX)

    shorts_rgb = _mix_rgb(outfit_rgb, (0.09, 0.11, 0.16), 0.34)
    trim_rgb = _mix_rgb(outfit_rgb, (0.96, 0.97, 0.99), 0.72)
    accent_rgb = _mix_rgb(outfit_rgb, (1.0, 0.85, 0.35), 0.25)

    return {
        "skin": (skin_rgb, 0.0, 0.58),
        "outfit": (outfit_rgb, 0.04, 0.46),
        "shorts": (shorts_rgb, 0.03, 0.54),
        "outfit_trim": (trim_rgb, 0.02, 0.42),
        "outfit_accent": (accent_rgb, 0.08, 0.38),
        "hair": (hair_rgb, 0.02, 0.64),
        "sole": ((0.13, 0.15, 0.20), 0.05, 0.82),
        "eye": ((0.11, 0.13, 0.19), 0.08, 0.25),
    }


def _stitch_closed_rings(rings: np.ndarray) -> trimesh.Trimesh:
    """Convert ``(R, S, 3)`` ordered rings into a closed watertight 2-manifold Trimesh."""
    n_rings, radial, _ = rings.shape
    if n_rings < 2 or radial < 3:
        raise ValueError("Need at least 2 rings and 3 radial vertices to loft a solid.")

    bot_cap = rings[0].mean(axis=0, keepdims=True)
    top_cap = rings[-1].mean(axis=0, keepdims=True)
    flat_rings = rings.reshape(-1, 3)
    bot_idx = len(flat_rings)
    top_idx = len(flat_rings) + 1
    vertices = np.vstack([flat_rings, bot_cap, top_cap])

    faces: list[tuple[int, int, int]] = []
    # Bottom fan
    for s in range(radial):
        s_next = (s + 1) % radial
        faces.append((bot_idx, s_next, s))

    # Quad strips split cleanly into non-degenerate triangles
    for r in range(n_rings - 1):
        base0 = r * radial
        base1 = (r + 1) * radial
        for s in range(radial):
            s_next = (s + 1) % radial
            a = base0 + s
            b = base0 + s_next
            c = base1 + s_next
            d = base1 + s
            faces.append((a, b, c))
            faces.append((a, c, d))

    # Top fan
    last_base = (n_rings - 1) * radial
    for s in range(radial):
        s_next = (s + 1) % radial
        faces.append((top_idx, last_base + s, last_base + s_next))

    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    if mesh.volume < 0.0:
        mesh.invert()
    return mesh


def _loft_vertical_profile(
    stations: list[tuple[float, float, float, float, float]],
    *,
    n_rings: int,
    radial: int,
    superellipse_n: float = 2.0,
) -> trimesh.Trimesh:
    """Loft a vertical (+Y) anatomical segment via ``scipy.interpolate.CubicSpline``.

    Each station is ``(y, rx, rz, cx, cz)`` in meters.
    """
    arr = np.asarray(stations, dtype=np.float64)
    t_knots = np.linspace(0.0, 1.0, len(arr))
    bc = "clamped" if len(arr) >= 4 else "not-a-knot"
    cs = CubicSpline(t_knots, arr, axis=0, bc_type=bc)
    ts = np.linspace(0.0, 1.0, max(2, n_rings))
    sampled = cs(ts)  # (n_rings, 5)

    angles = np.linspace(0.0, 2.0 * math.pi, radial, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)
    if abs(superellipse_n - 2.0) > 1e-3:
        exp = 2.0 / superellipse_n
        ux = np.sign(cos_a) * (np.abs(cos_a) ** exp)
        uz = np.sign(sin_a) * (np.abs(sin_a) ** exp)
    else:
        ux, uz = cos_a, sin_a

    rings = np.zeros((len(ts), radial, 3), dtype=np.float64)
    for idx in range(len(ts)):
        y, rx, rz, cx, cz = sampled[idx]
        rx_safe = max(float(rx), 1e-4)
        rz_safe = max(float(rz), 1e-4)
        rings[idx, :, 0] = cx + rx_safe * ux
        rings[idx, :, 1] = y
        rings[idx, :, 2] = cz + rz_safe * uz

    return _stitch_closed_rings(rings)


def _loft_horizontal_arm(
    stations: list[tuple[float, float, float, float, float]],
    *,
    side: float,
    n_rings: int,
    radial: int,
) -> trimesh.Trimesh:
    """Loft a symmetrical T-pose limb horizontally along ``side * +X``.

    Each station is ``(abs_x, ry, rz, cy, cz)`` in meters; ``side`` is ``-1.0`` or ``+1.0``.
    """
    arr = np.asarray(stations, dtype=np.float64)
    t_knots = np.linspace(0.0, 1.0, len(arr))
    bc = "clamped" if len(arr) >= 4 else "not-a-knot"
    cs = CubicSpline(t_knots, arr, axis=0, bc_type=bc)
    ts = np.linspace(0.0, 1.0, max(2, n_rings))
    sampled = cs(ts)

    angles = np.linspace(0.0, 2.0 * math.pi, radial, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    rings = np.zeros((len(ts), radial, 3), dtype=np.float64)
    for idx in range(len(ts)):
        ax, ry, rz, cy, cz = sampled[idx]
        ry_safe = max(float(ry), 1e-4)
        rz_safe = max(float(rz), 1e-4)
        rings[idx, :, 0] = side * float(ax)
        rings[idx, :, 1] = cy + ry_safe * cos_a
        rings[idx, :, 2] = cz + rz_safe * sin_a

    return _stitch_closed_rings(rings)


def _loft_along_3d_spline(
    control_points: list[tuple[float, float, float, float, float]],
    *,
    n_rings: int,
    radial: int,
) -> trimesh.Trimesh:
    """Sweep elliptical cross-sections along a 3D ``CubicSpline`` curve using parallel transport.

    Each control point is ``(x, y, z, r_major, r_minor)``.
    """
    arr = np.asarray(control_points, dtype=np.float64)
    t_knots = np.linspace(0.0, 1.0, len(arr))
    cs_pos = CubicSpline(t_knots, arr[:, :3], axis=0)
    cs_rad = CubicSpline(t_knots, arr[:, 3:], axis=0)

    ts = np.linspace(0.0, 1.0, max(3, n_rings))
    pts = cs_pos(ts)
    tangents = cs_pos(ts, 1)
    t_norms = np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), 1e-9)
    tangents = tangents / t_norms
    radii = np.maximum(cs_rad(ts), 1e-4)

    # Parallel-transport Bishop frame along the spline
    ref = np.array([1.0, 0.0, 0.0]) if abs(tangents[0, 0]) < 0.85 else np.array([0.0, 1.0, 0.0])
    normal = np.cross(tangents[0], ref)
    normal /= max(float(np.linalg.norm(normal)), 1e-9)

    angles = np.linspace(0.0, 2.0 * math.pi, radial, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    rings = np.zeros((len(ts), radial, 3), dtype=np.float64)
    for i in range(len(ts)):
        if i > 0:
            axis = np.cross(tangents[i - 1], tangents[i])
            sin_t = float(np.linalg.norm(axis))
            if sin_t > 1e-7:
                cos_t = float(np.clip(np.dot(tangents[i - 1], tangents[i]), -1.0, 1.0))
                rot = Rotation.from_rotvec((axis / sin_t) * math.atan2(sin_t, cos_t))
                normal = rot.apply(normal)
                normal -= np.dot(normal, tangents[i]) * tangents[i]
                normal /= max(float(np.linalg.norm(normal)), 1e-9)
        binormal = np.cross(tangents[i], normal)
        r_maj, r_min = float(radii[i, 0]), float(radii[i, 1])
        rings[i] = (
            pts[i][None, :]
            + (r_maj * cos_a)[:, None] * normal[None, :]
            + (r_min * sin_a)[:, None] * binormal[None, :]
        )

    return _stitch_closed_rings(rings)


def _oriented_capsule(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    r0: float,
    r1: float,
    radial: int,
) -> trimesh.Trimesh:
    """Build a closed tapered 4-ring capsule between 3D points ``p0`` and ``p1``."""
    a = np.asarray(p0, dtype=np.float64)
    b = np.asarray(p1, dtype=np.float64)
    vec = b - a
    length = max(float(np.linalg.norm(vec)), 1e-5)
    t_dir = vec / length
    ref = np.array([0.0, 1.0, 0.0]) if abs(t_dir[1]) < 0.85 else np.array([0.0, 0.0, 1.0])
    u = np.cross(t_dir, ref)
    u /= max(float(np.linalg.norm(u)), 1e-9)
    v = np.cross(t_dir, u)

    angles = np.linspace(0.0, 2.0 * math.pi, radial, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    fractions = [
        (-0.22 * r0 / length, r0 * 0.48),
        (0.0, r0),
        (0.55, 0.5 * (r0 + r1)),
        (1.0, r1),
        (1.0 + 0.22 * r1 / length, r1 * 0.45),
    ]
    rings = np.zeros((len(fractions), radial, 3), dtype=np.float64)
    for idx, (frac, rad) in enumerate(fractions):
        c = a + frac * vec
        rings[idx] = c[None, :] + (rad * cos_a)[:, None] * u[None, :] + (rad * sin_a)[:, None] * v[None, :]
    return _stitch_closed_rings(rings)


def build_stylized_female_tpose_parts(
    *,
    target_faces: int = 1800,
    height: float = 1.72,
    rng: np.random.Generator | None = None,
    parameters: dict[str, Any] | None = None,
) -> list[tuple[str, str, trimesh.Trimesh]]:
    """Construct articulated mid-poly stylized female character parts in a symmetrical T-pose.

    Returns ``[(part_name, material_slot, mesh), ...]`` in glTF space (meters, +Y up, Y_min=0).
    """
    params = parameters or {}
    H = float(params.get("height", height))
    athletic = float(params.get("musculature", 0.52))
    shoulder_scale = float(params.get("shoulder_width", 1.0))
    hip_scale = float(params.get("hip_width", 1.0))
    ponytail_len = float(params.get("ponytail_length", 1.0))
    rng_local = rng or np.random.default_rng(42)
    # Subtle seed-driven proportion micro-variation (keeps silhouette clean & deterministic)
    ponytail_sway = float(rng_local.uniform(-0.010, 0.010)) * H

    # Choose radial & longitudinal ring densities so native face count tracks target_faces cleanly
    clamped_target = max(360, min(int(target_faces), 30_000))
    density = math.sqrt(clamped_target / 4100.0)
    compact_lowpoly = clamped_target < 650

    rad_torso = int(np.clip(round(14 * density), 5 if compact_lowpoly else 6, 30))
    rad_head = int(np.clip(round(14 * density), 5 if compact_lowpoly else 6, 28))
    rad_limb = int(np.clip(round(10 * density), 4 if compact_lowpoly else 5, 22))
    rad_small = int(np.clip(round(6 * density), 3 if compact_lowpoly else 4, 14))
    ring_scale = float(np.clip(density, 0.36 if compact_lowpoly else 0.48, 2.30))
    articulated_fingers = clamped_target >= 1100

    def rings(base: int, minimum: int = 3) -> int:
        floor_r = 2 if (compact_lowpoly and minimum <= 3) else minimum
        return max(floor_r, int(round(base * ring_scale)))

    parts: list[tuple[str, str, trimesh.Trimesh]] = []

    # ------------------------------------------------------------------
    # 1. HEAD (Cranium, Cheekbones, Feminine Jawline, Nose, Ears, Eyes)
    # ------------------------------------------------------------------
    head_stations = [
        (0.858 * H, 0.032 * H, 0.036 * H, 0.0, 0.008 * H),   # chin base
        (0.876 * H, 0.048 * H, 0.056 * H, 0.0, 0.010 * H),   # jawline
        (0.902 * H, 0.060 * H, 0.066 * H, 0.0, 0.004 * H),   # cheekbones
        (0.934 * H, 0.064 * H, 0.072 * H, 0.0, -0.004 * H),  # brow / mid-cranium
        (0.966 * H, 0.058 * H, 0.066 * H, 0.0, -0.008 * H),  # upper cranium
        (0.986 * H, 0.032 * H, 0.036 * H, 0.0, -0.010 * H),  # crown apex
    ]
    parts.append(("Head", "skin", _loft_vertical_profile(head_stations, n_rings=rings(8, 4), radial=rad_head)))

    # Sculpted nose bridge (+Z) & symmetrical ears/eyes
    if not compact_lowpoly:
        nose = _loft_vertical_profile(
            [
                (0.896 * H, 0.009 * H, 0.012 * H, 0.0, 0.066 * H),
                (0.906 * H, 0.008 * H, 0.017 * H, 0.0, 0.073 * H),
                (0.922 * H, 0.006 * H, 0.010 * H, 0.0, 0.066 * H),
            ],
            n_rings=max(3, rings(4, 3)),
            radial=max(4, rad_small),
        )
        parts.append(("Head", "skin", nose))

        for side in (-1.0, 1.0):
            ear = _loft_vertical_profile(
                [
                    (0.902 * H, 0.007 * H, 0.011 * H, side * 0.062 * H, -0.004 * H),
                    (0.916 * H, 0.010 * H, 0.015 * H, side * 0.066 * H, -0.006 * H),
                    (0.930 * H, 0.007 * H, 0.010 * H, side * 0.061 * H, -0.005 * H),
                ],
                n_rings=3,
                radial=max(4, rad_small),
            )
            parts.append(("Head", "skin", ear))

            eye = _loft_vertical_profile(
                [
                    (0.914 * H, 0.011 * H, 0.005 * H, side * 0.023 * H, 0.063 * H),
                    (0.921 * H, 0.013 * H, 0.006 * H, side * 0.024 * H, 0.065 * H),
                    (0.927 * H, 0.010 * H, 0.005 * H, side * 0.023 * H, 0.063 * H),
                ],
                n_rings=3,
                radial=max(4, rad_small),
            )
            parts.append(("Eyes", "eye", eye))

    # ------------------------------------------------------------------
    # 2. HAIR CAP, SIDE-SWEPT BANGS, SCRUNCHIE TIE & CURVED PONYTAIL
    # ------------------------------------------------------------------
    hair_cap_stations = [
        (0.892 * H, 0.056 * H, 0.048 * H, 0.0, -0.030 * H),  # nape
        (0.926 * H, 0.067 * H, 0.068 * H, 0.0, -0.014 * H),  # temple wrap
        (0.956 * H, 0.069 * H, 0.076 * H, 0.0, -0.006 * H),  # full crown volume
        (0.985 * H, 0.056 * H, 0.064 * H, 0.0, -0.006 * H),  # upper dome
        (1.002 * H, 0.026 * H, 0.030 * H, 0.0, -0.008 * H),  # top crest
    ]
    parts.append(("Hair", "hair", _loft_vertical_profile(hair_cap_stations, n_rings=rings(6, 3), radial=rad_head)))

    # Framing front bangs (left & right temple locks)
    if not compact_lowpoly:
        for side in (-1.0, 1.0):
            bang_curve = [
                (side * 0.012 * H, 0.980 * H, 0.052 * H, 0.016 * H, 0.010 * H),
                (side * 0.038 * H, 0.958 * H, 0.058 * H, 0.020 * H, 0.011 * H),
                (side * 0.054 * H, 0.928 * H, 0.046 * H, 0.015 * H, 0.009 * H),
                (side * 0.058 * H, 0.898 * H, 0.028 * H, 0.006 * H, 0.005 * H),
            ]
            parts.append(("Hair", "hair", _loft_along_3d_spline(bang_curve, n_rings=rings(5, 3), radial=max(5, rad_small))))

    # Hair tie / scrunchie at high crown-back
    scrunchie_curve = [
        (0.0, 0.950 * H, -0.068 * H, 0.022 * H, 0.022 * H),
        (0.0, 0.946 * H, -0.080 * H, 0.025 * H, 0.025 * H),
        (0.0, 0.942 * H, -0.091 * H, 0.020 * H, 0.020 * H),
    ]
    parts.append(("HairTie", "outfit_accent", _loft_along_3d_spline(scrunchie_curve, n_rings=2 if compact_lowpoly else 3, radial=max(4 if compact_lowpoly else 6, rad_small))))

    # Dynamic curved stylized ponytail cascading down behind the head
    tail_drop = 0.21 * H * ponytail_len
    ponytail_curve = [
        (0.0, 0.944 * H, -0.086 * H, 0.019 * H, 0.018 * H),
        (ponytail_sway * 0.3, 0.955 * H, -0.125 * H, 0.034 * H, 0.028 * H),
        (ponytail_sway * 0.7, 0.905 * H - 0.18 * tail_drop, -0.158 * H, 0.040 * H, 0.031 * H),
        (ponytail_sway * 1.0, 0.835 * H - 0.55 * tail_drop, -0.165 * H, 0.030 * H, 0.023 * H),
        (ponytail_sway * 0.8, 0.775 * H - 0.85 * tail_drop, -0.148 * H, 0.015 * H, 0.012 * H),
        (ponytail_sway * 0.5, 0.742 * H - 1.00 * tail_drop, -0.132 * H, 0.004 * H, 0.004 * H),
    ]
    parts.append(
        ("Ponytail", "hair", _loft_along_3d_spline(ponytail_curve, n_rings=rings(9, 5), radial=max(6, rad_limb)))
    )

    # ------------------------------------------------------------------
    # 3. NECK & UPPER CLAVICLE SKIN
    # ------------------------------------------------------------------
    neck_stations = [
        (0.808 * H, 0.056 * H * shoulder_scale, 0.042 * H, 0.0, 0.002 * H),  # trapezius / collar base
        (0.826 * H, 0.033 * H, 0.032 * H, 0.0, 0.001 * H),                   # lower neck
        (0.850 * H, 0.029 * H, 0.029 * H, 0.0, 0.003 * H),                   # mid neck
        (0.874 * H, 0.031 * H, 0.031 * H, 0.0, 0.005 * H),                   # sub-jaw insertion
    ]
    parts.append(("Neck", "skin", _loft_vertical_profile(neck_stations, n_rings=rings(5, 3), radial=rad_limb)))

    # ------------------------------------------------------------------
    # 4. TORSO WITH ATHLETIC SPORTS TOP & COLLAR TRIM
    # ------------------------------------------------------------------
    bust_z = (0.074 + 0.010 * athletic) * H
    rib_x = (0.076 + 0.010 * athletic) * H * shoulder_scale
    sh_x = 0.104 * H * shoulder_scale

    athletic_top_stations = [
        (0.636 * H, 0.068 * H, 0.049 * H, 0.0, 0.002 * H),       # crop-top lower hem
        (0.668 * H, rib_x * 0.96, 0.056 * H, 0.0, 0.005 * H),    # underbust ribcage
        (0.724 * H, rib_x * 1.08, bust_z, 0.0, 0.014 * H),       # bust / chest contour (+Z)
        (0.772 * H, sh_x * 0.98, 0.060 * H, 0.0, 0.004 * H),     # upper chest / axillary line
        (0.806 * H, sh_x * 0.88, 0.048 * H, 0.0, -0.002 * H),    # shoulder bridge
        (0.818 * H, 0.052 * H, 0.038 * H, 0.0, 0.000 * H),       # scoop collar top
    ]
    parts.append(
        (
            "AthleticTop",
            "outfit",
            _loft_vertical_profile(athletic_top_stations, n_rings=rings(9, 5), radial=rad_torso, superellipse_n=2.25),
        )
    )

    # Crisp crop-top lower trim band
    if not compact_lowpoly:
        top_hem_trim = _loft_vertical_profile(
            [
                (0.628 * H, 0.067 * H, 0.048 * H, 0.0, 0.001 * H),
                (0.635 * H, 0.070 * H, 0.051 * H, 0.0, 0.002 * H),
                (0.642 * H, 0.069 * H, 0.050 * H, 0.0, 0.002 * H),
            ],
            n_rings=3,
            radial=rad_torso,
            superellipse_n=2.25,
        )
        parts.append(("AthleticTopTrim", "outfit_trim", top_hem_trim))

    # ------------------------------------------------------------------
    # 5. WAIST / TONED MIDRIFF (SKIN)
    # ------------------------------------------------------------------
    waist_x = 0.062 * H
    hip_x = 0.094 * H * hip_scale
    waist_stations = [
        (0.558 * H, hip_x * 0.88, 0.058 * H, 0.0, -0.003 * H),   # upper iliac flare
        (0.596 * H, waist_x, 0.046 * H, 0.0, 0.001 * H),         # narrow natural waist
        (0.634 * H, 0.067 * H, 0.048 * H, 0.0, 0.002 * H),       # joins crop-top hem
    ]
    parts.append(
        (
            "Waist",
            "skin",
            _loft_vertical_profile(waist_stations, n_rings=rings(5, 3), radial=rad_torso, superellipse_n=2.2),
        )
    )

    # ------------------------------------------------------------------
    # 6. SHORTS / PELVIS + WAISTBAND + FITTED SHORT CUFFS
    # ------------------------------------------------------------------
    pelvis_stations = [
        (0.468 * H, hip_x * 0.84, 0.056 * H, 0.0, -0.006 * H),   # pelvis saddle
        (0.506 * H, hip_x * 1.02, 0.068 * H, 0.0, -0.009 * H),   # full hip & glute curve
        (0.544 * H, hip_x * 0.95, 0.061 * H, 0.0, -0.005 * H),   # upper hip
        (0.562 * H, hip_x * 0.88, 0.057 * H, 0.0, -0.003 * H),   # shorts top
    ]
    parts.append(
        (
            "ShortsPelvis",
            "shorts",
            _loft_vertical_profile(pelvis_stations, n_rings=rings(6, 4), radial=rad_torso, superellipse_n=2.3),
        )
    )

    if not compact_lowpoly:
        waistband = _loft_vertical_profile(
            [
                (0.553 * H, hip_x * 0.90, 0.058 * H, 0.0, -0.003 * H),
                (0.562 * H, hip_x * 0.91, 0.059 * H, 0.0, -0.003 * H),
                (0.570 * H, hip_x * 0.88, 0.057 * H, 0.0, -0.003 * H),
            ],
            n_rings=3,
            radial=rad_torso,
            superellipse_n=2.3,
        )
        parts.append(("ShortsWaistband", "outfit_trim", waistband))

    # ------------------------------------------------------------------
    # 7 & 8. SYMMETRICAL HORIZONTAL T-POSE ARMS (+X AND -X) & HANDS
    # ------------------------------------------------------------------
    arm_y = 0.792 * H
    arm_z = -0.004 * H
    arm_thick = (1.0 + 0.14 * athletic)
    sh_start_x = 0.092 * H * shoulder_scale
    elbow_x = sh_start_x + 0.162 * H
    wrist_x = elbow_x + 0.148 * H

    for side in (-1.0, 1.0):
        side_tag = "L" if side > 0 else "R"

        # Upper arm (deltoid cap -> bicep/tricep -> elbow)
        upper_arm_stations = [
            (sh_start_x - 0.010 * H, 0.036 * H, 0.035 * H, arm_y - 0.004 * H, arm_z),
            (sh_start_x + 0.020 * H, 0.041 * H * arm_thick, 0.039 * H * arm_thick, arm_y + 0.003 * H, arm_z),
            (sh_start_x + 0.082 * H, 0.031 * H * arm_thick, 0.030 * H * arm_thick, arm_y, arm_z),
            (elbow_x - 0.015 * H, 0.025 * H, 0.026 * H, arm_y - 0.001 * H, arm_z),
            (elbow_x + 0.006 * H, 0.024 * H, 0.025 * H, arm_y - 0.001 * H, arm_z + 0.002 * H),
        ]
        parts.append(
            (
                f"UpperArm_{side_tag}",
                "skin",
                _loft_horizontal_arm(upper_arm_stations, side=side, n_rings=rings(6, 4), radial=rad_limb),
            )
        )

        # Lower arm / forearm (elbow -> forearm belly -> slender wrist)
        forearm_stations = [
            (elbow_x - 0.004 * H, 0.024 * H, 0.025 * H, arm_y - 0.001 * H, arm_z + 0.002 * H),
            (elbow_x + 0.036 * H, 0.027 * H * arm_thick, 0.026 * H * arm_thick, arm_y, arm_z + 0.003 * H),
            (elbow_x + 0.098 * H, 0.021 * H, 0.022 * H, arm_y - 0.001 * H, arm_z + 0.003 * H),
            (wrist_x, 0.016 * H, 0.020 * H, arm_y - 0.002 * H, arm_z + 0.004 * H),
        ]
        parts.append(
            (
                f"LowerArm_{side_tag}",
                "skin",
                _loft_horizontal_arm(forearm_stations, side=side, n_rings=rings(6, 4), radial=rad_limb),
            )
        )

        # Sporty wristband
        if not compact_lowpoly:
            wb_stations = [
                (wrist_x - 0.026 * H, 0.020 * H, 0.023 * H, arm_y - 0.002 * H, arm_z + 0.004 * H),
                (wrist_x - 0.013 * H, 0.021 * H, 0.024 * H, arm_y - 0.002 * H, arm_z + 0.004 * H),
                (wrist_x - 0.001 * H, 0.019 * H, 0.022 * H, arm_y - 0.002 * H, arm_z + 0.004 * H),
            ]
            parts.append(
                (
                    f"Wristband_{side_tag}",
                    "outfit",
                    _loft_horizontal_arm(wb_stations, side=side, n_rings=3, radial=rad_limb),
                )
            )

        # Hand: Palm (horizontal, palm down -Y, thumb forward +Z) + Thumb + Fingers
        palm_end_x = wrist_x + 0.044 * H
        palm_stations = [
            (wrist_x - 0.002 * H, 0.014 * H, 0.020 * H, arm_y - 0.002 * H, arm_z + 0.004 * H),
            (wrist_x + 0.022 * H, 0.013 * H, 0.026 * H, arm_y - 0.003 * H, arm_z + 0.006 * H),
            (palm_end_x, 0.011 * H, 0.024 * H, arm_y - 0.004 * H, arm_z + 0.005 * H),
        ]
        parts.append(
            (
                f"Hand_{side_tag}",
                "skin",
                _loft_horizontal_arm(palm_stations, side=side, n_rings=rings(4, 3), radial=max(6, rad_small)),
            )
        )

        # Forward-angled thumb (+Z)
        thumb_p0 = (side * (wrist_x + 0.016 * H), arm_y - 0.005 * H, arm_z + 0.024 * H)
        thumb_p1 = (side * (wrist_x + 0.040 * H), arm_y - 0.009 * H, arm_z + 0.046 * H)
        parts.append(
            (
                f"Hand_{side_tag}",
                "skin",
                _oriented_capsule(thumb_p0, thumb_p1, 0.0072 * H, 0.0052 * H, max(5, rad_small)),
            )
        )

        if articulated_fingers:
            finger_specs = [
                (0.017 * H, 0.038 * H, 0.0056 * H),   # index
                (0.006 * H, 0.043 * H, 0.0058 * H),   # middle
                (-0.005 * H, 0.039 * H, 0.0055 * H),  # ring
                (-0.015 * H, 0.031 * H, 0.0048 * H),  # pinky
            ]
            for fz_off, flen, frad in finger_specs:
                fp0 = (side * (palm_end_x - 0.003 * H), arm_y - 0.004 * H, arm_z + 0.005 * H + fz_off)
                fp1 = (side * (palm_end_x + flen), arm_y - 0.006 * H, arm_z + 0.005 * H + fz_off)
                parts.append(
                    (
                        f"Hand_{side_tag}",
                        "skin",
                        _oriented_capsule(fp0, fp1, frad, frad * 0.72, max(4, rad_small)),
                    )
                )
        else:
            # Clean low-poly finger mitt when target_faces < 750
            mitt_stations = [
                (palm_end_x - 0.002 * H, 0.010 * H, 0.022 * H, arm_y - 0.004 * H, arm_z + 0.005 * H),
                (palm_end_x + 0.024 * H, 0.008 * H, 0.020 * H, arm_y - 0.005 * H, arm_z + 0.005 * H),
                (palm_end_x + 0.040 * H, 0.005 * H, 0.014 * H, arm_y - 0.006 * H, arm_z + 0.005 * H),
            ]
            parts.append(
                (f"Hand_{side_tag}", "skin", _loft_horizontal_arm(mitt_stations, side=side, n_rings=3, radial=6))
            )

    # ------------------------------------------------------------------
    # 9, 10 & 11. SYMMETRICAL SHORT CUFFS, THIGHS, CALVES & SNEAKERS
    # ------------------------------------------------------------------
    leg_hip_x = 0.055 * H * hip_scale
    leg_knee_x = 0.053 * H * hip_scale
    leg_ankle_x = 0.054 * H * hip_scale
    thigh_scale = 1.0 + 0.12 * athletic

    for side in (-1.0, 1.0):
        side_tag = "L" if side > 0 else "R"
        hx = side * leg_hip_x
        kx = side * leg_knee_x
        ax = side * leg_ankle_x

        # Fitted athletic short leg cuffs
        short_cuff_stations = [
            (0.418 * H, 0.050 * H * thigh_scale, 0.053 * H * thigh_scale, hx * 0.99, 0.001 * H),
            (0.452 * H, 0.054 * H * thigh_scale, 0.058 * H * thigh_scale, hx, -0.003 * H),
            (0.492 * H, 0.056 * H * thigh_scale, 0.062 * H * thigh_scale, hx * 0.96, -0.006 * H),
        ]
        parts.append(
            (
                f"ShortsLeg_{side_tag}",
                "shorts",
                _loft_vertical_profile(short_cuff_stations, n_rings=rings(4, 3), radial=rad_limb),
            )
        )

        # Contoured anatomical thigh (upper quad/hamstring -> knee)
        thigh_stations = [
            (0.268 * H, 0.036 * H, 0.039 * H, kx, 0.004 * H),                                    # knee joint
            (0.305 * H, 0.041 * H * thigh_scale, 0.044 * H * thigh_scale, kx * 0.99, 0.004 * H), # distal quad
            (0.365 * H, 0.048 * H * thigh_scale, 0.052 * H * thigh_scale, hx, 0.002 * H),        # mid thigh
            (0.422 * H, 0.049 * H * thigh_scale, 0.052 * H * thigh_scale, hx * 0.99, 0.001 * H), # under short cuff
        ]
        parts.append(
            (
                f"Thigh_{side_tag}",
                "skin",
                _loft_vertical_profile(thigh_stations, n_rings=rings(6, 4), radial=rad_limb),
            )
        )

        # Sculpted calf (ankle -> Achilles taper -> gastrocnemius belly -> knee)
        calf_stations = [
            (0.098 * H, 0.025 * H, 0.028 * H, ax, -0.004 * H),                                   # upper ankle
            (0.145 * H, 0.030 * H, 0.033 * H, ax, -0.006 * H),                                   # mid shin
            (0.205 * H, 0.037 * H * thigh_scale, 0.041 * H * thigh_scale, kx, -0.008 * H),       # calf muscle belly
            (0.252 * H, 0.035 * H, 0.038 * H, kx, 0.001 * H),                                    # sub-knee
            (0.274 * H, 0.036 * H, 0.039 * H, kx, 0.005 * H),                                    # patella cap
        ]
        parts.append(
            (
                f"Calf_{side_tag}",
                "skin",
                _loft_vertical_profile(calf_stations, n_rings=rings(7, 4), radial=rad_limb),
            )
        )

        # Athletic crew sock cuff above sneaker
        if not compact_lowpoly:
            sock_stations = [
                (0.062 * H, 0.028 * H, 0.032 * H, ax, -0.002 * H),
                (0.084 * H, 0.027 * H, 0.030 * H, ax, -0.003 * H),
                (0.104 * H, 0.026 * H, 0.029 * H, ax, -0.004 * H),
            ]
            parts.append(
                (
                    f"Sock_{side_tag}",
                    "outfit_trim",
                    _loft_vertical_profile(sock_stations, n_rings=3, radial=rad_limb),
                )
            )

        # Grounded stylized sneaker / foot (planted cleanly at Y = 0.0)
        sole_stations = [
            (0.000 * H, 0.033 * H, 0.072 * H, ax, 0.028 * H),
            (0.011 * H, 0.035 * H, 0.075 * H, ax, 0.028 * H),
            (0.020 * H, 0.033 * H, 0.072 * H, ax, 0.026 * H),
        ]
        parts.append(
            (
                f"ShoeSole_{side_tag}",
                "sole",
                _loft_vertical_profile(sole_stations, n_rings=3, radial=max(6, rad_limb), superellipse_n=2.6),
            )
        )

        shoe_upper_stations = [
            (0.018 * H, 0.032 * H, 0.070 * H, ax, 0.026 * H),
            (0.038 * H, 0.030 * H, 0.058 * H, ax, 0.016 * H),
            (0.056 * H, 0.028 * H, 0.038 * H, ax, 0.001 * H),
            (0.068 * H, 0.026 * H, 0.031 * H, ax, -0.002 * H),
        ]
        parts.append(
            (
                f"ShoeUpper_{side_tag}",
                "outfit",
                _loft_vertical_profile(
                    shoe_upper_stations, n_rings=rings(4, 3), radial=max(6, rad_limb), superellipse_n=2.4
                ),
            )
        )

    return parts
