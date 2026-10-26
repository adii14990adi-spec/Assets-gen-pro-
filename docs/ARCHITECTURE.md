# System Architecture & Godot 4 Pipeline Guide

## 1. End-to-End Web-to-Blender Pipeline

```text
[React + Three.js Studio]
       │  POST /api/generate (strictly validated JSON, no shell/script input)
       ▼
[FastAPI Web Process (.venv — NO bpy imported)]
       │  Validates category, preset, bounds, & enqueues JobRecord in SQLite (WAL)
       ▼
[Async Background JobManager] ──(SSE / WebSocket live stage events)──► [Browser UI]
       │  Spawns isolated process group with CPU & wall-clock bounds
       ▼
[Blender 4.2.23 LTS Python Runtime (`backend/blender/runner.py`)]
   1. Factory reset (`read_factory_settings(use_empty=True)`)
   2. Selective capability activation (`activate_capabilities_for_category`)
   3. Deterministic geometry synthesis (`bpy` + `bmesh` + `numpy` + Geometry Nodes)
   4. Procedural PBR Principled BSDF materials + packed NumPy albedo textures + box UVs
   5. Scene topology, transform, UV, & normalized skin-weight inspection
   6. glTF 2.0 binary `.glb` export (+ optional compressed `.blend` project)
   7. Fresh-scene `.glb` roundtrip re-import verification inside Blender
       │
       ▼
[Independent Post-Export Validator (`backend/validation/validator.py`)]
   - Binary glTF 2.0 header (`0x46546C67`), version 2, & chunk-length verification
   - Independent `trimesh` scene load, face-index bounds, zero-area triangle & winding checks
   - Atomic promotion into `storage_data/assets/{asset_id}/` ONLY after verification succeeds
       │
       ▼
[React Three Fiber Viewport (`Viewport3D.tsx`)]
   - Fetches real `.glb` binary, checks glTF magic header, creates revocable Object URL
   - Renders with `GLTFLoader` + `RoomEnvironment` PBR + Material / Solid / Wireframe / Skeleton modes
```

## 2. Capability Registry & Extension Isolation

Every modeling extension and mesh-processing library sits behind an explicit adapter in `backend/integrations/`:

- **Blender Core (`blender_core`)** & **glTF 2.0 (`gltf2_exporter`)** — GPL-3.0 / Apache-2.0 — Required core engine.
- **Blender Geometry Nodes (`geometry_nodes`)** — GPL-3.0 — Used selectively for `architecture` (Kangura parapet arrays) and `environment` (Poisson boulder scattering).
- **Native Boolean (`native_boolean`)** & **Bool Tool (`bool_tool`)** — GPL-3.0 / GPL-2.0 — Used selectively for `architecture` (interior room hollowing, cusped arches, sally-ports) and `props` (barrier drainage cutouts).
- **Rigify (`rigify`)** — GPL-2.0 — Enabled selectively for `humanoid` rigging workflows alongside our Godot 4 `SkeletonProfileHumanoid` bone & analytical capsule-weight builder.
- **LoopTools (`looptools`)** — GPL-2.0 — Enabled selectively for `humanoid` and `props` loop operations, with analytical BMesh fallback.
- **MPFB2 / MakeHuman (`mpfb`)** — GPL-3.0 — Dynamically probed; when external MakeHuman asset packs are absent, the studio honestly reports `mpfb` as unavailable and uses the built-in **connected single-shell anatomical BMesh + Skin + Harmonic Sculpt humanoid generator**.
- **Trimesh (`trimesh`)**, **PyMeshLab (`pymeshlab`)**, and **Open3D (`open3d`)** — Probed in the backend runtime for independent post-export geometry verification.

## 3. Godot 4 Android Battle Royale Integration Notes

1. **Coordinate System & Units**: All assets are modeled in metric units (`1.0 = 1 meter`), grounded cleanly at `Z = 0` in Blender, and exported with `export_yup=True` so Godot 4 imports them upright (`+Y` up) at exact 1:1 world scale.
2. **Mobile Renderer (`Mobile` / `gl_compatibility`)**: Materials use standard glTF 2.0 `pbrMetallicRoughness` factors plus lightweight `128×128` embedded PNG grain textures—zero custom Blender node shaders that fail glTF export.
3. **Humanoid Retargeting**: Rigged characters use standard `Root -> Hips -> Spine -> Chest -> UpperChest -> Neck -> Head`, `Left/RightShoulder -> UpperArm -> LowerArm -> Hand -> 5 Fingers`, and `Left/RightUpperLeg -> LowerLeg -> Foot` hierarchy with strictly `<= 4` normalized bone influences per vertex (`JOINTS_0` / `WEIGHTS_0`). In Godot 4's Advanced Import dialog, assign a `SkeletonProfileHumanoid` resource for immediate animation retargeting.
4. **Mid-Poly Preservation**: Articulated characters are **never** passed through destructive mesh decimation; polygon counts are controlled cleanly via subdivision levels (`Prototype`, `Optimized Mid-Poly`, `Detailed Mid-Poly`) and equipment toggles so joint deformation loops remain intact.
