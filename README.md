# Asset Forge — Code-Only 3D Asset Pipeline + Static GitHub Pages Gallery

**Python 3.11 (NumPy · SciPy · Trimesh) generates every `.glb` → GitHub Actions exports and validates them → a static Three.js gallery on GitHub Pages displays and downloads them.**

There is **no FastAPI server, no Render service, no Docker runtime, and no cold start**. The deployed artifact is a folder of static files (`public/`) plus pre-generated binary glTF models. Opening the gallery is a CDN-cached HTML page and a `.glb` fetch — nothing else.

| What | Where |
| --- | --- |
| Python generators (pure code, no GUI, no hand modelling) | [`scripts/generators/`](scripts/generators) |
| Standalone Blender 4.0+ script: rigged athletic female character (`.blend` + skinned `.glb`) | [`scripts/generate_athletic_female_character.py`](scripts/generate_athletic_female_character.py) |
| Optional Blender add-on: clean / optimise / rig-ready any AI mesh from an N-panel | [`scripts/assetgen_mesh_optimizer.py`](scripts/assetgen_mesh_optimizer.py) |
| Build entrypoint → `.glb` + `manifest.json` | [`scripts/build_all_assets.py`](scripts/build_all_assets.py) |
| Static 3D gallery & inspector | [`public/index.html`](public/index.html) |
| Generated models + manifest | [`public/assets/models/`](public/assets/models), [`public/assets/manifest.json`](public/assets/manifest.json) |
| The only workflow: build → publish `gh-pages` | [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) |

---

## How the pipeline works

```
push to main ──► GitHub Actions (ubuntu-24.04, Python 3.11)
                   ├─ pip install --prefer-binary numpy scipy trimesh
                   ├─ ruff check scripts tests
                   ├─ pytest                       # 70 generator / gallery / workflow / add-on tests
                   ├─ python scripts/build_all_assets.py
                   │     presets/*.json  ─►  scripts/generators/*.py  ─►  in-memory mesh
                   │                          └─► flat-facet normals, triplanar UVs,
                   │                              per-face vertex colors, PBR materials
                   │     └─► public/assets/models/<id>.glb   (structurally validated)
                   │     └─► public/assets/manifest.json    (measured metadata)
                   └─ peaceiris/actions-gh-pages@v4  ──►  gh-pages branch  ──►  GitHub Pages
                                                                                  │
browser ──► index.html ──► ./assets/manifest.json ──► ./assets/models/<id>.glb ───┘
             (Three.js: GLTFLoader + OrbitControls, view-only inspector)
```

Key properties:

* **Reproducible.** Every generator is seeded from `(preset seed XOR crc32(preset id))`, so identical inputs produce byte-identical `.glb` files — verified by `tests/test_generators.py::test_generation_is_byte_for_byte_deterministic`.
* **Measured, not estimated.** `vertex_count`, `face_count`, `file_size_kb` in the manifest come from a **Trimesh re-import of the exact exported bytes**, and the CI gate re-checks the header/chunk/accessor layout of every shipped GLB.
* **Self-contained viewer.** `public/index.html` has zero build step: Tailwind via CDN, Three.js `0.170.0` via an ES-module import map, and only **relative** URLs (`./assets/manifest.json`, `./assets/models/…`) so it works at `https://<user>.github.io/<repo-name>/` without configuration.
* **View-only by design.** The gallery never creates geometry. It offers wireframe, flat/smooth preview, auto-rotate, background switching, a live geometry HUD, and a direct `.glb` download.

---

## The asset catalogue (18 models, ~8.5 MB total)

### Humanoid Characters — `scripts/generators/humanoid.py`

| Model | ID | Faces | Vertices | Size | Budget |
| --- | --- | ---: | ---: | ---: | ---: |
| Armored Squad Leader (Full Tactical Loadout) | `armored_squad_leader` | 15,156 | 45,468 | 1,791 KB | 34,000 |
| Athletic Female Recon Scout | `athletic_female_scout` | 13,280 | 39,840 | 1,570 KB | 28,000 |
| Athletic Male Battle Royale Combatant | `athletic_male_combatant` | 12,884 | 38,652 | 1,521 KB | 28,000 |
| Mid-Poly Stylized Female T-Pose Character | `midpoly_character` | 1,424 | 4,272 | 200 KB | 1,000 |

### Rajasthani & Modular Architecture — `scripts/generators/architecture.py`

| Model | ID | Faces | Vertices | Size | Budget |
| --- | --- | ---: | ---: | ---: | ---: |
| Fortified Pol Arched Gateway | `pol_arched_gateway` | 1,884 | 5,652 | 232 KB | 5,000 |
| Masonry Multi-Arch Canyon Bridge | `stone_arch_bridge` | 1,792 | 5,376 | 220 KB | 3,800 |
| Rajasthani Sandstone Haveli House | `rajasthani_haveli` | 2,516 | 7,548 | 314 KB | 5,600 |
| Rajput Hill Fort Bastion & Rampart | `rajput_fort_bastion` | 876 | 2,628 | 115 KB | 5,200 |
| Royal Octagonal Chhatri Pavilion | `chhatri_pavilion` | 2,376 | 7,128 | 292 KB | 4,800 |

### Environment & Terrain — `scripts/generators/terrain.py`

| Model | ID | Faces | Vertices | Size | Budget |
| --- | --- | ---: | ---: | ---: | ---: |
| Aravalli Ridge & Plateau Terrain | `aravalli_ridge_terrain` | 4,100 | 12,300 | 488 KB | 5,200 |
| Battle Royale Drop Island | `battle_royale_island` | 4,080 | 12,240 | 487 KB | 6,000 |
| Indian Banyan / Acacia Canopy Tree | `stylized_banyan_tree` | 2,372 | 7,116 | 285 KB | 3,400 |
| Meandering River Ravine & Ford | `river_ravine_crossing` | 3,292 | 9,876 | 392 KB | 5,400 |
| Stratified Desert Cliff & Rock Outcrop | `desert_rock_outcrop` | 2,776 | 8,328 | 331 KB | 3,200 |

### Props, Gear & Vehicles — `scripts/generators/props.py`

| Model | ID | Faces | Vertices | Size | Budget |
| --- | --- | ---: | ---: | ---: | ---: |
| Battle Royale Airdrop Supply Crate | `br_supply_crate` | 576 | 1,728 | 76 KB | 1,400 |
| Industrial Corrugated Fuel Barrel | `explosive_fuel_barrel` | 660 | 1,980 | 82 KB | 1,100 |
| Reinforced Tactical Cover Barrier | `tactical_cover_barrier` | 636 | 1,908 | 84 KB | 950 |
| Thar Desert Recon Buggy Vehicle | `desert_recon_buggy` | 1,368 | 4,104 | 172 KB | 3,800 |

Counts above are the measured values written into `public/assets/manifest.json` by the last build.

---

## The hero asset: faceted mid-poly female T-pose character

`scripts/generators/character_tpose.py` builds the character entirely from code — 1,424 faces / 4,272 vertices, flat-shaded, inside the required **1,200–1,500 face** window.

* **Anatomy from spline lofts.** `scipy.interpolate.CubicSpline` drives vertical/horizontal anatomical profiles (chin → jawline → cheekbones → cranium, ribcage → bust → clavicle, deltoid → forearm, thigh → knee → calf) which are stitched into closed, watertight multi-ring solids.
* **Crisp faceted shading.** Every triangle is unmerged into three unique vertices with a single geometric face normal, so the exported GLB renders hard polygon edges with zero smoothing overrides in the browser.
* **Athletic top & shorts vertex colors.** Per-face sRGB colors are baked into `COLOR_0` (converted to linear space per the glTF 2.0 spec): blue sports top `#3b82f6`, a darkened mix for the shorts, warm skin, hair, sole and eye palettes — all customisable via `skin_color` / `outfit_color` in the preset.
* **True horizontal T-pose.** Arms extend along ±X at shoulder height (span 1.67 m for a 1.72 m character), feet planted exactly at `y = 0`.
* **Face-band guard.** Ring density is quantised, so the build walks a polygon-budget ladder (`1000 → 950 → 1050 → …`) and stops at the first export whose measured face count falls inside 1,200–1,500. If nothing lands in band, the build **fails** rather than shipping an off-spec hero. `tests/test_hero_character.py` asserts the band, the T-pose silhouette, the part inventory, the vertex-color separation, and grounding.

---

## Local development

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # numpy, scipy, trimesh, pytest, ruff

# 1. Regenerate every .glb + the manifest (≈2 s for all 18 models)
.venv/bin/python scripts/build_all_assets.py

# 2. Preview the exact static site that GitHub Pages serves
.venv/bin/python -m http.server 8080 --directory public
#    → http://localhost:8080

# 3. Quality gates (same commands CI runs)
.venv/bin/ruff check scripts tests
.venv/bin/pytest -v
```

Useful CLI flags:

```bash
python scripts/build_all_assets.py --only midpoly_character rajasthani_haveli
python scripts/build_all_assets.py --seed 4242            # regenerate with another seed
python scripts/build_all_assets.py --output-dir dist/site  # publish elsewhere
python scripts/build_all_assets.py --no-clean              # keep orphaned .glb files
```

### Why no Blender in CI?

The generators are pure NumPy/SciPy/Trimesh code and the exporter is a hand-written, spec-correct glTF 2.0 binary writer (`scripts/generators/glb_writer.py`) that emits `POSITION`/`NORMAL`/`TEXCOORD_0`/`COLOR_0` plus named PBR materials in one deterministic layout. So:

* no `bpy` (≈300 MB wheel + GL/X11 runtime) in the workflow — the deploy job runs in about a minute;
* no quadric simplifier (`fast-simplification`): polygon budgets are enforced with a deterministic vertex-cluster decimation pass, so a laptop and CI produce identical bytes;
* swapping in Blender later only requires adding a `bpy` code path behind the same `generate_asset()` contract.

### Cleaning up an AI-generated mesh (optional Blender add-on)

Anything that enters the project from outside — a Tripo/Meshy/Rodin/GLB drop — usually needs the same
five repairs before it can be rigged, so [`scripts/assetgen_mesh_optimizer.py`](scripts/assetgen_mesh_optimizer.py)
(registered as *AssetGenPro: AI Mesh Optimizer*) ships as a Blender 4.0+ add-on with an
**AssetGenPro** sidebar tab:

| Step | Button | What runs |
| --- | --- | --- |
| 0 | Import & Setup | apply location/rotation/scale (scale becomes 1.000) and move the origin to geometry, world origin or floor |
| 1 | Clean Mesh | `bmesh.ops.remove_doubles` at a user-set distance (default `0.0001`), degenerate-face dissolve, optional coplanar-triangle dissolve, loose vert/edge removal, floating-island removal, `recalc_face_normals` plus a signed-volume check so an inside-out shell ends up outward |
| 2 | Symmetrize | `bmesh.ops.symmetrize` across X/Y/Z with a snap distance, for the half-modelled limbs AI generators produce |
| 3 | Optimize | **Mode A** Decimate (Collapse, ratio or an exact face budget, UVs/materials/weights intact) or **Mode B** Voxel Remesh (default `0.02` m) for a uniform rigging base, with an optional budget pass and UV/vertex-colour recovery from the untouched `*_AI_SRC` backup through a Data Transfer modifier |
| 4 | Auto UV Unwrap | Smart UV Project (angle limit + island margin) into a fresh atlas so the original texture can be baked onto the new topology |

Install it with *Edit → Preferences → Add-ons → Install…* (or paste it into a Text Editor and run —
`register()` is at the bottom of the file), then press `N` in the 3D Viewport. Every slider lives on the
scene, the cleanup is pure `bmesh` rather than edit-mode operators, and modifier application goes through
`temp_override`, so the whole thing also runs under `--background` and is exercised by
`tests/test_mesh_optimizer_addon.py` (the eight functional tests skip unless a real `bpy` is importable,
which is why CI stays Blender-free).

Two behaviours are deliberate: destructive passes **refuse** to weld a mesh that still has shape keys or
skin weights until you tick the matching override, and the last-untouched copy is kept hidden as
`<name>_AI_SRC` because it is both the transfer source and the thing you bake from.

---

## Static gallery features

`public/index.html` (single file, no bundler, mobile-first):

| Area | Details |
| --- | --- |
| Gallery drawer | Sidebar on desktop, slide-over drawer on mobile; searchable list of all models with category filters and per-category counts |
| Viewport | Three.js `0.170.0` ES modules, `GLTFLoader`, `OrbitControls` with damping; touch pinch/2-finger pan, wheel zoom, right-drag pan |
| Lighting | Studio 3-point rig — warm key (shadow-casting), cool fill, white rim — plus hemisphere ambience and a subtle `RoomEnvironment` PBR reflection |
| Ground | Adaptive `GridHelper` scaled to the model bounds and a soft shadow catcher |
| Inspector toolbar | Wireframe overlay toggle · Flat vs. Smooth shading preview · Auto-rotate · 4 background presets (studio / midnight / light / blueprint) · camera reset |
| Geometry HUD | Live vertex count, triangle/face count, file size, mesh & material counts, bounding-box dimensions, seed, last-update date, and a deep link to the exact generator script on GitHub |
| Download | `Download .GLB` streams the pre-generated model from `./assets/models/…` |
| Extras | Keyboard shortcuts (`W` `F` `R` `B` `G`), `?model=<id>` deep links, and reduced-motion support |

`public/.nojekyll` is committed so GitHub Pages serves the folder verbatim (no Jekyll processing).

---

## GitHub Actions deployment

`.github/workflows/deploy.yml` is the **only** workflow. It runs on `push` to `main` and on manual `workflow_dispatch`, with `permissions: contents: write`:

1. `actions/checkout@v4`
2. `actions/setup-python@v5` with Python **3.11** (pip cache keyed on the requirement files)
3. `pip install --prefer-binary numpy scipy trimesh` + `-r requirements-dev.txt`
4. `ruff check scripts tests` and `pytest`
5. `python scripts/build_all_assets.py` → writes `public/assets/models/*.glb` and `public/assets/manifest.json`
6. A verification step that re-reads every shipped `.glb` (magic, declared length, manifest key completeness, manifest ↔ file parity, hero face band)
7. `actions/upload-artifact@v4` for build provenance
8. `peaceiris/actions-gh-pages@v4` with `github_token: ${{ secrets.GITHUB_TOKEN }}` and `publish_dir: ./public` → force-pushes the static bundle to the `gh-pages` branch

> **No `actions/configure-pages`, no `actions/deploy-pages`.** Those actions require a Pages site that already exists and abort the whole run with `HttpError: Not Found - Get Pages site failed` when Pages has not been provisioned. Pushing a branch with `peaceiris/actions-gh-pages@v4` cannot fail that way.

### One-time repository setting

**Settings → Pages → Build and deployment → Source: _Deploy from a branch_ → Branch: `gh-pages` / `root` → Save.**

The first workflow run creates the `gh-pages` branch; the site is then live at
`https://<owner>.github.io/<repo-name>/`.

---

## Project layout

```
.
├── .github/workflows/deploy.yml       # single workflow: build models → gh-pages
├── presets/                           # per-asset parameters (id, name, tags, budget, seed…)
│   ├── architecture/  environment/  humanoid/  props/
├── public/                            # ← the entire deployed site
│   ├── index.html                     #   static Three.js gallery + inspector
│   ├── .nojekyll
│   └── assets/
│       ├── manifest.json              #   generated metadata for every model
│       └── models/*.glb               #   generated binary glTF 2.0 models
├── scripts/
│   ├── build_all_assets.py            # generate → validate → write .glb + manifest
│   ├── generate_athletic_female_character.py  # optional Blender path: mesh + 51-bone rig
│   ├── assetgen_mesh_optimizer.py     # optional Blender add-on: AI mesh cleanup panel
│   └── generators/
│       ├── pipeline.py                # orchestration + GLB structural validation
│       ├── specs.py                   # asset catalogue (presets → script + seed)
│       ├── meshkit.py                 # primitives, decimation, faceting, shading
│       ├── glb_writer.py              # deterministic glTF 2.0 binary writer
│       ├── palette.py                 # PBR material themes
│       ├── diagnostics.py             # measured topology + round-trip checks
│       ├── character_tpose.py         # hero mid-poly female T-pose character
│       ├── humanoid.py                # A-pose body archetypes
│       ├── architecture.py            # Rajasthani / modular architecture
│       ├── terrain.py                 # fBm terrain, water, vegetation
│       └── props.py                   # crates, barrels, barriers, buggy
├── tests/                             # 70 tests: generators, hero, manifest, site, workflow, add-on
└── docs/ARCHITECTURE.md, docs/DEPLOYMENT.md
```

---

## Requirements

| Layer | Pinned / verified |
| --- | --- |
| Python | 3.11 (`.python-version`, workflow `python-version: "3.11"`) |
| Generation | `numpy>=1.26.4,<3`, `scipy>=1.11.4,<2`, `trimesh>=4,<6` — wheels only, no compiler |
| Viewer | Three.js `0.170.0` + Tailwind CDN (no npm install, no bundler) |
| Hosting | GitHub Pages (`gh-pages` branch) — zero server runtime, zero cold start |

## License

GPL-3.0-or-later (see `pyproject.toml`).
