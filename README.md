# Assets Gen Pro

Deterministic, seed-based **SVG asset generation** — a small FastAPI backend
plus a zero-build static front end.

Give it a kind, a seed and a palette, and it returns an SVG. The same inputs
always produce byte-identical output, so generated assets can be cached
forever and referenced by URL.

```
GET /api/asset.svg?kind=mesh&seed=aurora&palette=neon&size=512
```

## Features

- **Five asset kinds** — mesh gradients, geometric patterns, identicons,
  shield badges and image placeholders.
- **Deterministic** — output is a pure function of `(kind, seed, palette,
  params)`; no global RNG state, no timestamps.
- **Five palettes** — `vivid`, `pastel`, `neon`, `mono`, `earth`, all
  generated from the seed itself.
- **Cache-friendly** — strong `ETag` plus `immutable` caching, with `304`
  revalidation.
- **No build step** — the UI is plain HTML/CSS/JS served by the same app.
- **No binary dependencies** — assets are emitted as hand-built SVG markup.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000> for the UI and
<http://localhost:8000/docs> for the generated API reference.

Run the test suite with:

```bash
pytest
```

## Asset kinds

| Kind          | What it draws                                        | Options                                     |
| ------------- | ---------------------------------------------------- | ------------------------------------------- |
| `mesh`        | Aurora-like blurred blobs over a deep background      | `blobs` 3–10, `grain`                       |
| `pattern`     | Tiled geometric motifs                                | `motif` (`auto`, `dots`, `triangles`, `hexagons`, `waves`, `stripes`), `density` 3–10 |
| `identicon`   | Symmetrical block avatar                              | `grid` (`5`, `7`), `mask` (`circle`, `squircle`) |
| `badge`       | Gradient shield with initials                         | `text` (≤4 chars), `sparkles`               |
| `placeholder` | Framed empty-state graphic with a caption             | `caption` (≤16 chars), `icon` (`mountain`, `camera`, `layers`), `dots`, `corners` |

## API

### `GET /api/asset.svg`

| Query param | Default | Notes                                            |
| ----------- | ------- | ------------------------------------------------ |
| `kind`      | —       | required; one of the kinds above                 |
| `seed`      | `demo`  | any string                                       |
| `size`      | `400`   | 16–2048, square                                  |
| `palette`   | `vivid` | `vivid`, `pastel`, `neon`, `mono`, `earth`       |
| *others*    | —       | forwarded to the kind's own options              |

```bash
curl -s "http://localhost:8000/api/asset.svg?kind=badge&seed=launch&palette=neon&text=AB" \
  -o badge.svg
```

### `POST /api/asset.svg`

Same rendering, JSON body — convenient for long parameter sets.

```json
{
  "kind": "pattern",
  "seed": "grid",
  "size": 800,
  "palette": "earth",
  "params": { "motif": "hexagons", "density": 7 }
}
```

### Other endpoints

| Endpoint               | Purpose                                        |
| ---------------------- | ---------------------------------------------- |
| `GET /api/kinds`       | Kind catalogue with parameter metadata (drives the UI) |
| `GET /api/palettes`    | Listed inside `/api/health`                     |
| `GET /api/seed`        | Fresh random seed                               |
| `GET /api/batch.json`  | `count` seeds derived from one seed, with URLs  |
| `GET /api/health`      | Status and version                              |

Errors return a JSON `detail` string: `422` for invalid parameters, `404` for
an unknown kind.

## Project layout

```
app.py                    FastAPI application and routes
assets_gen/
  rng.py                  SHA-256 seeded PRNG helpers
  palettes.py             HSL palette construction per style
  params.py               Query/JSON parameter coercion and validation
  svg.py                  SVG document assembly helpers
  generators/
    base.py               Context / ParamSpec types
    mesh.py               soft blurred blobs
    pattern.py            tiled motifs
    identicon.py          symmetrical avatars
    badge.py              shield badges
    placeholder.py        framed placeholders
web/                      static UI (no build step)
tests/                    pytest suite
```

## Determinism

`assets_gen.rng.make_rng(*parts)` hashes its inputs and seeds a local
`random.Random`, so generators never touch global state and the palette is
derived from the same stream as the artwork. Rendering the same URL twice
returns identical bytes — the test suite asserts this for every kind.

## Embedding

```html
<img src="/api/asset.svg?kind=identicon&seed=user-42&palette=pastel"
     alt="Avatar" width="400" height="400" />
```

For raster output, use the **PNG** button in the UI (renders the SVG to a
canvas at the selected size).
