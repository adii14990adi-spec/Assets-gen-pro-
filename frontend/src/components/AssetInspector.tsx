import React, { useState } from "react";
import {
  AlertTriangle,
  Bone,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  FileCode2,
  FolderOpen,
  Info,
  Layers,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { resolveApiUrl } from "../api/client";
import type { AssetRecord, JobRecord } from "../types/studio";

interface AssetInspectorProps {
  activeAsset: AssetRecord | null;
  activeJob: JobRecord | null;
  assetHistory: AssetRecord[];
  onSelectHistoryAsset: (asset: AssetRecord) => void;
}

type InspectorTab = "stats" | "validation" | "progress" | "library";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export const AssetInspector: React.FC<AssetInspectorProps> = ({
  activeAsset,
  activeJob,
  assetHistory,
  onSelectHistoryAsset,
}) => {
  const [tab, setTab] = useState<InspectorTab>("stats");
  const [showAllBones, setShowAllBones] = useState(false);

  const stats = activeAsset?.stats;
  const validation = activeAsset?.validation;

  return (
    <aside className="studio-right-panel" aria-label="Asset Inspector and Library">
      <div className="inspector-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "stats"}
          className={`insp-tab ${tab === "stats" ? "active" : ""}`}
          onClick={() => setTab("stats")}
        >
          <Layers size={14} />
          <span>Stats</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "validation"}
          className={`insp-tab ${tab === "validation" ? "active" : ""}`}
          onClick={() => setTab("validation")}
        >
          <ShieldCheck size={14} />
          <span>Checks</span>
          {validation && validation.warning_count > 0 && (
            <span className="badge-warn">{validation.warning_count}</span>
          )}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "progress"}
          className={`insp-tab ${tab === "progress" ? "active" : ""}`}
          onClick={() => setTab("progress")}
        >
          <Clock size={14} />
          <span>Job</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "library"}
          className={`insp-tab ${tab === "library" ? "active" : ""}`}
          onClick={() => setTab("library")}
        >
          <FolderOpen size={14} />
          <span>Library ({assetHistory.length})</span>
        </button>
      </div>

      <div className="panel-scroll">
        {/* TAB 1: MESH STATS, MATERIALS, RIG & DOWNLOADS */}
        {tab === "stats" && (
          <>
            {!activeAsset ? (
              <div className="empty-panel-note">
                <Info size={22} />
                <p>Generate or select an asset to inspect exact triangle counts, dimensions, PBR materials, rigging, and download options.</p>
              </div>
            ) : (
              <div className="inspector-stack" data-testid="asset-stats-panel">
                <div className="asset-header-card">
                  <div className="asset-badge-row">
                    <span className="cat-chip">{activeAsset.category}</span>
                    <span className="qual-chip">{activeAsset.quality_profile.replace(/_/g, " ")}</span>
                  </div>
                  <h3>{activeAsset.name}</h3>
                  <div className="meta-kv">
                    <span>Job ID:</span>
                    <code>{activeAsset.job_id}</code>
                  </div>
                  <div className="meta-kv">
                    <span>Asset ID:</span>
                    <code>{activeAsset.id}</code>
                  </div>
                  <div className="meta-kv">
                    <span>Runtime:</span>
                    <span>
                      Blender {activeAsset.blender_version} ({activeAsset.generation_time_seconds.toFixed(2)}s)
                    </span>
                  </div>
                </div>

                {/* Download Controls */}
                <div className="download-card">
                  <div className="section-label">Download Game-Ready Outputs</div>
                  <a
                    className="download-primary-btn"
                    href={resolveApiUrl(activeAsset.glb_download_url)}
                    download={activeAsset.glb_filename}
                    data-testid="download-glb-link"
                  >
                    <Download size={16} />
                    <span>
                      Download .GLB ({formatBytes(activeAsset.glb_size_bytes)})
                    </span>
                  </a>
                  <div className="download-secondary-row">
                    {activeAsset.blend_download_url && activeAsset.blend_filename && (
                      <a
                        className="download-sec-btn"
                        href={resolveApiUrl(activeAsset.blend_download_url)}
                        download={activeAsset.blend_filename}
                      >
                        <Download size={14} />
                        <span>.BLEND ({formatBytes(activeAsset.blend_size_bytes || 0)})</span>
                      </a>
                    )}
                    <a
                      className="download-sec-btn"
                      href={resolveApiUrl(activeAsset.metadata_download_url)}
                      download={`${activeAsset.id}_metadata.json`}
                    >
                      <FileCode2 size={14} />
                      <span>Metadata JSON</span>
                    </a>
                  </div>
                </div>

                {/* Measured Geometry Counts */}
                {stats && (
                  <div className="stats-grid-card">
                    <div className="section-label">Actual Measured Geometry</div>
                    <div className="metric-tiles">
                      <div className="metric-tile">
                        <span className="m-label">Triangles</span>
                        <strong className="m-val" data-testid="actual-triangles">
                          {stats.actual_triangles.toLocaleString()}
                        </strong>
                        <span className="m-sub">Budget: {activeAsset.polygon_budget.toLocaleString()}</span>
                      </div>
                      <div className="metric-tile">
                        <span className="m-label">Vertices</span>
                        <strong className="m-val">{stats.actual_vertices.toLocaleString()}</strong>
                        <span className="m-sub">glTF GPU: {stats.gltf_render_vertices.toLocaleString()}</span>
                      </div>
                      <div className="metric-tile">
                        <span className="m-label">Meshes</span>
                        <strong className="m-val">{stats.mesh_count}</strong>
                        <span className="m-sub">UV Maps: {stats.has_uvs ? "Yes" : "No"}</span>
                      </div>
                      <div className="metric-tile">
                        <span className="m-label">Materials</span>
                        <strong className="m-val">{stats.material_count}</strong>
                        <span className="m-sub">Textures: {stats.texture_count}</span>
                      </div>
                    </div>

                    {/* Dimensions & Bounding Box */}
                    <div className="section-label" style={{ marginTop: "0.75rem" }}>
                      Dimensions &amp; Bounding Box (m)
                    </div>
                    <div className="bbox-box">
                      <div>
                        <span>Size (W × H × D):</span>
                        <strong>
                          {stats.bounding_box.dimensions[0].toFixed(2)}m ×{" "}
                          {stats.bounding_box.dimensions[1].toFixed(2)}m ×{" "}
                          {stats.bounding_box.dimensions[2].toFixed(2)}m
                        </strong>
                      </div>
                      <div>
                        <span>Min Corner:</span>
                        <code>[{stats.bounding_box.min_corner.map((v) => v.toFixed(2)).join(", ")}]</code>
                      </div>
                      <div>
                        <span>Max Corner:</span>
                        <code>[{stats.bounding_box.max_corner.map((v) => v.toFixed(2)).join(", ")}]</code>
                      </div>
                    </div>

                    {/* Materials & Embedded Textures */}
                    <div className="section-label" style={{ marginTop: "0.75rem" }}>
                      PBR Materials &amp; Textures
                    </div>
                    <div className="mat-list">
                      {stats.materials.map((m) => {
                        const [r, g, b] = m.base_color;
                        const cssRgb = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
                        return (
                          <div key={m.name} className="mat-item">
                            <span className="mat-swatch" style={{ backgroundColor: cssRgb }} />
                            <div className="mat-meta">
                              <strong>{m.name}</strong>
                              <span>
                                Metal {m.metallic.toFixed(2)} · Rough {m.roughness.toFixed(2)}
                                {m.has_textures ? ` · Tex: ${m.texture_names.join(", ") || "Embedded PNG"}` : ""}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {/* Rig & Animation Info */}
                    <div className="section-label" style={{ marginTop: "0.75rem" }}>
                      Rigging &amp; Animation
                    </div>
                    {stats.rig.has_armature ? (
                      <div className="rig-box">
                        <div className="rig-header">
                          <Bone size={15} />
                          <strong>{stats.rig.armature_name || "Humanoid Armature"}</strong>
                        </div>
                        <p>
                          <strong>{stats.rig.bone_count}</strong> bones ·{" "}
                          <strong>{stats.rig.skinned_mesh_count}</strong> skinned mesh(es) · Max{" "}
                          <strong>{stats.rig.max_influences_per_vertex}</strong> weights/vert ·{" "}
                          {stats.rig.normalized_weights_verified ? "Normalized ✓" : "Unnormalized"}
                        </p>
                        {stats.rig.animation_clips.length > 0 && (
                          <p>Exported Clips: {stats.rig.animation_clips.join(", ")}</p>
                        )}
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => setShowAllBones((v) => !v)}
                        >
                          {showAllBones ? "Hide Bone Hierarchy" : `Show ${stats.rig.bone_names.length} Bones`}
                        </button>
                        {showAllBones && (
                          <div className="bone-tags">
                            {stats.rig.bone_names.map((bName) => (
                              <code key={bName}>{bName}</code>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <p className="muted-line">Static asset (no armature attached).</p>
                    )}

                    {/* Capabilities Used & Honest Fallbacks */}
                    <div className="section-label" style={{ marginTop: "0.75rem" }}>
                      Active Capabilities &amp; Fallbacks
                    </div>
                    <div className="bone-tags">
                      {activeAsset.capabilities_used.map((cap) => (
                        <code key={cap}>{cap}</code>
                      ))}
                    </div>
                    {activeAsset.capabilities_fallback.length > 0 && (
                      <ul className="fallback-notes">
                        {activeAsset.capabilities_fallback.map((fb) => (
                          <li key={fb}>{fb}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* TAB 2: VALIDATION REPORT */}
        {tab === "validation" && (
          <>
            {!validation ? (
              <div className="empty-panel-note">
                <ShieldCheck size={22} />
                <p>Validation checks appear here once an asset is generated or uploaded.</p>
              </div>
            ) : (
              <div className="inspector-stack">
                <div className={`val-summary ${validation.valid ? "ok" : "err"}`}>
                  {validation.valid ? <CheckCircle2 size={20} /> : <XCircle size={20} />}
                  <div>
                    <strong>{validation.valid ? "Validation Passed" : "Validation Failed"}</strong>
                    <span>
                      {validation.passed_count} passed · {validation.warning_count} warning(s) ·{" "}
                      {validation.error_count} error(s)
                    </span>
                  </div>
                </div>
                <div className="muted-line">
                  Backends: {validation.validator_backends.join(", ")}
                </div>
                <div className="check-list">
                  {validation.checks.map((chk) => (
                    <div key={chk.check_id} className={`check-item ${chk.passed ? "pass" : chk.severity}`}>
                      {chk.passed ? (
                        <CheckCircle2 size={15} className="ic-pass" />
                      ) : chk.severity === "warning" ? (
                        <AlertTriangle size={15} className="ic-warn" />
                      ) : (
                        <XCircle size={15} className="ic-err" />
                      )}
                      <div>
                        <strong>{chk.name}</strong>
                        <p>{chk.message}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* TAB 3: LIVE JOB STATUS & LOGS */}
        {tab === "progress" && (
          <>
            {!activeJob ? (
              <div className="empty-panel-note">
                <Clock size={22} />
                <p>No generation job started in this session yet.</p>
              </div>
            ) : (
              <div className="inspector-stack">
                <div className="asset-header-card">
                  <div className="asset-badge-row">
                    <span className={`status-pill status-${activeJob.status}`}>{activeJob.status}</span>
                    <span>{activeJob.progress_pct}%</span>
                  </div>
                  <h4>{activeJob.id}</h4>
                  <p className="preset-desc">{activeJob.message}</p>
                  {activeJob.error && (
                    <div className="job-error-box" role="alert">
                      {activeJob.error}
                    </div>
                  )}
                  {activeJob.external_run_url && (
                    <a
                      href={activeJob.external_run_url}
                      target="_blank"
                      rel="noreferrer"
                      className="link-btn"
                    >
                      <ExternalLink size={13} /> View GitHub Actions Workflow
                    </a>
                  )}
                </div>
                <div className="log-timeline">
                  {activeJob.logs.map((entry, idx) => (
                    <div key={`${entry.timestamp}-${idx}`} className="log-row">
                      <span className="log-pct">{entry.progress_pct}%</span>
                      <div>
                        <strong>{entry.stage}</strong>
                        <p>{entry.message}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* TAB 4: PERSISTENT ASSET LIBRARY */}
        {tab === "library" && (
          <div className="inspector-stack">
            {assetHistory.length === 0 ? (
              <div className="empty-panel-note">
                <FolderOpen size={22} />
                <p>Generated 3D assets are stored persistently and listed here for instant reopening.</p>
              </div>
            ) : (
              assetHistory.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`library-card ${activeAsset?.id === item.id ? "selected" : ""}`}
                  onClick={() => onSelectHistoryAsset(item)}
                >
                  <div className="lib-top">
                    <strong>{item.name}</strong>
                    <span className="cat-chip">{item.category}</span>
                  </div>
                  <div className="lib-sub">
                    <span>{item.stats.actual_triangles.toLocaleString()} tris</span>
                    <span>·</span>
                    <span>{formatBytes(item.glb_size_bytes)}</span>
                    <span>·</span>
                    <span>Seed {item.seed}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
