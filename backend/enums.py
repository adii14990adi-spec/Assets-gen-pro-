"""Zero-dependency shared enums safe to import inside both FastAPI and vanilla Blender Python."""

from __future__ import annotations

from enum import Enum


class AssetCategory(str, Enum):
    HUMANOID = "humanoid"
    ARCHITECTURE = "architecture"
    ENVIRONMENT = "environment"
    PROPS = "props"


class QualityProfile(str, Enum):
    PROTOTYPE = "prototype"
    OPTIMIZED_MID_POLY = "optimized_mid_poly"
    DETAILED_MID_POLY = "detailed_mid_poly"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(str, Enum):
    LIVE = "live"
    GITHUB_ACTIONS = "github_actions"
