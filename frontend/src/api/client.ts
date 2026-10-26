import type {
  AssetCategory,
  AssetRecord,
  AssetTypeInfo,
  CapabilityStatus,
  GenerateAssetRequest,
  HealthStatus,
  JobRecord,
  MeshStats,
  ParameterOption,
  PresetInfo,
  ValidationReport,
} from "../types/studio";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export const MAX_VIEWER_GLB_BYTES = 80 * 1024 * 1024; // 80 MB safety cap in browser

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${clean}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveApiUrl(path), {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status} ${response.statusText}`;
    try {
      const errBody = await response.json();
      if (typeof errBody?.detail === "string") {
        detail = errBody.detail;
      } else if (Array.isArray(errBody?.detail)) {
        detail = errBody.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join("; ");
      }
    } catch {
      // keep status fallback
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function getHealth(): Promise<HealthStatus> {
  return fetchJson<HealthStatus>("/api/health");
}

export async function getCapabilities(refresh = false): Promise<{
  capabilities: CapabilityStatus[];
  category_plan: Record<string, { active: string[]; fallback: string[] }>;
}> {
  return fetchJson(`/api/capabilities${refresh ? "?refresh=true" : ""}`);
}

export async function getAssetTypesCatalog(): Promise<{
  types: AssetTypeInfo[];
  material_presets: ParameterOption[];
  quality_profiles: { id: string; label: string; description: string }[];
}> {
  return fetchJson("/api/assets/types");
}

export async function getPresets(category?: AssetCategory): Promise<PresetInfo[]> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return fetchJson<PresetInfo[]>(`/api/presets${q}`);
}

export async function submitGenerationJob(
  req: GenerateAssetRequest,
  apiKey?: string
): Promise<JobRecord> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey?.trim()) {
    headers["X-API-Key"] = apiKey.trim();
  }
  return fetchJson<JobRecord>("/api/generate", {
    method: "POST",
    headers,
    body: JSON.stringify(req),
  });
}

export async function getJob(jobId: string): Promise<JobRecord> {
  return fetchJson<JobRecord>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export async function getJobResult(jobId: string): Promise<{ job: JobRecord; asset: AssetRecord | null }> {
  return fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/result`);
}

export async function cancelJob(jobId: string): Promise<JobRecord> {
  return fetchJson<JobRecord>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export async function listAssets(category?: AssetCategory): Promise<AssetRecord[]> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return fetchJson<AssetRecord[]>(`/api/assets${q}`);
}

export async function getAsset(assetId: string): Promise<AssetRecord> {
  return fetchJson<AssetRecord>(`/api/assets/${encodeURIComponent(assetId)}`);
}

export async function validateUploadedGlb(
  file: File,
  polygonBudget?: number
): Promise<{
  filename: string;
  size_bytes: number;
  stats: MeshStats | null;
  validation: ValidationReport;
}> {
  const form = new FormData();
  form.append("file", file);
  const q = polygonBudget ? `?polygon_budget=${encodeURIComponent(String(polygonBudget))}` : "";
  return fetchJson(`/api/validate${q}`, {
    method: "POST",
    body: form,
  });
}

/**
 * Validate binary GLB magic bytes (`glTF` = 0x46546C67, version 2) and create a
 * revocable Object URL so Three.js GLTFLoader loads verified binary geometry.
 */
export async function fetchVerifiedGlbObjectUrl(
  downloadUrl: string,
  signal?: AbortSignal
): Promise<{ objectUrl: string; byteLength: number }> {
  const response = await fetch(resolveApiUrl(downloadUrl), { signal });
  if (!response.ok) {
    throw new Error(`Failed to fetch GLB binary (HTTP ${response.status}).`);
  }
  const buffer = await response.arrayBuffer();
  return createVerifiedGlbObjectUrlFromBuffer(buffer);
}

export function createVerifiedGlbObjectUrlFromBuffer(buffer: ArrayBuffer): {
  objectUrl: string;
  byteLength: number;
} {
  if (buffer.byteLength < 28) {
    throw new Error(`Malformed GLB file: truncated (${buffer.byteLength} bytes).`);
  }
  if (buffer.byteLength > MAX_VIEWER_GLB_BYTES) {
    throw new Error(
      `Oversized GLB (${(buffer.byteLength / (1024 * 1024)).toFixed(1)} MB) exceeds viewer limit (${MAX_VIEWER_GLB_BYTES / (1024 * 1024)} MB).`
    );
  }
  const view = new DataView(buffer);
  const magic = view.getUint32(0, true);
  const version = view.getUint32(4, true);
  const declaredLen = view.getUint32(8, true);

  if (magic !== 0x46546c67) {
    throw new Error(`Invalid GLB header magic (0x${magic.toString(16)}); expected 'glTF' (0x46546c67).`);
  }
  if (version !== 2) {
    throw new Error(`Unsupported glTF binary version ${version} (expected 2).`);
  }
  if (declaredLen !== buffer.byteLength) {
    throw new Error(
      `Corrupted GLB payload: header declares ${declaredLen} bytes, received ${buffer.byteLength} bytes.`
    );
  }

  const blob = new Blob([buffer], { type: "model/gltf-binary" });
  const objectUrl = URL.createObjectURL(blob);
  return { objectUrl, byteLength: buffer.byteLength };
}

/**
 * Subscribe to real-time SSE job updates with automatic graceful fallback to polling.
 */
export function subscribeToJobProgress(
  jobId: string,
  onUpdate: (job: JobRecord) => void,
  onError: (err: Error) => void
): () => void {
  let closed = false;
  let pollTimer: number | undefined;
  let eventSource: EventSource | undefined;

  const startPolling = () => {
    const tick = async () => {
      if (closed) return;
      try {
        const job = await getJob(jobId);
        if (closed) return;
        onUpdate(job);
        if (job.status === "queued" || job.status === "running") {
          pollTimer = window.setTimeout(tick, 900);
        }
      } catch (err) {
        if (!closed) {
          onError(err instanceof Error ? err : new Error(String(err)));
        }
      }
    };
    void tick();
  };

  if (typeof EventSource !== "undefined") {
    try {
      eventSource = new EventSource(resolveApiUrl(`/api/jobs/${encodeURIComponent(jobId)}/events`));
      eventSource.onmessage = (ev) => {
        if (closed) return;
        try {
          const parsed = JSON.parse(ev.data) as JobRecord;
          onUpdate(parsed);
          if (parsed.status === "completed" || parsed.status === "failed" || parsed.status === "cancelled") {
            eventSource?.close();
          }
        } catch {
          // ignore malformed event line
        }
      };
      eventSource.onerror = () => {
        eventSource?.close();
        if (!closed) {
          startPolling();
        }
      };
    } catch {
      startPolling();
    }
  } else {
    startPolling();
  }

  return () => {
    closed = true;
    eventSource?.close();
    if (pollTimer !== undefined) {
      window.clearTimeout(pollTimer);
    }
  };
}
