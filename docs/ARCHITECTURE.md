# Architecture — Code-Only Generation, Static Delivery

## 1. Design goals

| Goal | Consequence in this repository |
| --- | --- |
| Every 3D model is created by Python code | `scripts/generators/` (NumPy + SciPy + Trimesh). No sculpting, no downloaded assets, no runtime modelling in the browser. |
| Zero server runtime | No FastAPI/uvicorn/`app.py`, no `backend/`, no `render.yaml`, no Docker image. The deployable artifact is a folder of static files. |
| Deterministic, reviewable assets | Seeded RNG, deterministic exporter byte layout, measured metadata, byte-equality tests. |
| Instant page load | Static HTML + CDN Three.js + small cached `.glb` files (~8.5 MB total for 18 models, 76 KB–1.8 MB each). |
| Deploy that can never fail on Pages misconfiguration | `peaceiris/actions-gh-pages@v4` branch push; no `actions/configure-pages`/`deploy-pages`. |

## 2. Layers

```
┌──────────────────────────── Python build time (GitHub Actions) ────────────────────────────┐
│ presets/*.json ──► generators/specs.py ──► AssetSpec(id, category, seed, budget, params)   │
│                                                        │                                    │
│                                    generators/pipeline.py · generate_asset(config)         │
│                                                        │                                    │
│        ┌───────────────────────────┬───────────────────┴────────────┬────────────────────┐  │
│        │ humanoid.build_humanoid   │ architecture.build_architecture│ terrain.build_       │  │
│        │ → character_tpose.py      │                                │ environment          │  │
│        │                           │ props.build_prop               │                      │  │
│        └───────────────────────────┴────────────────────────────────┴────────────────────┘  │
│                                                        │                                    │
│      meshkit.SceneBuilder (material-slot groups) → enforce_budget → facet/smooth baking      │
│                                                        │                                    │
│      glb_writer.build_glb_stream  →  bytes  →  diagnostics.measure_diagnostics (re-import)  │
│                                                        │                                    │
│      pipeline.validate_glb_bytes (header, chunks, accessors, index bounds, parity)           │
│                                                        │                                    │
│      build_all_assets.py  →  public/assets/models/<id>.glb + public/assets/manifest.json    │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                          │  git push (gh-pages)
┌──────────────────────────── Browser (GitHub Pages, static) ─────────────────────────────────┐
│ public/index.html → fetch ./assets/manifest.json → GLTFLoader(./assets/models/<id>.glb)      │
│ Three.js scene: 3-point lights, grid, shadow catcher · OrbitControls · inspector toolbar      │
│ HUD reads manifest metadata (measured at build time) + live geometry counts from the scene     │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Module responsibilities

| Module | Responsibility |
| --- | --- |
| `generators/specs.py` | Reads `presets/*.json`, validates categories, attaches the producing script, seed and (for the hero) the face-band budget ladder. |
| `generators/pipeline.py` | `generate_asset()` orchestration: RNG seeding, material resolution, builder dispatch, budget enforcement, shading, export, measured diagnostics. Also `validate_glb_bytes()` — an independent structural validator/gate. |
| `generators/meshkit.py` | Watertight primitives (box, cylinder-Y, cone-Y, icosphere, torus, tube, displaced rock), `SceneBuilder` material grouping, deterministic vertex-cluster decimation (component-aware), triplanar UVs, flat-facet and smooth normal baking, `mesh_to_glb_part`. |
| `generators/glb_writer.py` | Deterministic glTF 2.0 binary writer: 4-byte aligned buffer views, `POSITION` min/max, `COLOR_0` (linear space), `TEXCOORD_0`, named `pbrMetallicRoughness` materials. |
| `generators/palette.py` | Material themes (Rajasthan sandstone, Makrana marble, tactical military, desert camo, Aravalli biome, cyber arena) and character palettes driven by `skin_color`/`outfit_color`. |
| `generators/diagnostics.py` | Measured topology: triangles, vertices, degenerate faces, non-manifold edges, component counts, bounding box, material summaries, and the GLB re-import check. |
| `generators/character_tpose.py` | Hero faceted mid-poly female T-pose character from cubic-spline loft profiles. |
| `generators/humanoid.py` | A-pose male/female combatant archetypes (armour, backpack, boots, hands). |
| `generators/architecture.py` | Cusped arches, walls with portals, Jharokha balconies, Chhajja eaves, lotus domes, Kangura battlements, chhatri pavilions, arch bridges. |
| `generators/terrain.py` | Multi-octave fBm/ridged heightfields closed into watertight solids, strata terracing, Poisson-style boulder scatter, water planes, Banyan/Acacia trees. |
| `generators/props.py` | Chamfered crates with latches and brackets, corrugated fuel drums, cover barriers, off-road buggy. |
| `build_all_assets.py` | CLI: catalogue → generate → validate → write `.glb` (atomic per asset) → prune orphaned models → write `manifest.json` with repository/commit provenance. |

## 4. Determinism contract

1. Seed = `seed XOR crc32(preset_id)`, truncated to 31 bits — stable across platforms.
2. No wall-clock, no network, no environment-dependent geometry; `float64` math via NumPy/SciPy.
3. The exporter sorts parts, materials, and accessors and writes a fixed buffer layout.
4. `tests/test_generators.py` and `tests/test_hero_character.py` assert byte-for-byte equality across repeated runs.

## 5. Validation strategy (defence in depth)

| Stage | What is proven |
| --- | --- |
| Generator unit tests | Required body parts exist, feet at `y≈0`, parts are non-degenerate, T-pose span ≥ height. |
| `measure_diagnostics` | Real triangle/vertex counts, degenerate faces, non-manifold edge count, bounds. |
| Round-trip re-import | The exact exported bytes are re-loaded with Trimesh and triangle counts must match. |
| `validate_glb_bytes` | GLB magic/version/declared length, chunk alignment, JSON parse, buffer sizes, `POSITION` min/max presence, accessor/bufferView bounds, index range, triangle parity. |
| CI verification step | Every shipped file re-read: magic, length, manifest keys, size parity, hero face band, script path existence. |
| Browser-side reality check | `GLTFLoader` parses each model in the deployed site; the HUD counts come from the loaded scene. |

## 6. Front-end architecture

* Single HTML file, ES modules, import map → `three@0.170.0` (`three.module.js`, `GLTFLoader`, `OrbitControls`, `RoomEnvironment`).
* State object holds manifest, filters, selection, shading mode, wireframe flag, background preset.
* **Shading preview** works by swapping geometries: the exported geometry (flat, one normal per triangle) and a lazily built welded twin whose normals are recomputed with `computeVertexNormals()` — no re-export, no geometry authoring.
* **Wireframe overlay** is a `WireframeGeometry`+`LineSegments` child added on first use and toggled after.
* **Backgrounds** are a canvas gradient used as `scene.background`, with matching grid colours, fog and exposure.
* **Responsive shell**: sidebar at ≥1024 px, slide-over drawer below; the HUD collapses on phones; `ResizeObserver` keeps the renderer pixel-ratio aware.
* **Deep links**: `?model=<id>` selects a model; the share URL is rewritten with `history.replaceState`.

## 7. Removed components

| Removed | Why |
| --- | --- |
| `app.py`, `main.py`, `backend/**` | FastAPI job queue, SSE/WebSocket progress, SQLite storage, Blender runner — all unnecessary once models are pre-generated. |
| `frontend/**` (React/Vite/R3F) | Replaced by a dependency-free static page that needs no build step. |
| `render.yaml`, `Dockerfile`, `.dockerignore`, `.env.example`, `runtime.txt` | Deployment-time server infrastructure. |
| `.github/workflows/ci.yml`, `generate-asset.yml` | Folded into the single `deploy.yml` (lint + tests + generate + deploy). |
| `scripts/setup_blender_runtime.py`, `smoke_test_blender.py`, `cli_generate.py` | Blender-runtime bootstrapping and the server-oriented CLI; superseded by `build_all_assets.py`. |
