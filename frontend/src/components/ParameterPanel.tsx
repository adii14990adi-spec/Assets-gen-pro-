import React, { useMemo } from "react";
import {
  Box,
  Building2,
  Dices,
  Mountain,
  Play,
  RefreshCw,
  Square,
  User,
} from "lucide-react";
import type {
  AssetCategory,
  AssetTypeInfo,
  ExecutionMode,
  ParameterOption,
  ParameterSpec,
  PresetInfo,
  QualityProfile,
} from "../types/studio";

interface ParameterPanelProps {
  assetTypes: AssetTypeInfo[];
  selectedCategory: AssetCategory;
  onSelectCategory: (category: AssetCategory) => void;
  presets: PresetInfo[];
  selectedPresetId: string;
  onSelectPreset: (presetId: string) => void;
  assetName: string;
  onChangeAssetName: (name: string) => void;
  qualityProfile: QualityProfile;
  onChangeQualityProfile: (q: QualityProfile) => void;
  polygonBudget: number;
  onChangePolygonBudget: (b: number) => void;
  materialPreset: string;
  materialOptions: ParameterOption[];
  onChangeMaterialPreset: (m: string) => void;
  seed: number;
  onChangeSeed: (seed: number) => void;
  saveBlend: boolean;
  onChangeSaveBlend: (v: boolean) => void;
  executionMode: ExecutionMode;
  onChangeExecutionMode: (mode: ExecutionMode) => void;
  parameters: Record<string, number | boolean | string>;
  onChangeParameter: (name: string, value: number | boolean | string) => void;
  isGenerating: boolean;
  hasActiveAsset: boolean;
  onGenerate: () => void;
  onCancel: () => void;
}

const CATEGORY_ICONS: Record<AssetCategory, React.ReactNode> = {
  humanoid: <User size={16} />,
  architecture: <Building2 size={16} />,
  environment: <Mountain size={16} />,
  props: <Box size={16} />,
};

export const ParameterPanel: React.FC<ParameterPanelProps> = ({
  assetTypes,
  selectedCategory,
  onSelectCategory,
  presets,
  selectedPresetId,
  onSelectPreset,
  assetName,
  onChangeAssetName,
  qualityProfile,
  onChangeQualityProfile,
  polygonBudget,
  onChangePolygonBudget,
  materialPreset,
  materialOptions,
  onChangeMaterialPreset,
  seed,
  onChangeSeed,
  saveBlend,
  onChangeSaveBlend,
  executionMode,
  onChangeExecutionMode,
  parameters,
  onChangeParameter,
  isGenerating,
  hasActiveAsset,
  onGenerate,
  onCancel,
}) => {
  const currentType = useMemo(
    () => assetTypes.find((t) => t.category === selectedCategory),
    [assetTypes, selectedCategory]
  );

  const categoryPresets = useMemo(
    () => presets.filter((p) => p.category === selectedCategory),
    [presets, selectedCategory]
  );

  const groupedSpecs = useMemo(() => {
    const groups: Record<string, ParameterSpec[]> = {};
    for (const spec of currentType?.parameter_specs || []) {
      if (!groups[spec.group]) {
        groups[spec.group] = [];
      }
      groups[spec.group].push(spec);
    }
    return groups;
  }, [currentType]);

  const budgetGuide = currentType?.default_budgets[qualityProfile];

  return (
    <aside className="studio-left-panel" aria-label="Asset Configuration">
      {/* Category Selector Tabs */}
      <div className="category-grid" role="tablist" aria-label="Asset Categories">
        {assetTypes.map((t) => (
          <button
            key={t.category}
            type="button"
            role="tab"
            aria-selected={selectedCategory === t.category}
            className={`category-tab ${selectedCategory === t.category ? "active" : ""}`}
            onClick={() => onSelectCategory(t.category)}
          >
            {CATEGORY_ICONS[t.category]}
            <span>{t.name.split(" ")[0]}</span>
          </button>
        ))}
      </div>

      <div className="panel-scroll">
        {currentType && (
          <p className="category-hint">{currentType.godot_target_notes}</p>
        )}

        {/* Preset Selector */}
        <section className="control-section">
          <label className="section-label" htmlFor="preset-select">
            Model Preset
          </label>
          <select
            id="preset-select"
            className="studio-input"
            value={selectedPresetId}
            onChange={(e) => onSelectPreset(e.target.value)}
          >
            {categoryPresets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {categoryPresets.find((p) => p.id === selectedPresetId) && (
            <p className="preset-desc">
              {categoryPresets.find((p) => p.id === selectedPresetId)?.description}
            </p>
          )}
        </section>

        {/* Custom Name & Seed */}
        <section className="control-section">
          <div className="field-row">
            <label htmlFor="asset-name-input">Asset Name</label>
            <input
              id="asset-name-input"
              type="text"
              className="studio-input"
              placeholder="Optional custom name..."
              value={assetName}
              maxLength={80}
              onChange={(e) => onChangeAssetName(e.target.value)}
            />
          </div>

          <div className="field-row">
            <label htmlFor="seed-input">Deterministic Seed</label>
            <div className="seed-row">
              <input
                id="seed-input"
                type="number"
                className="studio-input"
                min={0}
                max={2147483647}
                value={seed}
                onChange={(e) => onChangeSeed(Math.max(0, Number(e.target.value) || 0))}
              />
              <button
                type="button"
                className="icon-btn"
                title="Randomize Seed"
                onClick={() => onChangeSeed(Math.floor(Math.random() * 999999))}
              >
                <Dices size={16} />
              </button>
            </div>
          </div>
        </section>

        {/* Quality Profile, Budget & Material */}
        <section className="control-section">
          <div className="section-label">Quality &amp; Polygon Budget</div>

          <div className="quality-pills">
            {(
              [
                ["prototype", "Prototype"],
                ["optimized_mid_poly", "Optimized"],
                ["detailed_mid_poly", "Detailed"],
              ] as [QualityProfile, string][]
            ).map(([qId, label]) => (
              <button
                key={qId}
                type="button"
                className={`pill-btn ${qualityProfile === qId ? "active" : ""}`}
                onClick={() => onChangeQualityProfile(qId)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="field-row">
            <div className="slider-header">
              <label htmlFor="budget-input">Target Triangle Budget</label>
              <span className="mono-val">{polygonBudget.toLocaleString()} tris</span>
            </div>
            <input
              id="budget-input"
              type="range"
              min={budgetGuide ? budgetGuide.min_triangles : 200}
              max={budgetGuide ? budgetGuide.max_triangles : 45000}
              step={100}
              value={polygonBudget}
              onChange={(e) => onChangePolygonBudget(Number(e.target.value))}
            />
            {budgetGuide && (
              <div className="range-captions">
                <span>Min: {budgetGuide.min_triangles.toLocaleString()}</span>
                <span>Rec: {budgetGuide.target_triangles.toLocaleString()}</span>
                <span>Max: {budgetGuide.max_triangles.toLocaleString()}</span>
              </div>
            )}
          </div>

          <div className="field-row">
            <label htmlFor="material-select">PBR Material Theme</label>
            <select
              id="material-select"
              className="studio-input"
              value={materialPreset}
              onChange={(e) => onChangeMaterialPreset(e.target.value)}
            >
              {materialOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </section>

        {/* Dynamic Category Parameters */}
        {Object.entries(groupedSpecs).map(([groupName, specs]) => (
          <section key={groupName} className="control-section">
            <div className="section-label">{groupName}</div>
            {specs.map((spec) => {
              const rawVal = parameters[spec.name] ?? spec.default;
              if (spec.type === "bool") {
                return (
                  <label key={spec.name} className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={Boolean(rawVal)}
                      onChange={(e) => onChangeParameter(spec.name, e.target.checked)}
                    />
                    <span>{spec.label}</span>
                  </label>
                );
              }
              if (spec.type === "select") {
                return (
                  <div key={spec.name} className="field-row">
                    <label htmlFor={`param-${spec.name}`}>{spec.label}</label>
                    <select
                      id={`param-${spec.name}`}
                      className="studio-input"
                      value={String(rawVal)}
                      onChange={(e) => onChangeParameter(spec.name, e.target.value)}
                    >
                      {(spec.options || []).map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              }
              if (spec.type === "color") {
                const strVal = typeof rawVal === "string" && rawVal.startsWith("#") ? rawVal : "";
                const pickerVal = strVal || (spec.name === "skin_color" ? "#e6a88a" : "#3b82f6");
                return (
                  <div key={spec.name} className="field-row">
                    <div className="slider-header">
                      <label htmlFor={`param-${spec.name}`}>{spec.label}</label>
                      <span className="mono-val">{strVal || "theme"}</span>
                    </div>
                    <div className="seed-row">
                      <input
                        id={`param-${spec.name}`}
                        type="color"
                        className="studio-input"
                        style={{ height: 36, padding: 2, cursor: "pointer" }}
                        value={pickerVal}
                        onChange={(e) => onChangeParameter(spec.name, e.target.value)}
                      />
                      {strVal && (
                        <button
                          type="button"
                          className="icon-btn"
                          title="Reset to theme default"
                          onClick={() => onChangeParameter(spec.name, "")}
                        >
                          ×
                        </button>
                      )}
                    </div>
                  </div>
                );
              }
              return (
                <div key={spec.name} className="field-row">
                  <div className="slider-header">
                    <label htmlFor={`param-${spec.name}`}>{spec.label}</label>
                    <span className="mono-val">
                      {typeof rawVal === "number"
                        ? spec.type === "int"
                          ? rawVal
                          : rawVal.toFixed(2)
                        : String(rawVal)}
                      {spec.unit ? ` ${spec.unit}` : ""}
                    </span>
                  </div>
                  <input
                    id={`param-${spec.name}`}
                    type="range"
                    min={spec.min_value ?? 0}
                    max={spec.max_value ?? 10}
                    step={spec.step ?? (spec.type === "int" ? 1 : 0.05)}
                    value={Number(rawVal)}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      onChangeParameter(spec.name, spec.type === "int" ? Math.round(n) : n);
                    }}
                  />
                </div>
              );
            })}
          </section>
        ))}

        {/* Export & Pipeline Options */}
        <section className="control-section">
          <div className="section-label">Export &amp; Pipeline Mode</div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={saveBlend}
              onChange={(e) => onChangeSaveBlend(e.target.checked)}
            />
            <span>Save Native Blender (.blend) Project</span>
          </label>
          <div className="field-row">
            <label htmlFor="exec-mode-select">Execution Backend</label>
            <select
              id="exec-mode-select"
              className="studio-input"
              value={executionMode}
              onChange={(e) => onChangeExecutionMode(e.target.value as ExecutionMode)}
            >
              <option value="live">Mode B: Live Blender Worker Service</option>
              <option value="github_actions">Mode A: GitHub Actions Workflow Dispatch</option>
            </select>
          </div>
        </section>
      </div>

      {/* Primary Action Footer */}
      <div className="panel-footer">
        {!isGenerating ? (
          <button
            type="button"
            className="generate-btn"
            onClick={onGenerate}
            data-testid="generate-btn"
          >
            {hasActiveAsset ? <RefreshCw size={17} /> : <Play size={17} />}
            <span>{hasActiveAsset ? "Regenerate 3D Asset" : "Generate 3D Asset"}</span>
          </button>
        ) : (
          <button type="button" className="cancel-btn" onClick={onCancel}>
            <Square size={16} />
            <span>Cancel Running Job</span>
          </button>
        )}
      </div>
    </aside>
  );
};
