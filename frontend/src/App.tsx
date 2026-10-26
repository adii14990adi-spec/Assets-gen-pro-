import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Cpu,
  Sliders,
  Upload,
  Box,
  Layers,
} from "lucide-react";
import {
  cancelJob,
  createVerifiedGlbObjectUrlFromBuffer,
  fetchVerifiedGlbObjectUrl,
  getAssetTypesCatalog,
  getCapabilities,
  getHealth,
  getJobResult,
  getPresets,
  listAssets,
  submitGenerationJob,
  subscribeToJobProgress,
  validateUploadedGlb,
} from "./api/client";
import { AssetInspector } from "./components/AssetInspector";
import { CapabilitiesModal } from "./components/CapabilitiesModal";
import { ParameterPanel } from "./components/ParameterPanel";
import { Viewport3D } from "./components/Viewport3D";
import type {
  AssetCategory,
  AssetRecord,
  AssetTypeInfo,
  CapabilityStatus,
  ExecutionMode,
  HealthStatus,
  JobRecord,
  ParameterOption,
  PresetInfo,
  QualityProfile,
} from "./types/studio";

type MobilePane = "config" | "viewport" | "inspector";

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [assetTypes, setAssetTypes] = useState<AssetTypeInfo[]>([]);
  const [materialOptions, setMaterialOptions] = useState<ParameterOption[]>([]);
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityStatus[]>([]);
  const [isCapModalOpen, setIsCapModalOpen] = useState(false);
  const [isRefreshingCaps, setIsRefreshingCaps] = useState(false);

  // Configuration state
  const [selectedCategory, setSelectedCategory] = useState<AssetCategory>("architecture");
  const [selectedPresetId, setSelectedPresetId] = useState<string>("rajasthani_haveli");
  const [assetName, setAssetName] = useState<string>("");
  const [qualityProfile, setQualityProfile] = useState<QualityProfile>("optimized_mid_poly");
  const [polygonBudget, setPolygonBudget] = useState<number>(5600);
  const [materialPreset, setMaterialPreset] = useState<string>("rajasthan_sandstone");
  const [seed, setSeed] = useState<number>(1727);
  const [saveBlend, setSaveBlend] = useState<boolean>(true);
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("live");
  const [parameters, setParameters] = useState<Record<string, number | boolean | string>>({});

  // Job & Asset state
  const [activeJob, setActiveJob] = useState<JobRecord | null>(null);
  const [activeAsset, setActiveAsset] = useState<AssetRecord | null>(null);
  const [assetHistory, setAssetHistory] = useState<AssetRecord[]>([]);
  const [glbObjectUrl, setGlbObjectUrl] = useState<string | null>(null);
  const [studioError, setStudioError] = useState<string | null>(null);
  const [mobilePane, setMobilePane] = useState<MobilePane>("viewport");

  const activeBlobUrlRef = useRef<string | null>(null);
  const jobUnsubRef = useRef<(() => void) | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);

  const replaceObjectUrl = useCallback((nextUrl: string | null) => {
    if (activeBlobUrlRef.current && activeBlobUrlRef.current !== nextUrl) {
      URL.revokeObjectURL(activeBlobUrlRef.current);
    }
    activeBlobUrlRef.current = nextUrl;
    setGlbObjectUrl(nextUrl);
  }, []);

  useEffect(() => {
    return () => {
      if (jobUnsubRef.current) {
        jobUnsubRef.current();
      }
      if (activeBlobUrlRef.current) {
        URL.revokeObjectURL(activeBlobUrlRef.current);
        activeBlobUrlRef.current = null;
      }
    };
  }, []);

  const applyPresetDefaults = useCallback(
    (preset: PresetInfo, typesList: AssetTypeInfo[]) => {
      setSelectedCategory(preset.category);
      setSelectedPresetId(preset.id);
      setQualityProfile(preset.quality_profile);
      setPolygonBudget(preset.polygon_budget);
      setMaterialPreset(preset.material_preset);
      const tInfo = typesList.find((t) => t.category === preset.category);
      const merged: Record<string, number | boolean | string> = {};
      for (const spec of tInfo?.parameter_specs || []) {
        merged[spec.name] = spec.default;
      }
      Object.assign(merged, preset.parameters);
      setParameters(merged);
    },
    []
  );

  const loadAssetIntoViewport = useCallback(
    async (asset: AssetRecord) => {
      setStudioError(null);
      setActiveAsset(asset);
      try {
        const { objectUrl } = await fetchVerifiedGlbObjectUrl(asset.glb_download_url);
        replaceObjectUrl(objectUrl);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setStudioError(msg);
      }
    },
    [replaceObjectUrl]
  );

  // Initial Studio Boot
  useEffect(() => {
    let mounted = true;
    const boot = async () => {
      try {
        const [healthRes, catalogRes, presetsRes, historyRes, capRes] = await Promise.all([
          getHealth(),
          getAssetTypesCatalog(),
          getPresets(),
          listAssets(),
          getCapabilities(false),
        ]);
        if (!mounted) return;
        setHealth(healthRes);
        setAssetTypes(catalogRes.types);
        setMaterialOptions(catalogRes.material_presets);
        setPresets(presetsRes);
        setAssetHistory(historyRes);
        setCapabilities(capRes.capabilities);

        const defaultPreset =
          presetsRes.find((p) => p.id === "rajasthani_haveli") || presetsRes[0];
        if (defaultPreset) {
          applyPresetDefaults(defaultPreset, catalogRes.types);
        }

        if (historyRes.length > 0) {
          await loadAssetIntoViewport(historyRes[0]);
        }
      } catch (err) {
        if (!mounted) return;
        setStudioError(
          err instanceof Error ? `Backend connection error: ${err.message}` : "Failed to initialize studio."
        );
      }
    };
    void boot();
    return () => {
      mounted = false;
    };
  }, [applyPresetDefaults, loadAssetIntoViewport]);

  const handleSelectCategory = useCallback(
    (category: AssetCategory) => {
      setSelectedCategory(category);
      const firstPreset = presets.find((p) => p.category === category);
      if (firstPreset) {
        applyPresetDefaults(firstPreset, assetTypes);
      }
    },
    [presets, assetTypes, applyPresetDefaults]
  );

  const handleSelectPreset = useCallback(
    (presetId: string) => {
      const found = presets.find((p) => p.id === presetId);
      if (found) {
        applyPresetDefaults(found, assetTypes);
      }
    },
    [presets, assetTypes, applyPresetDefaults]
  );

  const handleChangeQualityProfile = useCallback(
    (q: QualityProfile) => {
      setQualityProfile(q);
      const tInfo = assetTypes.find((t) => t.category === selectedCategory);
      if (tInfo) {
        setPolygonBudget(tInfo.default_budgets[q].target_triangles);
      }
    },
    [assetTypes, selectedCategory]
  );

  const handleChangeParameter = useCallback(
    (name: string, value: number | boolean | string) => {
      setParameters((prev) => ({ ...prev, [name]: value }));
    },
    []
  );

  const handleRefreshCapabilities = useCallback(async () => {
    setIsRefreshingCaps(true);
    try {
      const res = await getCapabilities(true);
      setCapabilities(res.capabilities);
    } catch (err) {
      setStudioError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsRefreshingCaps(false);
    }
  }, []);

  const handleStartGeneration = useCallback(async () => {
    setStudioError(null);
    setMobilePane("viewport");
    if (jobUnsubRef.current) {
      jobUnsubRef.current();
      jobUnsubRef.current = null;
    }

    try {
      const queuedJob = await submitGenerationJob({
        name: assetName.trim() || null,
        category: selectedCategory,
        preset_id: selectedPresetId,
        quality_profile: qualityProfile,
        seed,
        polygon_budget: polygonBudget,
        material_preset: materialPreset,
        save_blend: saveBlend,
        execution_mode: executionMode,
        parameters,
      });

      setActiveJob(queuedJob);

      jobUnsubRef.current = subscribeToJobProgress(
        queuedJob.id,
        async (updatedJob) => {
          setActiveJob(updatedJob);
          if (updatedJob.status === "completed") {
            const result = await getJobResult(updatedJob.id);
            const refreshedHistory = await listAssets();
            setAssetHistory(refreshedHistory);
            if (result.asset) {
              await loadAssetIntoViewport(result.asset);
            }
          } else if (updatedJob.status === "failed") {
            setStudioError(updatedJob.error || "Blender generation job failed.");
          }
        },
        (err) => {
          setStudioError(err.message);
        }
      );
    } catch (err) {
      setStudioError(err instanceof Error ? err.message : String(err));
    }
  }, [
    assetName,
    selectedCategory,
    selectedPresetId,
    qualityProfile,
    seed,
    polygonBudget,
    materialPreset,
    saveBlend,
    executionMode,
    parameters,
    loadAssetIntoViewport,
  ]);

  const handleCancelJob = useCallback(async () => {
    if (!activeJob) return;
    try {
      const cancelled = await cancelJob(activeJob.id);
      setActiveJob(cancelled);
    } catch (err) {
      setStudioError(err instanceof Error ? err.message : String(err));
    }
  }, [activeJob]);

  const handleSelectHistoryAsset = useCallback(
    async (asset: AssetRecord) => {
      setSelectedCategory(asset.category);
      setSelectedPresetId(asset.preset_id);
      setAssetName(asset.name);
      setQualityProfile(asset.quality_profile);
      setPolygonBudget(asset.polygon_budget);
      setMaterialPreset(asset.material_preset);
      setSeed(asset.seed);
      setParameters(asset.parameters);
      setMobilePane("viewport");
      await loadAssetIntoViewport(asset);
    },
    [loadAssetIntoViewport]
  );

  const handleUploadGlbFile = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      setStudioError(null);
      try {
        const buffer = await file.arrayBuffer();
        const { objectUrl } = createVerifiedGlbObjectUrlFromBuffer(buffer);
        const valRes = await validateUploadedGlb(file, polygonBudget);
        replaceObjectUrl(objectUrl);

        if (valRes.stats) {
          setActiveAsset({
            id: `uploaded_${Date.now()}`,
            job_id: "local_upload",
            name: file.name.replace(/\.glb$/i, ""),
            category: selectedCategory,
            preset_id: selectedPresetId,
            quality_profile: qualityProfile,
            seed,
            polygon_budget: polygonBudget,
            material_preset: materialPreset,
            parameters,
            created_at: new Date().toISOString(),
            glb_filename: file.name,
            glb_size_bytes: file.size,
            glb_download_url: objectUrl,
            metadata_download_url: objectUrl,
            capabilities_used: ["trimesh", "gltf_binary_inspector"],
            capabilities_fallback: [],
            blender_version: "External GLB",
            generation_time_seconds: 0,
            stats: valRes.stats,
            validation: valRes.validation,
          });
        }
      } catch (err) {
        setStudioError(err instanceof Error ? err.message : String(err));
      }
    },
    [polygonBudget, replaceObjectUrl, selectedCategory, selectedPresetId, qualityProfile, seed, materialPreset, parameters]
  );

  const isGenerating = Boolean(
    activeJob && (activeJob.status === "queued" || activeJob.status === "running")
  );

  return (
    <div className="studio-app">
      {/* Top Studio Header */}
      <header className="studio-header">
        <div className="brand-block">
          <div className="brand-logo">3D</div>
          <div>
            <h1>Procedural 3D Asset Generator Studio</h1>
            <p className="brand-sub">
              Python · Blender {health?.blender_version || "4.2 LTS"} · NumPy · Geometry Nodes · Godot 4 Android Pipeline
            </p>
          </div>
        </div>

        <div className="header-actions">
          <span
            className={`runtime-badge ${
              health?.blender_available || health?.python_fallback_available ? "online" : "offline"
            }`}
            title="3D Generation Engine Status (Blender 4.2 LTS or Pure-Python fallback)"
          >
            <Activity size={13} />
            <span>
              {!health
                ? "Checking Generation Engine..."
                : health.blender_available
                  ? `Blender ${health.blender_version} Ready`
                  : health.python_fallback_available
                    ? "Python Fallback Engine Ready"
                    : "No Generation Engine Available"}
            </span>
          </span>

          <button
            type="button"
            className="header-btn"
            onClick={() => setIsCapModalOpen(true)}
          >
            <Cpu size={15} />
            <span>
              Capabilities ({health?.capabilities_verified ?? capabilities.filter((c) => c.verified).length}/
              {health?.capabilities_total ?? capabilities.length})
            </span>
          </button>

          <button
            type="button"
            className="header-btn"
            onClick={() => uploadInputRef.current?.click()}
            title="Inspect & Validate an External .GLB File"
          >
            <Upload size={15} />
            <span>Validate .GLB</span>
          </button>
          <input
            ref={uploadInputRef}
            type="file"
            accept=".glb,model/gltf-binary"
            style={{ display: "none" }}
            onChange={handleUploadGlbFile}
          />
        </div>
      </header>

      {/* Mobile Responsive Navigation Bar (Android / Small Screens) */}
      <nav className="mobile-pane-nav" aria-label="Studio Mobile View Switcher">
        <button
          type="button"
          className={mobilePane === "config" ? "active" : ""}
          onClick={() => setMobilePane("config")}
        >
          <Sliders size={15} />
          <span>Configure</span>
        </button>
        <button
          type="button"
          className={mobilePane === "viewport" ? "active" : ""}
          onClick={() => setMobilePane("viewport")}
        >
          <Box size={15} />
          <span>3D Viewport</span>
        </button>
        <button
          type="button"
          className={mobilePane === "inspector" ? "active" : ""}
          onClick={() => setMobilePane("inspector")}
        >
          <Layers size={15} />
          <span>Inspector</span>
        </button>
      </nav>

      {/* Main 3-Pane Studio Workspace */}
      <main className={`studio-workspace mobile-show-${mobilePane}`}>
        <ParameterPanel
          assetTypes={assetTypes}
          selectedCategory={selectedCategory}
          onSelectCategory={handleSelectCategory}
          presets={presets}
          selectedPresetId={selectedPresetId}
          onSelectPreset={handleSelectPreset}
          assetName={assetName}
          onChangeAssetName={setAssetName}
          qualityProfile={qualityProfile}
          onChangeQualityProfile={handleChangeQualityProfile}
          polygonBudget={polygonBudget}
          onChangePolygonBudget={setPolygonBudget}
          materialPreset={materialPreset}
          materialOptions={materialOptions}
          onChangeMaterialPreset={setMaterialPreset}
          seed={seed}
          onChangeSeed={setSeed}
          saveBlend={saveBlend}
          onChangeSaveBlend={setSaveBlend}
          executionMode={executionMode}
          onChangeExecutionMode={setExecutionMode}
          parameters={parameters}
          onChangeParameter={handleChangeParameter}
          isGenerating={isGenerating}
          hasActiveAsset={Boolean(activeAsset)}
          onGenerate={handleStartGeneration}
          onCancel={handleCancelJob}
        />

        <Viewport3D
          glbObjectUrl={glbObjectUrl}
          assetTitle={activeAsset ? `${activeAsset.name} (${activeAsset.glb_filename})` : null}
          isGenerating={isGenerating}
          generationProgressPct={activeJob?.progress_pct ?? 0}
          generationStageText={activeJob?.message || "Preparing Blender runtime..."}
          externalError={studioError}
          hasRig={Boolean(activeAsset?.stats.rig.has_armature)}
        />

        <AssetInspector
          activeAsset={activeAsset}
          activeJob={activeJob}
          assetHistory={assetHistory}
          onSelectHistoryAsset={handleSelectHistoryAsset}
        />
      </main>

      <CapabilitiesModal
        open={isCapModalOpen}
        capabilities={capabilities}
        isRefreshing={isRefreshingCaps}
        onRefresh={handleRefreshCapabilities}
        onClose={() => setIsCapModalOpen(false)}
      />
    </div>
  );
};

export default App;
