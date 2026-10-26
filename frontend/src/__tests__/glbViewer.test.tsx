import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { createVerifiedGlbObjectUrlFromBuffer } from "../api/client";
import App from "../App";

// Mock WebGL Viewport3D canvas in jsdom unit tests while keeping real Three.js GLTFLoader binary parsing tests!
vi.mock("@react-three/fiber", () => ({
  Canvas: () => <div data-testid="r3f-canvas-mock" />,
  useFrame: () => {},
  useThree: () => ({
    camera: new THREE.PerspectiveCamera(),
    gl: {},
    scene: new THREE.Scene(),
  }),
}));

vi.mock("@react-three/drei", () => ({
  Grid: () => null,
  OrbitControls: React.forwardRef(() => null),
}));

const FIXTURE_GLB_PATH = path.resolve(
  __dirname,
  "../../../tests/fixtures/real_blender_crate.glb"
);
const FIXTURE_META_PATH = path.resolve(
  __dirname,
  "../../../tests/fixtures/real_blender_crate_metadata.json"
);

describe("Real Blender GLB Loader & Studio UI Verification", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads and parses the real Blender-generated GLB fixture with Three.js GLTFLoader", async () => {
    expect(fs.existsSync(FIXTURE_GLB_PATH)).toBe(true);
    const nodeBuf = fs.readFileSync(FIXTURE_GLB_PATH);
    // Construct a jsdom-realm ArrayBuffer so `data instanceof ArrayBuffer` is true in GLTFLoader
    const copy = new Uint8Array(nodeBuf.byteLength);
    copy.set(nodeBuf);
    const arrayBuffer = copy.buffer;
    const meta = JSON.parse(fs.readFileSync(FIXTURE_META_PATH, "utf-8"));

    // 1. Verify our frontend binary header check accepts the real Blender GLB
    const { objectUrl, byteLength } = createVerifiedGlbObjectUrlFromBuffer(arrayBuffer);
    expect(byteLength).toBe(meta.glb_size_bytes);
    expect(objectUrl.startsWith("blob:")).toBe(true);
    URL.revokeObjectURL(objectUrl);

    // 2. Parse actual binary GLB using Three.js GLTFLoader (stubbing Image decode in headless jsdom)
    const loader = new GLTFLoader();
    const gltf = await new Promise<{ scene: THREE.Group }>((resolve, reject) => {
      // Patch THREE.ImageLoader in Node/jsdom so embedded PNG textures resolve cleanly without browser Image decode
      const origLoad = THREE.ImageLoader.prototype.load;
      THREE.ImageLoader.prototype.load = function (_url, onLoad) {
        const dummyImg = document.createElement("img");
        if (onLoad) setTimeout(() => onLoad(dummyImg), 0);
        return dummyImg;
      };
      loader.parse(
        arrayBuffer,
        "",
        (parsed) => {
          THREE.ImageLoader.prototype.load = origLoad;
          resolve(parsed);
        },
        (err) => {
          THREE.ImageLoader.prototype.load = origLoad;
          reject(err);
        }
      );
    });

    let meshCount = 0;
    let triangleCount = 0;
    const box = new THREE.Box3().setFromObject(gltf.scene);

    gltf.scene.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        meshCount += 1;
        const geom = (obj as THREE.Mesh).geometry;
        if (geom.index) {
          triangleCount += geom.index.count / 3;
        } else if (geom.attributes.position) {
          triangleCount += geom.attributes.position.count / 3;
        }
      }
    });

    expect(meshCount).toBeGreaterThanOrEqual(1);
    expect(triangleCount).toBe(meta.stats.actual_triangles);
    expect(box.isEmpty()).toBe(false);
  });

  it("rejects malformed or truncated GLB buffers with a clear error message", () => {
    const truncated = new Uint8Array([1, 2, 3, 4]).buffer;
    expect(() => createVerifiedGlbObjectUrlFromBuffer(truncated)).toThrow(/truncated/i);

    const wrongMagic = new Uint8Array(32);
    new DataView(wrongMagic.buffer).setUint32(0, 0xdeadbeef, true);
    expect(() => createVerifiedGlbObjectUrlFromBuffer(wrongMagic.buffer)).toThrow(
      /Invalid GLB header magic/i
    );
  });

  it("displays failed generation job errors honestly in the Studio UI and revokes blob URLs", async () => {
    const meta = JSON.parse(fs.readFileSync(FIXTURE_META_PATH, "utf-8"));
    const nodeBuf = fs.readFileSync(FIXTURE_GLB_PATH);
    const glbArrayBuffer = nodeBuf.buffer.slice(
      nodeBuf.byteOffset,
      nodeBuf.byteOffset + nodeBuf.byteLength
    );

    const revokeSpy = vi.spyOn(URL, "revokeObjectURL");

    const mockFetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/health")) {
        return new Response(
          JSON.stringify({
            status: "ok",
            service: "Procedural 3D Asset Generator Studio",
            version: "1.0.0",
            operating_mode: "live",
            github_dispatch_configured: false,
            blender_available: true,
            blender_version: "4.2.23 LTS",
            active_jobs: 0,
            queued_jobs: 0,
            capabilities_verified: 9,
            capabilities_total: 11,
          })
        );
      }
      if (url.includes("/api/assets/types")) {
        return new Response(
          JSON.stringify({
            types: [
              {
                category: "props",
                name: "Gameplay Props",
                description: "Props",
                icon: "box",
                godot_target_notes: "Centered pivot",
                default_budgets: {
                  prototype: { min_triangles: 200, target_triangles: 550, max_triangles: 1200 },
                  optimized_mid_poly: { min_triangles: 300, target_triangles: 1100, max_triangles: 2500 },
                  detailed_mid_poly: { min_triangles: 700, target_triangles: 2000, max_triangles: 6000 },
                },
                recommended_capabilities: ["blender_core"],
                parameter_specs: [],
              },
            ],
            material_presets: [{ value: "tactical_military", label: "Tactical Olive" }],
            quality_profiles: [{ id: "prototype", label: "Prototype", description: "Fast" }],
          })
        );
      }
      if (url.includes("/api/presets")) {
        return new Response(
          JSON.stringify([
            {
              id: "br_supply_crate",
              name: "Battle Royale Supply Crate",
              category: "props",
              description: "Airdrop crate",
              tags: ["loot"],
              quality_profile: "prototype",
              polygon_budget: 1100,
              material_preset: "tactical_military",
              parameters: {},
            },
          ])
        );
      }
      if (url.includes("/api/capabilities")) {
        return new Response(JSON.stringify({ capabilities: [], category_plan: {} }));
      }
      if (url.endsWith("/api/assets")) {
        return new Response(
          JSON.stringify([
            {
              ...meta,
              id: "ast_crate_1",
              created_at: new Date().toISOString(),
              glb_download_url: "/api/assets/ast_crate_1/download?format=glb",
              metadata_download_url: "/api/assets/ast_crate_1/download?format=metadata",
            },
          ])
        );
      }
      if (url.includes("/download?format=glb")) {
        return new Response(glbArrayBuffer, {
          status: 200,
          headers: { "Content-Type": "model/gltf-binary" },
        });
      }
      if (url.includes("/api/generate")) {
        return new Response(
          JSON.stringify({
            id: "job_fail_99",
            status: "failed",
            execution_mode: "live",
            stage: "failed",
            progress_pct: 40,
            message: "Simulated Blender failure",
            request: {
              category: "props",
              preset_id: "br_supply_crate",
              quality_profile: "prototype",
              seed: 42,
              material_preset: "tactical_military",
              save_blend: false,
              execution_mode: "live",
              parameters: {},
            },
            created_at: new Date().toISOString(),
            retry_count: 1,
            error: "Blender subprocess out of bounds during boolean test",
            logs: [],
          }),
          { status: 202 }
        );
      }
      if (url.includes("/api/jobs/job_fail_99")) {
        return new Response(
          JSON.stringify({
            id: "job_fail_99",
            status: "failed",
            execution_mode: "live",
            stage: "failed",
            progress_pct: 40,
            message: "Simulated Blender failure",
            request: {
              category: "props",
              preset_id: "br_supply_crate",
              quality_profile: "prototype",
              seed: 42,
              material_preset: "tactical_military",
              save_blend: false,
              execution_mode: "live",
              parameters: {},
            },
            created_at: new Date().toISOString(),
            retry_count: 1,
            error: "Blender subprocess out of bounds during boolean test",
            logs: [],
          })
        );
      }
      return new Response("Not Found", { status: 404 });
    });

    vi.stubGlobal("fetch", mockFetch);

    const { unmount } = render(<App />);

    // Wait for initial asset stats to render from real metadata
    await waitFor(() => {
      expect(screen.getByTestId("actual-triangles")).toHaveTextContent(
        meta.stats.actual_triangles.toLocaleString()
      );
    });

    // Trigger a generation job that fails and verify error banner appears honestly
    fireEvent.click(screen.getByTestId("generate-btn"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /Blender subprocess out of bounds during boolean test/i
      );
    });

    unmount();
    expect(revokeSpy).toHaveBeenCalled();
  });
});
