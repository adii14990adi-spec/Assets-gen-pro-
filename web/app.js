/* Assets Gen Pro — front-end controller.
 * All API calls use relative URLs so the app works behind any host/proxy.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = { kinds: [], kind: null, params: {}, swatches: [], seed: "aurora" };
  let currentSvg = "";

  const els = {
    kinds: $("kinds"),
    kindDesc: $("kind-desc"),
    seed: $("seed"),
    dice: $("dice"),
    palette: $("palette"),
    size: $("size"),
    params: $("params"),
    asset: $("asset"),
    status: $("status"),
    pill: $("kind-pill"),
    meta: $("preview-meta"),
    swatches: $("swatches"),
    snippet: $("snippet"),
    batch: $("batch"),
    batchBtn: $("batch-btn"),
    copy: $("copy"),
    dlSvg: $("dl-svg"),
    dlPng: $("dl-png"),
  };

  const setStatus = (message, isError = false) => {
    els.status.textContent = message || "";
    els.status.classList.toggle("error", Boolean(isError));
  };

  const query = () => {
    const url = new URLSearchParams();
    url.set("kind", state.kind);
    url.set("seed", state.seed || "demo");
    url.set("size", els.size.value);
    url.set("palette", els.palette.value);
    for (const [key, value] of Object.entries(state.params)) {
      if (value !== "" && value !== null && value !== undefined) {
        url.set(key, String(value));
      }
    }
    return url;
  };

  const assetUrl = () => {
    const url = new URL("api/asset.svg", document.baseURI);
    url.search = query().toString();
    return url.href;
  };

  /* ---------------- rendering ---------------- */

  const renderKinds = () => {
    els.kinds.textContent = "";
    state.kinds.forEach((kind) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = kind.label;
      button.dataset.kind = kind.id;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(kind.id === state.kind));
      button.addEventListener("click", () => selectKind(kind.id));
      els.kinds.append(button);
    });
  };

  const renderParams = () => {
    const kind = state.kinds.find((item) => item.id === state.kind);
    els.params.textContent = "";
    state.params = {};
    if (!kind) return;

    els.kindDesc.textContent = kind.description;

    kind.params.forEach((spec) => {
      state.params[spec.name] = spec.default;
      const wrap = document.createElement("div");
      wrap.className = "param";

      if (spec.type === "bool") {
        const label = document.createElement("label");
        label.className = "switch";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(spec.default);
        input.addEventListener("change", () => {
          state.params[spec.name] = input.checked;
          update();
        });
        label.append(input, document.createTextNode(spec.label));
        wrap.append(label);
        els.params.append(wrap);
        return;
      }

      if (spec.type === "int") {
        const head = document.createElement("div");
        head.className = "param-head";
        const label = document.createElement("label");
        label.textContent = spec.label;
        const value = document.createElement("span");
        value.textContent = String(spec.default);
        head.append(label, value);

        const input = document.createElement("input");
        input.type = "range";
        input.min = String(spec.min ?? 0);
        input.max = String(spec.max ?? 10);
        input.step = "1";
        input.value = String(spec.default);
        input.setAttribute("aria-label", spec.label);
        input.addEventListener("input", () => {
          value.textContent = input.value;
          state.params[spec.name] = Number(input.value);
          updateSoon();
        });

        wrap.append(head, input);
        els.params.append(wrap);
        return;
      }

      const label = document.createElement("label");
      label.textContent = spec.label;
      label.htmlFor = `param-${spec.name}`;
      wrap.append(label);

      let input;
      if (spec.type === "choice") {
        input = document.createElement("select");
        spec.choices.forEach((choice) => {
          const option = document.createElement("option");
          option.value = choice;
          option.textContent = choice;
          input.append(option);
        });
        input.value = spec.default;
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.value = spec.default ?? "";
        input.placeholder = spec.help || "";
        input.maxLength = spec.max_length ?? 32;
        input.autocomplete = "off";
      }
      input.id = `param-${spec.name}`;
      input.addEventListener("input", () => {
        state.params[spec.name] = input.value;
        updateSoon();
      });
      input.addEventListener("change", () => {
        state.params[spec.name] = input.value;
        update();
      });
      wrap.append(input);
      els.params.append(wrap);
    });
  };

  const renderSnippet = () => {
    const url = assetUrl();
    const rel = url.replace(/^https?:\/\/[^/]+/, "");
    els.snippet.textContent = `<img src="${rel}" alt="Generated asset" width="400" height="400" />`;
  };

  const renderPreview = () => {
    if (!state.kind) return;
    els.pill.textContent = state.kind;
    els.meta.textContent = `${els.size.value} × ${els.size.value} · ${els.palette.value}`;
    els.asset.src = assetUrl();
    els.asset.alt = `${state.kind} asset generated from seed ${state.seed}`;
    renderSnippet();
  };

  /* ---------------- data loading ---------------- */

  const loadSvgSource = async () => {
    try {
      const response = await fetch(assetUrl(), { headers: { Accept: "image/svg+xml" } });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `Request failed (${response.status})`);
      }
      currentSvg = await response.text();
      renderSwatches();
      setStatus("");
    } catch (error) {
      setStatus(error.message, true);
    }
  };

  const renderSwatches = () => {
    const fills = new Set();
    const pattern = /(?:fill|stop-color)="(#[0-9a-fA-F]{6})"/g;
    let match;
    while ((match = pattern.exec(currentSvg)) && fills.size < 8) {
      fills.add(match[1].toLowerCase());
    }
    els.swatches.textContent = "";
    [...fills].slice(0, 8).forEach((colour) => {
      const chip = document.createElement("i");
      chip.style.background = colour;
      chip.title = colour;
      els.swatches.append(chip);
    });
  };

  let updateTimer = 0;
  const update = () => {
    renderPreview();
    loadSvgSource();
  };

  // Typing and dragging fire rapidly; debounce the network round trip only.
  const updateSoon = () => {
    renderPreview();
    window.clearTimeout(updateTimer);
    updateTimer = window.setTimeout(loadSvgSource, 180);
  };

  const selectKind = (id) => {
    state.kind = id;
    [...els.kinds.children].forEach((button) => {
      button.setAttribute("aria-selected", String(button.dataset.kind === id));
    });
    renderParams();
    els.batch.textContent = "";
    update();
  };

  /* ---------------- actions ---------------- */

  const download = (href, filename) => {
    const link = document.createElement("a");
    link.href = href;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
  };

  const slug = () => `${state.kind}-${(state.seed || "demo").slice(0, 24)}`;

  els.copy.addEventListener("click", async () => {
    if (!currentSvg) return setStatus("Nothing to copy yet.", true);
    try {
      await navigator.clipboard.writeText(currentSvg);
      setStatus("SVG markup copied to clipboard.");
    } catch {
      setStatus("Clipboard blocked — use the SVG download instead.", true);
    }
  });

  els.dlSvg.addEventListener("click", () => {
    if (!currentSvg) return;
    const blob = new Blob([currentSvg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    download(url, `${slug()}.svg`);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    setStatus("SVG downloaded.");
  });

  els.dlPng.addEventListener("click", () => {
    if (!currentSvg) return;
    const size = Number(els.size.value);
    const image = new Image();
    const blobUrl = URL.createObjectURL(new Blob([currentSvg], { type: "image/svg+xml" }));
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0, size, size);
      canvas.toBlob((blob) => {
        if (!blob) return setStatus("PNG export failed.", true);
        const url = URL.createObjectURL(blob);
        download(url, `${slug()}.png`);
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        setStatus(`PNG exported at ${size} × ${size}.`);
      }, "image/png");
      URL.revokeObjectURL(blobUrl);
    };
    image.onerror = () => {
      URL.revokeObjectURL(blobUrl);
      setStatus("PNG export failed.", true);
    };
    image.src = blobUrl;
  });

  els.dice.addEventListener("click", async () => {
    try {
      const response = await fetch("api/seed");
      if (response.ok) {
        const data = await response.json();
        els.seed.value = data.seed;
      } else {
        throw new Error("fallback");
      }
    } catch {
      els.seed.value = Math.random().toString(36).slice(2, 12);
    }
    state.seed = els.seed.value;
    update();
  });

  els.batchBtn.addEventListener("click", async () => {
    els.batch.textContent = "";
    const url = new URL("api/batch.json", document.baseURI);
    url.search = new URLSearchParams({
      kind: state.kind,
      seed: state.seed || "demo",
      count: "8",
      size: "200",
      palette: els.palette.value,
    }).toString();
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Batch request failed");
      const data = await response.json();
      data.items.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.title = `Use seed ${item.seed}`;
        const img = document.createElement("img");
        img.src = item.url;
        img.alt = `Variation ${item.seed}`;
        img.loading = "lazy";
        button.append(img);
        button.addEventListener("click", () => {
          els.seed.value = item.seed;
          state.seed = item.seed;
          update();
        });
        els.batch.append(button);
      });
      setStatus(`Generated ${data.items.length} variations.`);
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  els.seed.addEventListener("input", () => {
    state.seed = els.seed.value.trim();
    updateSoon();
  });

  [els.palette, els.size].forEach((element) => {
    element.addEventListener("change", update);
  });

  /* ---------------- boot ---------------- */

  const boot = async () => {
    try {
      const response = await fetch("api/kinds");
      if (!response.ok) throw new Error(`Could not load kinds (${response.status})`);
      const data = await response.json();
      state.kinds = data.kinds;
      state.kind = state.kinds[0]?.id ?? null;

      const palettes = ["vivid", "pastel", "neon", "mono", "earth"];
      els.palette.textContent = "";
      palettes.forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        els.palette.append(option);
      });

      renderKinds();
      renderParams();
      update();
    } catch (error) {
      setStatus(error.message, true);
    }
  };

  boot();
})();
