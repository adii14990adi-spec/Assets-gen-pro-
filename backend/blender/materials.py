"""glTF 2.0-ready PBR material & procedural packed-texture builders for Blender 4.2 LTS.

Generates deterministic NumPy-synthesized albedo grain textures (sandstone masonry,
Makrana marble veins, cordura tactical weave, brushed steel, bark/foliage, skin tone)
and connects them into Principled BSDF materials so exported GLBs carry genuine PBR
materials and embedded mobile-friendly textures for Godot 4 Android.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Theme palettes: each defines primary, secondary, accent, trim, and organic/skin slots
THEME_PALETTES: dict[str, dict[str, tuple[tuple[float, float, float], float, float, str]]] = {
    "rajasthan_sandstone": {
        "primary": ((0.76, 0.44, 0.35), 0.0, 0.78, "masonry"),
        "secondary": ((0.89, 0.78, 0.66), 0.0, 0.68, "sandstone"),
        "accent": ((0.94, 0.92, 0.88), 0.02, 0.42, "marble"),
        "trim": ((0.29, 0.19, 0.12), 0.05, 0.65, "wood"),
        "metal": ((0.26, 0.23, 0.20), 0.82, 0.42, "metal"),
    },
    "makrana_marble": {
        "primary": ((0.93, 0.91, 0.88), 0.02, 0.34, "marble"),
        "secondary": ((0.82, 0.52, 0.42), 0.0, 0.72, "sandstone"),
        "accent": ((0.83, 0.67, 0.26), 0.88, 0.28, "metal"),
        "trim": ((0.35, 0.23, 0.15), 0.04, 0.62, "wood"),
        "metal": ((0.78, 0.62, 0.24), 0.90, 0.25, "metal"),
    },
    "tactical_military": {
        "primary": ((0.24, 0.29, 0.21), 0.04, 0.74, "fabric"),
        "secondary": ((0.17, 0.18, 0.20), 0.78, 0.38, "metal"),
        "accent": ((0.84, 0.56, 0.14), 0.15, 0.48, "stripe"),
        "trim": ((0.13, 0.13, 0.14), 0.12, 0.82, "rubber"),
        "metal": ((0.32, 0.34, 0.36), 0.88, 0.34, "metal"),
    },
    "desert_camo": {
        "primary": ((0.71, 0.61, 0.45), 0.03, 0.76, "fabric"),
        "secondary": ((0.36, 0.31, 0.25), 0.55, 0.48, "metal"),
        "accent": ((0.76, 0.31, 0.16), 0.12, 0.52, "stripe"),
        "trim": ((0.16, 0.15, 0.14), 0.08, 0.85, "rubber"),
        "metal": ((0.40, 0.38, 0.35), 0.85, 0.38, "metal"),
    },
    "aravalli_biome": {
        "primary": ((0.34, 0.45, 0.23), 0.0, 0.86, "foliage"),
        "secondary": ((0.52, 0.44, 0.36), 0.0, 0.88, "rock"),
        "accent": ((0.76, 0.67, 0.50), 0.0, 0.82, "sandstone"),
        "trim": ((0.33, 0.24, 0.16), 0.0, 0.84, "wood"),
        "water": ((0.14, 0.39, 0.48), 0.08, 0.16, "smooth"),
    },
    "cyber_arena": {
        "primary": ((0.16, 0.18, 0.23), 0.65, 0.35, "metal"),
        "secondary": ((0.11, 0.12, 0.15), 0.40, 0.50, "fabric"),
        "accent": ((0.16, 0.54, 0.92), 0.35, 0.28, "stripe"),
        "trim": ((0.09, 0.09, 0.11), 0.20, 0.75, "rubber"),
        "metal": ((0.58, 0.62, 0.68), 0.92, 0.24, "metal"),
    },
}


def _synthesize_procedural_image(
    name: str,
    base_rgb: tuple[float, float, float],
    pattern: str,
    seed: int,
    size: int = 128,
) -> Any:
    """Create a deterministic packed Blender Image datablock using NumPy."""
    import bpy  # type: ignore[import-not-found]

    existing = bpy.data.images.get(name)
    if existing is not None:
        return existing

    rng = np.random.default_rng(seed)
    yy, xx = np.meshgrid(np.linspace(0.0, 1.0, size, endpoint=False), np.linspace(0.0, 1.0, size, endpoint=False), indexing="ij")
    noise_fine = rng.normal(0.0, 0.035, size=(size, size))

    if pattern == "masonry":
        # Ashlar sandstone courses with subtle mortar lines
        row_h = size // 8
        col_w = size // 4
        row_idx = (np.arange(size)[:, None] // max(1, row_h))
        x_shifted = (np.arange(size)[None, :] + (row_idx % 2) * (col_w // 2)) % size
        mortar_y = (np.arange(size)[:, None] % max(1, row_h)) < 2
        mortar_x = (x_shifted % max(1, col_w)) < 2
        mortar = np.logical_or(mortar_y, mortar_x).astype(np.float32)
        block_var = np.sin(row_idx * 1.9) * 0.03
        mod = 1.0 + noise_fine + block_var - mortar * 0.16
    elif pattern == "marble":
        veins = np.sin((xx * 5.0 + yy * 3.0) * np.pi + 0.6 * np.sin(yy * 9.0 * np.pi))
        vein_mask = np.clip(1.0 - np.abs(veins) * 3.5, 0.0, 1.0)
        mod = 1.0 + noise_fine * 0.4 - vein_mask * 0.12
    elif pattern == "fabric":
        weave = 0.03 * (np.sin(xx * size * np.pi) * np.cos(yy * size * np.pi))
        mod = 1.0 + weave + noise_fine * 0.6
    elif pattern == "metal":
        brushed = 0.04 * np.sin(yy * size * 0.7) + rng.normal(0.0, 0.02, size=(size, size))
        mod = 1.0 + brushed
    elif pattern == "wood":
        grain = 0.07 * np.sin((yy * 14.0 + 0.15 * np.sin(xx * 6.0)) * np.pi)
        mod = 1.0 + grain + noise_fine * 0.5
    elif pattern == "stripe":
        diag = ((xx + yy) * 8.0) % 1.0
        band = (diag < 0.22).astype(np.float32)
        mod = 1.0 - band * 0.18 + noise_fine * 0.4
    elif pattern in ("rock", "sandstone"):
        strata = 0.06 * np.sin(yy * 18.0 + 0.4 * np.cos(xx * 10.0))
        mod = 1.0 + strata + noise_fine * 1.2
    else:
        mod = 1.0 + noise_fine * 0.7

    rgba = np.ones((size, size, 4), dtype=np.float32)
    rgba[..., 0] = np.clip(base_rgb[0] * mod, 0.02, 0.99)
    rgba[..., 1] = np.clip(base_rgb[1] * mod, 0.02, 0.99)
    rgba[..., 2] = np.clip(base_rgb[2] * mod, 0.02, 0.99)

    img = bpy.data.images.new(name=name, width=size, height=size, alpha=False)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def get_or_create_pbr_material(
    name: str,
    base_rgb: tuple[float, float, float],
    metallic: float = 0.0,
    roughness: float = 0.65,
    pattern: str = "smooth",
    seed: int = 42,
    use_texture: bool = True,
    alpha: float = 1.0,
) -> Any:
    """Build or return a glTF-compatible Principled BSDF material."""
    import bpy  # type: ignore[import-not-found]

    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (320, 0)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = (base_rgb[0], base_rgb[1], base_rgb[2], 1.0)
    bsdf.inputs["Metallic"].default_value = float(np.clip(metallic, 0.0, 1.0))
    bsdf.inputs["Roughness"].default_value = float(np.clip(roughness, 0.04, 1.0))
    if "Alpha" in bsdf.inputs and alpha < 0.999:
        bsdf.inputs["Alpha"].default_value = float(alpha)
        mat.blend_method = "BLEND"

    if use_texture and pattern != "smooth":
        tex_img = _synthesize_procedural_image(
            name=f"{name}_AlbedoTex",
            base_rgb=base_rgb,
            pattern=pattern,
            seed=seed,
        )
        tex_node = nodes.new(type="ShaderNodeTexImage")
        tex_node.location = (-320, 0)
        tex_node.image = tex_img
        links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    return mat


def resolve_theme_materials(theme_name: str, default_theme: str, seed: int, wear_amount: float = 0.3) -> dict[str, Any]:
    """Return a dictionary of ready-to-assign Blender materials for the selected theme."""
    chosen = theme_name if theme_name in THEME_PALETTES else default_theme
    palette = THEME_PALETTES.get(chosen, THEME_PALETTES["rajasthan_sandstone"])
    mats: dict[str, Any] = {}
    wear_delta = (wear_amount - 0.35) * 0.18
    for idx, (slot, (rgb, metallic, rough, pattern)) in enumerate(palette.items()):
        adj_rough = float(np.clip(rough + wear_delta, 0.08, 0.98))
        mats[slot] = get_or_create_pbr_material(
            name=f"Mat_{chosen}_{slot}",
            base_rgb=rgb,
            metallic=metallic,
            roughness=adj_rough,
            pattern=pattern,
            seed=seed + idx * 31,
            use_texture=(slot in ("primary", "secondary")),
        )
    return mats


def ensure_smart_uv_project(obj: Any) -> None:
    """Ensure a mesh object has at least one clean non-overlapping UV map for glTF export."""
    import bmesh  # type: ignore[import-not-found]

    if obj.type != "MESH" or obj.data is None or len(obj.data.polygons) == 0:
        return

    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")

    # Fast deterministic triplanar/cubic box UV projection directly in BMesh (no UI context needed!)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.verify()

    verts_co = np.array([v.co[:] for v in bm.verts], dtype=np.float32)
    span = np.maximum(verts_co.max(axis=0) - verts_co.min(axis=0), 1e-3)
    scale = 1.0 / float(np.max(span))
    mins = verts_co.min(axis=0)

    for face in bm.faces:
        nx, ny, nz = abs(face.normal.x), abs(face.normal.y), abs(face.normal.z)
        for loop in face.loops:
            co = loop.vert.co
            if nz >= nx and nz >= ny:
                u = (co.x - mins[0]) * scale
                v = (co.y - mins[1]) * scale
            elif nx >= ny:
                u = (co.y - mins[1]) * scale
                v = (co.z - mins[2]) * scale
            else:
                u = (co.x - mins[0]) * scale
                v = (co.z - mins[2]) * scale
            loop[uv_layer].uv = (float(u), float(v))

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
