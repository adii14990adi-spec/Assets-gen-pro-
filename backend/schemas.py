"""Pydantic v2 request, response, metadata, validation, and job schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.enums import AssetCategory, ExecutionMode, JobStatus, QualityProfile


class ParameterOption(BaseModel):
    value: str
    label: str


class ParameterSpec(BaseModel):
    name: str
    label: str
    type: Literal["float", "int", "bool", "select", "color"]
    default: Any
    description: str = ""
    min_value: float | int | None = None
    max_value: float | int | None = None
    step: float | int | None = None
    unit: str | None = None
    options: list[ParameterOption] | None = None
    group: str = "General"


class PolygonBudgetGuide(BaseModel):
    min_triangles: int
    target_triangles: int
    max_triangles: int


class AssetTypeInfo(BaseModel):
    category: AssetCategory
    name: str
    description: str
    icon: str
    godot_target_notes: str
    default_budgets: dict[QualityProfile, PolygonBudgetGuide]
    recommended_capabilities: list[str]
    parameter_specs: list[ParameterSpec]


class PresetInfo(BaseModel):
    id: str
    name: str
    category: AssetCategory
    description: str
    tags: list[str] = Field(default_factory=list)
    quality_profile: QualityProfile = QualityProfile.OPTIMIZED_MID_POLY
    polygon_budget: int = Field(ge=100, le=250_000)
    material_preset: str = "default"
    parameters: dict[str, Any] = Field(default_factory=dict)


class GenerateAssetRequest(BaseModel):
    """Strict, validated asset generation request. Rejects arbitrary scripts or paths."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80, description="Optional custom asset name")
    category: AssetCategory
    preset_id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_]+$")
    quality_profile: QualityProfile = QualityProfile.OPTIMIZED_MID_POLY
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    polygon_budget: int | None = Field(default=None, ge=100, le=200_000)
    material_preset: str = Field(default="default", min_length=2, max_length=48, pattern=r"^[a-z0-9_]+$")
    target_faces: int | None = Field(default=None, ge=100, le=200_000)
    flat_shading: bool | None = Field(default=None)
    skin_color: str | None = Field(default=None, max_length=16)
    outfit_color: str | None = Field(default=None, max_length=16)
    save_blend: bool = Field(default=True, description="Also save native .blend project file")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.LIVE)
    parameters: dict[str, float | int | bool | str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        for forbidden in ("..", "/", "\\", "\x00", ";", "`", "$"):
            if forbidden in cleaned:
                raise ValueError(f"Asset name contains disallowed character sequence: {forbidden!r}")
        return cleaned


class DirectGenerateRequest(BaseModel):
    """Immediate procedural 3D generation payload supporting shorthand presets & direct hex colors."""

    model_config = ConfigDict(extra="forbid")

    preset: str = Field(
        default="midpoly_character",
        min_length=2,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Preset or category shorthand ('midpoly_character', 'architecture', 'terrain', 'prop', or preset ID).",
    )
    preset_id: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-z0-9_]+$")
    category: AssetCategory | None = None
    target_faces: int = Field(default=1800, ge=100, le=200_000)
    flat_shading: bool = Field(default=True)
    skin_color: str = Field(default="#e6a88a", max_length=16)
    outfit_color: str = Field(default="#3b82f6", max_length=16)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    quality_profile: QualityProfile = QualityProfile.OPTIMIZED_MID_POLY
    material_preset: str = Field(default="default", min_length=2, max_length=48, pattern=r"^[a-z0-9_]+$")
    name: str | None = Field(default=None, max_length=80)
    response_format: Literal["json", "glb"] | None = None
    sync: bool = Field(default=True)
    parameters: dict[str, float | int | bool | str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def sanitize_direct_name(cls, value: str | None) -> str | None:
        return GenerateAssetRequest.sanitize_name(value)

    @field_validator("skin_color", "outfit_color")
    @classmethod
    def validate_hex(cls, value: str) -> str:
        cleaned = value.strip()
        h = cleaned.lstrip("#")
        if len(h) == 3 and all(c in "0123456789abcdefABCDEF" for c in h):
            h = "".join(c * 2 for c in h)
        if len(h) != 6 or not all(c in "0123456789abcdefABCDEF" for c in h):
            raise ValueError(f"Expected hex color (#RRGGBB or #RGB), got {value!r}.")
        return f"#{h.lower()}"


class BoundingBox3D(BaseModel):
    min_corner: tuple[float, float, float]
    max_corner: tuple[float, float, float]
    dimensions: tuple[float, float, float]  # width (X), height (Y in glTF / Z in Blender), depth (Z/Y)
    center: tuple[float, float, float]
    diagonal: float


class MaterialSummary(BaseModel):
    name: str
    base_color: tuple[float, float, float, float]
    metallic: float
    roughness: float
    has_textures: bool = False
    texture_names: list[str] = Field(default_factory=list)


class RigSummary(BaseModel):
    has_armature: bool = False
    armature_name: str | None = None
    bone_count: int = 0
    bone_names: list[str] = Field(default_factory=list)
    root_bones: list[str] = Field(default_factory=list)
    skinned_mesh_count: int = 0
    normalized_weights_verified: bool = False
    max_influences_per_vertex: int = 0
    animation_clips: list[str] = Field(default_factory=list)


class MeshStats(BaseModel):
    actual_triangles: int
    actual_vertices: int
    gltf_render_vertices: int = 0
    polygon_faces: int = 0
    mesh_count: int
    material_count: int
    texture_count: int = 0
    connected_components: int = 1
    uv_layer_count: int = 0
    has_uvs: bool = False
    bounding_box: BoundingBox3D
    materials: list[MaterialSummary] = Field(default_factory=list)
    rig: RigSummary = Field(default_factory=RigSummary)


class ValidationCheckItem(BaseModel):
    check_id: str
    name: str
    passed: bool
    severity: Literal["info", "warning", "error"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    valid: bool
    passed_count: int
    warning_count: int
    error_count: int
    polygon_budget: int | None = None
    within_budget: bool = True
    reimport_verified: bool = False
    validator_backends: list[str] = Field(default_factory=list)
    checks: list[ValidationCheckItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CapabilityStatus(BaseModel):
    id: str
    name: str
    kind: Literal["blender_core", "blender_addon", "python_library"]
    available: bool
    verified: bool
    version: str | None = None
    license: str
    applicable_categories: list[AssetCategory]
    fallback_strategy: str
    status_message: str


class JobProgressEntry(BaseModel):
    timestamp: datetime
    stage: str
    progress_pct: int = Field(ge=0, le=100)
    message: str


class AssetRecord(BaseModel):
    id: str
    job_id: str
    name: str
    category: AssetCategory
    preset_id: str
    quality_profile: QualityProfile
    seed: int
    polygon_budget: int
    material_preset: str
    parameters: dict[str, Any]
    created_at: datetime
    glb_filename: str
    glb_size_bytes: int
    glb_download_url: str
    blend_filename: str | None = None
    blend_size_bytes: int | None = None
    blend_download_url: str | None = None
    metadata_download_url: str
    capabilities_used: list[str] = Field(default_factory=list)
    capabilities_fallback: list[str] = Field(default_factory=list)
    blender_version: str = ""
    generation_time_seconds: float = 0.0
    stats: MeshStats
    validation: ValidationReport


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    stage: str
    progress_pct: int = Field(ge=0, le=100)
    message: str = ""
    request: GenerateAssetRequest
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    asset_id: str | None = None
    error: str | None = None
    logs: list[JobProgressEntry] = Field(default_factory=list)
    external_run_url: str | None = None


class JobResultResponse(BaseModel):
    job: JobRecord
    asset: AssetRecord | None = None
