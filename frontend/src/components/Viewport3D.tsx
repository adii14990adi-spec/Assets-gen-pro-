import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader, type GLTF } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import {
  Box,
  Compass,
  Expand,
  Eye,
  Grid3X3,
  Layers,
  Loader2,
  Minimize,
  AlertTriangle,
  Play,
  Pause,
  RotateCcw,
  Bone,
} from "lucide-react";
import type { CameraViewPreset, ViewportShadingMode } from "../types/studio";

export interface BackgroundPreset {
  id: string;
  label: string;
  color: string;
  gridCell: string;
  gridSection: string;
}

export const STUDIO_BACKGROUNDS: BackgroundPreset[] = [
  { id: "slate", label: "Studio Slate", color: "#151922", gridCell: "#283040", gridSection: "#3d4b66" },
  { id: "obsidian", label: "Obsidian Dark", color: "#0b0d12", gridCell: "#1d222e", gridSection: "#333d52" },
  { id: "rajasthan_dusk", label: "Jaipur Dusk", color: "#231920", gridCell: "#3e2c37", gridSection: "#6e4b58" },
  { id: "neutral", label: "Neutral Clay", color: "#343840", gridCell: "#4b515c", gridSection: "#697282" },
  { id: "daylight", label: "Daylight Mist", color: "#cfd8e3", gridCell: "#aebbc9", gridSection: "#7c8fa6" },
];

interface Viewport3DProps {
  glbObjectUrl: string | null;
  assetTitle: string | null;
  isGenerating: boolean;
  generationProgressPct: number;
  generationStageText: string;
  externalError: string | null;
  hasRig?: boolean;
}

function ProceduralStudioEnvironment() {
  const { gl, scene } = useThree();
  useEffect(() => {
    if (!gl || typeof gl.compile !== "function") return undefined;
    const pmrem = new THREE.PMREMGenerator(gl);
    pmrem.compileEquirectangularShader();
    const envScene = new RoomEnvironment();
    const envRT = pmrem.fromScene(envScene, 0.04);
    scene.environment = envRT.texture;
    return () => {
      scene.environment = null;
      envRT.dispose();
      envScene.dispose();
      pmrem.dispose();
    };
  }, [gl, scene]);
  return null;
}

interface LoadedModelSceneProps {
  gltf: GLTF;
  shadingMode: ViewportShadingMode;
  showSkeleton: boolean;
  playAnimation: boolean;
}

function LoadedModelScene({ gltf, shadingMode, showSkeleton, playAnimation }: LoadedModelSceneProps) {
  const mixerRef = useRef<THREE.AnimationMixer | null>(null);
  const originalMaterialsRef = useRef<Map<string, THREE.Material | THREE.Material[]>>(new Map());

  const clayMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color("#b9c2cf"),
        roughness: 0.52,
        metalness: 0.06,
      }),
    []
  );

  const wireMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color("#60a5fa"),
        roughness: 0.4,
        metalness: 0.1,
        wireframe: true,
      }),
    []
  );

  useEffect(() => {
    const map = new Map<string, THREE.Material | THREE.Material[]>();
    gltf.scene.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        map.set(mesh.uuid, mesh.material);
      }
    });
    originalMaterialsRef.current = map;

    return () => {
      clayMaterial.dispose();
      wireMaterial.dispose();
    };
  }, [gltf, clayMaterial, wireMaterial]);

  useEffect(() => {
    gltf.scene.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        const orig = originalMaterialsRef.current.get(mesh.uuid);
        if (shadingMode === "solid") {
          mesh.material = clayMaterial;
        } else if (shadingMode === "wireframe") {
          mesh.material = wireMaterial;
        } else if (orig) {
          mesh.material = orig;
        }
      }
    });
  }, [gltf, shadingMode, clayMaterial, wireMaterial]);

  const skeletonHelper = useMemo(() => {
    if (!showSkeleton) return null;
    const helper = new THREE.SkeletonHelper(gltf.scene);
    return helper;
  }, [gltf, showSkeleton]);

  useEffect(() => {
    if (gltf.animations && gltf.animations.length > 0) {
      const mixer = new THREE.AnimationMixer(gltf.scene);
      mixerRef.current = mixer;
      const action = mixer.clipAction(gltf.animations[0]);
      if (playAnimation) {
        action.play();
      }
      return () => {
        mixer.stopAllAction();
        mixerRef.current = null;
      };
    }
    return undefined;
  }, [gltf, playAnimation]);

  useFrame((_, delta) => {
    if (playAnimation && mixerRef.current) {
      mixerRef.current.update(delta);
    }
  });

  return (
    <group>
      <primitive object={gltf.scene} />
      {skeletonHelper && <primitive object={skeletonHelper} />}
    </group>
  );
}

interface CameraRigControllerProps {
  bounds: { center: THREE.Vector3; radius: number } | null;
  viewRequest: { preset: CameraViewPreset; nonce: number };
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
}

function CameraRigController({ bounds, viewRequest, controlsRef }: CameraRigControllerProps) {
  const { camera } = useThree();

  useEffect(() => {
    const center = bounds ? bounds.center : new THREE.Vector3(0, 0.9, 0);
    const r = bounds ? Math.max(0.8, bounds.radius) : 2.5;
    const dist = r * 2.35;

    const pos = new THREE.Vector3();
    switch (viewRequest.preset) {
      case "front":
        pos.set(center.x, center.y + r * 0.12, center.z + dist);
        break;
      case "rear":
        pos.set(center.x, center.y + r * 0.12, center.z - dist);
        break;
      case "left":
        pos.set(center.x - dist, center.y + r * 0.12, center.z);
        break;
      case "right":
        pos.set(center.x + dist, center.y + r * 0.12, center.z);
        break;
      case "top":
        pos.set(center.x, center.y + dist * 1.15, center.z + 0.001);
        break;
      case "perspective":
      default:
        pos.set(center.x + dist * 0.72, center.y + dist * 0.52, center.z + dist * 0.78);
        break;
    }

    camera.position.copy(pos);
    camera.near = Math.max(0.01, r * 0.005);
    camera.far = Math.max(500, r * 60);
    camera.updateProjectionMatrix();

    if (controlsRef.current) {
      controlsRef.current.target.copy(center);
      controlsRef.current.update();
    } else {
      camera.lookAt(center);
    }
  }, [bounds, viewRequest, camera, controlsRef]);

  return null;
}

export const Viewport3D: React.FC<Viewport3DProps> = ({
  glbObjectUrl,
  assetTitle,
  isGenerating,
  generationProgressPct,
  generationStageText,
  externalError,
  hasRig = false,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const controlsRef = useRef<OrbitControlsImpl | null>(null);

  const [gltf, setGltf] = useState<GLTF | null>(null);
  const [isLoadingGlb, setIsLoadingGlb] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [bounds, setBounds] = useState<{ center: THREE.Vector3; radius: number } | null>(null);

  const [shadingMode, setShadingMode] = useState<ViewportShadingMode>("material");
  const [showGrid, setShowGrid] = useState(true);
  const [showAxes, setShowAxes] = useState(true);
  const [showSkeleton, setShowSkeleton] = useState(false);
  const [playAnimation, setPlayAnimation] = useState(true);
  const [bgIndex, setBgIndex] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [viewRequest, setViewRequest] = useState<{ preset: CameraViewPreset; nonce: number }>({
    preset: "perspective",
    nonce: 0,
  });

  const activeBg = STUDIO_BACKGROUNDS[bgIndex] || STUDIO_BACKGROUNDS[0];

  useEffect(() => {
    if (!glbObjectUrl) {
      setGltf(null);
      setBounds(null);
      setLoadError(null);
      return;
    }

    let cancelled = false;
    setIsLoadingGlb(true);
    setLoadError(null);

    const loader = new GLTFLoader();
    loader.load(
      glbObjectUrl,
      (loaded) => {
        if (cancelled) return;
        const box = new THREE.Box3().setFromObject(loaded.scene);
        const sphere = new THREE.Sphere();
        if (!box.isEmpty()) {
          box.getBoundingSphere(sphere);
        } else {
          sphere.center.set(0, 0.8, 0);
          sphere.radius = 1.5;
        }
        setGltf(loaded);
        setBounds({ center: sphere.center.clone(), radius: Math.max(0.35, sphere.radius) });
        setViewRequest((prev) => ({ preset: "perspective", nonce: prev.nonce + 1 }));
        setIsLoadingGlb(false);
      },
      undefined,
      (err) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "Failed to parse GLB geometry in Three.js.";
        setLoadError(msg);
        setGltf(null);
        setIsLoadingGlb(false);
      }
    );

    return () => {
      cancelled = true;
    };
  }, [glbObjectUrl]);

  useEffect(() => {
    const onFsChange = () => {
      setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const triggerCameraView = useCallback((preset: CameraViewPreset) => {
    setViewRequest((prev) => ({ preset, nonce: prev.nonce + 1 }));
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await containerRef.current.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch {
      // Fullscreen may be restricted in embedded iframes; toggle maximized CSS fallback
      setIsFullscreen((v) => !v);
    }
  }, []);

  const combinedError = externalError || loadError;
  const hasAnimations = Boolean(gltf && gltf.animations && gltf.animations.length > 0);

  return (
    <div
      ref={containerRef}
      className={`viewport-shell ${isFullscreen ? "viewport-fullscreen" : ""}`}
      style={{ backgroundColor: activeBg.color }}
      data-testid="viewport-3d"
    >
      {/* Top Floating Viewport Toolbar */}
      <div className="viewport-toolbar-top">
        <div className="toolbar-group" role="group" aria-label="Shading Modes">
          <button
            type="button"
            className={`vp-btn ${shadingMode === "material" ? "active" : ""}`}
            onClick={() => setShadingMode("material")}
            title="PBR Material & Texture View"
          >
            <Eye size={14} />
            <span>Material</span>
          </button>
          <button
            type="button"
            className={`vp-btn ${shadingMode === "solid" ? "active" : ""}`}
            onClick={() => setShadingMode("solid")}
            title="Solid Studio Clay View"
          >
            <Box size={14} />
            <span>Solid</span>
          </button>
          <button
            type="button"
            className={`vp-btn ${shadingMode === "wireframe" ? "active" : ""}`}
            onClick={() => setShadingMode("wireframe")}
            title="Topology Wireframe View"
          >
            <Layers size={14} />
            <span>Wireframe</span>
          </button>
        </div>

        <div className="toolbar-group" role="group" aria-label="Camera Presets">
          {(["perspective", "front", "rear", "left", "right", "top"] as CameraViewPreset[]).map((cam) => (
            <button
              key={cam}
              type="button"
              className={`vp-btn ${viewRequest.preset === cam ? "active" : ""}`}
              onClick={() => triggerCameraView(cam)}
              title={`${cam.toUpperCase()} Camera`}
            >
              {cam === "perspective" ? "Persp" : cam.charAt(0).toUpperCase() + cam.slice(1)}
            </button>
          ))}
          <button
            type="button"
            className="vp-btn"
            onClick={() => triggerCameraView("perspective")}
            title="Frame & Reset Camera"
          >
            <RotateCcw size={14} />
          </button>
        </div>

        <div className="toolbar-group" role="group" aria-label="Viewport Helpers">
          <button
            type="button"
            className={`vp-btn ${showGrid ? "active" : ""}`}
            onClick={() => setShowGrid((v) => !v)}
            title="Toggle Metric Floor Grid (1m)"
          >
            <Grid3X3 size={14} />
          </button>
          <button
            type="button"
            className={`vp-btn ${showAxes ? "active" : ""}`}
            onClick={() => setShowAxes((v) => !v)}
            title="Toggle XYZ Coordinate Axes"
          >
            <Compass size={14} />
          </button>
          {hasRig && (
            <button
              type="button"
              className={`vp-btn ${showSkeleton ? "active" : ""}`}
              onClick={() => setShowSkeleton((v) => !v)}
              title="Toggle Armature Skeleton Helper"
            >
              <Bone size={14} />
              <span>Rig</span>
            </button>
          )}
          {hasAnimations && (
            <button
              type="button"
              className={`vp-btn ${playAnimation ? "active" : ""}`}
              onClick={() => setPlayAnimation((v) => !v)}
              title="Play / Pause Exported glTF Animation"
            >
              {playAnimation ? <Pause size={14} /> : <Play size={14} />}
            </button>
          )}
          <select
            className="vp-select"
            aria-label="Viewport Background"
            value={bgIndex}
            onChange={(e) => setBgIndex(Number(e.target.value))}
          >
            {STUDIO_BACKGROUNDS.map((b, idx) => (
              <option key={b.id} value={idx}>
                {b.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="vp-btn"
            onClick={toggleFullscreen}
            title="Toggle Fullscreen Viewport"
          >
            {isFullscreen ? <Minimize size={14} /> : <Expand size={14} />}
          </button>
        </div>
      </div>

      {/* Three.js / React Three Fiber Interactive Canvas */}
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ fov: 42, near: 0.05, far: 1000, position: [4, 3, 5] }}
      >
        <color attach="background" args={[activeBg.color]} />
        <ProceduralStudioEnvironment />

        <hemisphereLight args={["#f8fafc", "#334155", 0.55]} />
        <directionalLight
          position={[8, 14, 9]}
          intensity={1.35}
          castShadow
          shadow-mapSize={[1024, 1024]}
        />
        <directionalLight position={[-9, 6, -7]} intensity={0.45} color="#93c5fd" />

        {showGrid && (
          <Grid
            position={[0, -0.002, 0]}
            args={[60, 60]}
            cellSize={1}
            cellThickness={0.6}
            cellColor={activeBg.gridCell}
            sectionSize={5}
            sectionThickness={1.2}
            sectionColor={activeBg.gridSection}
            fadeDistance={55}
            fadeStrength={1}
            infiniteGrid
          />
        )}

        {showAxes && <axesHelper args={[Math.max(1.5, (bounds?.radius || 1.5) * 0.9)]} />}

        {gltf && (
          <LoadedModelScene
            gltf={gltf}
            shadingMode={shadingMode}
            showSkeleton={showSkeleton}
            playAnimation={playAnimation}
          />
        )}

        <OrbitControls
          ref={controlsRef}
          makeDefault
          enableDamping
          dampingFactor={0.08}
          minDistance={0.15}
          maxDistance={250}
        />

        <CameraRigController
          bounds={bounds}
          viewRequest={viewRequest}
          controlsRef={controlsRef}
        />
      </Canvas>

      {/* Empty State when no asset is loaded yet */}
      {!gltf && !isGenerating && !isLoadingGlb && !combinedError && (
        <div className="viewport-overlay-card">
          <Box size={34} className="accent-icon" />
          <h3>Procedural 3D Viewport Ready</h3>
          <p>
            Select a category &amp; preset on the left and click <strong>Generate 3D Asset</strong>, or
            reopen an asset from the Library to inspect its real Blender-generated GLB model.
          </p>
        </div>
      )}

      {/* Active Blender Generation / GLB Loading Overlay */}
      {(isGenerating || isLoadingGlb) && (
        <div className="viewport-overlay-card loading">
          <Loader2 size={30} className="spin accent-icon" />
          <h3>{isGenerating ? "Blender 4.2 Generating Geometry..." : "Loading Verified GLB..."}</h3>
          <p>{isGenerating ? generationStageText : "Streaming binary glTF 2.0 into Three.js viewport..."}</p>
          {isGenerating && (
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${Math.max(5, generationProgressPct)}%` }} />
            </div>
          )}
        </div>
      )}

      {/* Error State Banner */}
      {combinedError && !isGenerating && (
        <div className="viewport-error-banner" role="alert">
          <AlertTriangle size={18} />
          <div>
            <strong>3D Asset Error:</strong> {combinedError}
          </div>
        </div>
      )}

      {/* Bottom Viewport Status Bar */}
      <div className="viewport-statusbar">
        <span>
          {assetTitle ? (
            <>
              Loaded GLB: <strong>{assetTitle}</strong>
            </>
          ) : (
            "No GLB loaded"
          )}
        </span>
        <span>LMB: Orbit 360° · RMB: Pan · Scroll: Zoom · Units: Meters (Godot 4 glTF +Y Up)</span>
      </div>
    </div>
  );
};
