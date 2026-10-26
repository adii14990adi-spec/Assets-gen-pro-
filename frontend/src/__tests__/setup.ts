import "@testing-library/jest-dom";

// Polyfill ResizeObserver for jsdom
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

let blobCounter = 0;
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = () => `blob:http://localhost/test-glb-${++blobCounter}`;
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = () => {};
}
