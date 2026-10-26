export type AssetCategory = "humanoid" | "architecture" | "environment" | "props";

export type QualityProfile = "prototype" | "optimized_mid_poly" | "detailed_mid_poly";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type ExecutionMode = "live" | "github_actions";

export type ViewportShadingMode = "material" | "solid" | "wireframe";

export type CameraViewPreset = "perspective" | "front" | "rear" | "left" | "right" | "top";

export interface ParameterOption {
  value: string;
  label: string;
}

export interface ParameterSpec {
  name: string;
  label: string;
  type: "float" | "int" | "bool" | "select" | "color";
  default: number | boolean | string;
  description: string;
  min_value?: number | null;
  max_value?: number | null;
  step?: number | null;
  unit?: string | null;
  options?: ParameterOption[] | null;
  group: string;
}

export interface PolygonBudgetGuide {
  min_triangles: number;
  target_triangles: number;
  max_triangles: number;
}

export interface AssetTypeInfo {
  category: AssetCategory;
  name: string;
  description: string;
  icon: string;
  godot_target_notes: string;
  default_budgets: Record<QualityProfile, PolygonBudgetGuide>;
  recommended_capabilities: string[];
  parameter_specs: ParameterSpec[];
}

export interface PresetInfo {
  id: string;
  name: string;
  category: AssetCategory;
  description: string;
  tags: string[];
  quality_profile: QualityProfile;
  polygon_budget: number;
  material_preset: string;
  parameters: Record<string, number | boolean | string>;
}

export interface GenerateAssetRequest {
  name?: string | null;
  category: AssetCategory;
  preset_id: string;
  quality_profile: QualityProfile;
  seed: number;
  polygon_budget?: number | null;
  material_preset: string;
  save_blend: boolean;
  execution_mode: ExecutionMode;
  parameters: Record<string, number | boolean | string>;
}

export interface BoundingBox3D {
  min_corner: [number, number, number];
  max_corner: [number, number, number];
  dimensions: [number, number, number];
  center: [number, number, number];
  diagonal: number;
}

export interface MaterialSummary {
  name: string;
  base_color: [number, number, number, number];
  metallic: number;
  roughness: number;
  has_textures: boolean;
  texture_names: string[];
}

export interface RigSummary {
  has_armature: boolean;
  armature_name?: string | null;
  bone_count: number;
  bone_names: string[];
  root_bones: string[];
  skinned_mesh_count: number;
  normalized_weights_verified: boolean;
  max_influences_per_vertex: number;
  animation_clips: string[];
}

export interface MeshStats {
  actual_triangles: number;
  actual_vertices: number;
  gltf_render_vertices: number;
  polygon_faces: number;
  mesh_count: number;
  material_count: number;
  texture_count: number;
  connected_components: number;
  uv_layer_count: number;
  has_uvs: boolean;
  bounding_box: BoundingBox3D;
  materials: MaterialSummary[];
  rig: RigSummary;
}

export interface ValidationCheckItem {
  check_id: string;
  name: string;
  passed: boolean;
  severity: "info" | "warning" | "error";
  message: string;
  details: Record<string, unknown>;
}

export interface ValidationReport {
  valid: boolean;
  passed_count: number;
  warning_count: number;
  error_count: number;
  polygon_budget?: number | null;
  within_budget: boolean;
  reimport_verified: boolean;
  validator_backends: string[];
  checks: ValidationCheckItem[];
  warnings: string[];
  errors: string[];
}

export interface CapabilityStatus {
  id: string;
  name: string;
  kind: "blender_core" | "blender_addon" | "python_library";
  available: boolean;
  verified: boolean;
  version?: string | null;
  license: string;
  applicable_categories: AssetCategory[];
  fallback_strategy: string;
  status_message: string;
}

export interface JobProgressEntry {
  timestamp: string;
  stage: string;
  progress_pct: number;
  message: string;
}

export interface AssetRecord {
  id: string;
  job_id: string;
  name: string;
  category: AssetCategory;
  preset_id: string;
  quality_profile: QualityProfile;
  seed: number;
  polygon_budget: number;
  material_preset: string;
  parameters: Record<string, number | boolean | string>;
  created_at: string;
  glb_filename: string;
  glb_size_bytes: number;
  glb_download_url: string;
  blend_filename?: string | null;
  blend_size_bytes?: number | null;
  blend_download_url?: string | null;
  metadata_download_url: string;
  capabilities_used: string[];
  capabilities_fallback: string[];
  blender_version: string;
  generation_time_seconds: number;
  stats: MeshStats;
  validation: ValidationReport;
}

export interface JobRecord {
  id: string;
  status: JobStatus;
  execution_mode: ExecutionMode;
  stage: string;
  progress_pct: number;
  message: string;
  request: GenerateAssetRequest;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  retry_count: number;
  asset_id?: string | null;
  error?: string | null;
  logs: JobProgressEntry[];
  external_run_url?: string | null;
}

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  operating_mode: string;
  github_dispatch_configured: boolean;
  blender_available: boolean;
  blender_version?: string | null;
  active_jobs: number;
  queued_jobs: number;
  capabilities_verified: number;
  capabilities_total: number;
}
