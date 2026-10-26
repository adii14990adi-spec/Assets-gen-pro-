# Deployment — GitHub Actions → GitHub Pages

The site is 100% static. Deployment = build the `.glb` files with Python, then publish
`public/` to the `gh-pages` branch.

---

## 1. One-time repository setup

1. **Settings → Pages → Build and deployment**
   * **Source**: *Deploy from a branch*
   * **Branch**: `gh-pages` · **Folder**: `/ (root)`
   * Save.
2. **Settings → Actions → General → Workflow permissions**: allow read/write (the workflow
   already declares `permissions: contents: write`, but the repository must not block writes).
3. Nothing else — no secrets, no environment variables, no Pages API provisioning.

> The `gh-pages` branch is created by the first successful workflow run. If Pages is configured
> before the branch exists, GitHub simply shows an empty site until the run finishes.
>
> **Why no `actions/configure-pages`?** That action queries the Pages API and aborts the job with
> `HttpError: Not Found - Get Pages site failed` when Pages has not been provisioned. Pushing a
> branch with `peaceiris/actions-gh-pages@v4` has no such failure mode, so the pipeline is green
> on the very first push.

Resulting URL: `https://<owner>.github.io/<repo-name>/`

Because every path in `public/index.html` is relative (`./assets/...`), project-page URLs work
without any `basePath`/`homepage` configuration.

---

## 2. The workflow (`.github/workflows/deploy.yml`)

| Step | Command / action | Purpose |
| --- | --- | --- |
| 1 | `actions/checkout@v4` | Full checkout of the pushed commit. |
| 2 | `actions/setup-python@v5` (`python-version: "3.11"`) | Pinned interpreter + pip cache. |
| 3 | `pip install --prefer-binary numpy scipy trimesh` and `-r requirements-dev.txt` | Generation + test dependencies, wheels only. |
| 4 | `ruff check scripts tests` | Static analysis gate. |
| 5 | `pytest -v` | 70 generator / manifest / site / workflow / add-on tests (8 add-on tests need `bpy` and skip in CI). |
| 6 | `python scripts/build_all_assets.py` | Regenerates every `.glb` and `public/assets/manifest.json`. |
| 7 | Inline Python verification | Re-reads each GLB (magic, declared length, manifest parity, hero 1,200–1,500 face band). |
| 8 | `actions/upload-artifact@v4` | Keeps the generated assets as run artifacts. |
| 9 | `peaceiris/actions-gh-pages@v4` | Force-pushes `public/` to `gh-pages` (`github_token: secrets.GITHUB_TOKEN`, `publish_dir: ./public`, `enable_jekyll: false`). |

Triggers: `push` to `main`, plus `workflow_dispatch`. Concurrency group `deploy-gh-pages` with
`cancel-in-progress: true` — the newest push always wins.

Typical duration: **1–2 minutes** (the 18 models generate in roughly 2 seconds).

---

## 3. Routine workflows

### Publish a change to a model

```bash
# edit e.g. presets/props/br_supply_crate.json or scripts/generators/props.py
python scripts/build_all_assets.py                # verify locally first
git add -A && git commit -m "feat(props): richer crate hardware" && git push origin main
```

The push triggers the workflow; the new `.glb` files and manifest are published automatically.

### Add a brand-new model

1. Create `presets/<category>/<id>.json` (`id`, `name`, `category`, `description`, `tags`,
   `quality_profile`, `polygon_budget`, `material_preset`, `parameters`).
2. If the shape needs new geometry, extend the matching builder in `scripts/generators/`
   (`props.py`, `architecture.py`, `terrain.py`, `humanoid.py`) — every builder receives
   `(scene, config, quality, rng)`.
3. `python scripts/build_all_assets.py --only <id>` → check the printed face/vertex/size numbers
   and the new entry in `public/assets/manifest.json`.
4. Add the preset id to `tests/test_specs.py` expectations if the catalogue size changes, run
   `pytest`, then commit. The gallery picks the model up automatically (it renders whatever the
   manifest lists).

### Rebuild with a different seed (art variation)

```bash
python scripts/build_all_assets.py --seed 4242
```

Commit the regenerated `.glb` files if you want the variation to be the published baseline; CI
regenerates from the same seeds anyway, so `main` stays the source of truth.

---

## 4. Local preview of the exact deployed artifact

```bash
python -m http.server 8080 --directory public
# http://localhost:8080
```

Any static file server works (`npx serve public`, Caddy, Nginx). Opening `public/index.html`
via `file://` will fail because ES modules and `fetch()` require an HTTP origin.

---

## 5. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `HttpError: Not Found - Get Pages site failed` | You are running an old workflow that used `actions/configure-pages`. This repo no longer references it; make sure `.github/workflows/` contains only `deploy.yml`. |
| Pages shows a 404 after a green run | Pages source is not set to the `gh-pages` branch (step 1). Check **Settings → Pages**. |
| Assets 404 on the project URL | A path was changed to a root-absolute form (`/assets/...`). All gallery URLs must stay relative (`./assets/...`); `tests/test_public_site.py` enforces this. |
| Manifest loads but a model fails | The `.glb` was not regenerated with the manifest. Run `python scripts/build_all_assets.py` (it prunes orphaned models and rewrites the manifest). |
| Hero face count outside 1,200–1,500 | `build_all_assets.py` fails loudly by design. Adjust `HERO_BUDGET_LADDER` in `scripts/generators/specs.py` or the ring density in `character_tpose.py`, then re-run. |
| `_files`/`node_modules` appearing on the site | Jekyll was enabled. `public/.nojekyll` must exist (it is committed) and `enable_jekyll: false` must remain in the workflow. |

---

## 6. Rollback

Every deploy is a single commit on `gh-pages`:

```bash
git fetch origin gh-pages
git log --oneline origin/gh-pages          # find the last good deploy commit
git push origin <good-commit>:gh-pages --force
```

or re-run the workflow for an earlier commit (**Actions → Build 3D Assets & Deploy Gallery →
Run workflow → branch/ref**), which rebuilds the models from that revision of the generators.
