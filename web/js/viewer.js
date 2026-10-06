// Canvas viewer for a SkyShift sequence: blink, slider and difference modes with an asinh stretch.
//
// Frames are n*n Float32Arrays, row 0 at the bottom (south), NaN = no data. Pixel coordinates used
// by overlays and clicks are the backend's grid pixels: (0, 0) is the centre of the bottom-left pixel.

const NO_DATA = [16, 21, 34];

function robustStats(data) {
  const vals = [];
  for (let i = 0; i < data.length; i += 1) if (Number.isFinite(data[i])) vals.push(data[i]);
  if (!vals.length) return { med: 0, sig: 1 };
  vals.sort((a, b) => a - b);
  const med = vals[vals.length >> 1];
  const dev = vals.map((v) => Math.abs(v - med)).sort((a, b) => a - b);
  return { med, sig: 1.4826 * dev[dev.length >> 1] || 1 };
}

export class Viewer {
  constructor(host, { onClick } = {}) {
    this.host = host;
    this.data = document.createElement("canvas");
    this.data.className = "data";
    this.overlay = document.createElement("canvas");
    this.overlay.className = "overlay";
    host.append(this.data, this.overlay);
    this.onClick = onClick;
    this.mode = "blink";
    this.contrast = 40;      // white point, in units of the background noise
    this.balance = false;    // normalise each frame on its own noise (for mixed wavelengths)
    this.showKnown = true;
    this.fps = 2;
    this.playing = true;
    this.split = 0.5;        // slider position
    this.reset(0, []);

    this.overlay.addEventListener("click", (e) => {
      if (this.mode === "slider" || !this.onClick || !this.n) return;
      const r = this.overlay.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * this.n - 0.5;
      const y = (1 - (e.clientY - r.top) / r.height) * this.n - 0.5;
      this.onClick({ x, y, frame: this.index });
    });
    let dragging = false;
    const drag = (e) => {
      if (!dragging || this.mode !== "slider") return;
      const r = this.overlay.getBoundingClientRect();
      this.split = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      this.draw();
    };
    this.overlay.addEventListener("pointerdown", (e) => { dragging = true; drag(e); });
    window.addEventListener("pointermove", drag);
    window.addEventListener("pointerup", () => { dragging = false; });
    new ResizeObserver(() => this.draw()).observe(host);
    this.tick = this.tick.bind(this);
    requestAnimationFrame(this.tick);
  }

  reset(n, entries) {
    this.n = n;
    this.entries = entries;
    this.frames = entries.map(() => null);
    this.stats = entries.map(() => null);
    this.failed = new Set();
    this.index = 0;
    this.template = null;
    this.known = [];
    this.markers = [];
    this.lastStep = 0;
    this.draw();
  }

  setFrame(i, data) {
    if (data === null) this.failed.add(i);
    else {
      this.frames[i] = data;
      this.stats[i] = robustStats(data);
    }
    this.template = null;
    if (this.readyCount() === 1 && data) this.index = i;
    this.draw();
  }

  readyCount() { return this.frames.filter(Boolean).length; }
  readyIndices() { return this.frames.map((f, i) => (f ? i : -1)).filter((i) => i >= 0); }

  // Per-pixel median of normalised frames: "what this patch usually looks like".
  buildTemplate() {
    const idx = this.readyIndices();
    if (!idx.length) return null;
    const n2 = this.n * this.n;
    const out = new Float32Array(n2);
    const col = new Float32Array(idx.length);
    for (let p = 0; p < n2; p += 1) {
      let k = 0;
      for (const i of idx) {
        const v = this.norm(i, this.frames[i][p]);
        if (Number.isFinite(v)) col[k++] = v;
      }
      if (!k) { out[p] = NaN; continue; }
      const s = col.subarray(0, k).sort();
      out[p] = s[k >> 1];
    }
    this.template = out;
    return out;
  }

  // Pixel value in noise units. Without balance, every frame uses the first ready frame's scale,
  // so real brightness changes survive.
  norm(i, v) {
    const ref = this.balance ? this.stats[i] : this.stats[this.readyIndices()[0]];
    const own = this.stats[i];
    return (v - own.med) / ref.sig;
  }

  step(d) {
    const idx = this.readyIndices();
    if (!idx.length) return;
    const pos = idx.indexOf(this.index);
    this.index = idx[(pos + d + idx.length) % idx.length];
    this.draw();
    this.onStep?.(this.index);
  }

  goto(i) {
    if (!this.frames[i]) return;
    this.index = i;
    this.draw();
    this.onStep?.(i);
  }

  tick(t) {
    if (this.playing && this.mode !== "slider" && this.readyCount() > 1 && t - this.lastStep > 1000 / this.fps) {
      this.lastStep = t;
      this.step(1);
    }
    requestAnimationFrame(this.tick);
  }

  stretch(z) {
    const a = 3;
    const lo = Math.asinh(-2 / a);
    const hi = Math.asinh(this.contrast / a);
    return Math.min(1, Math.max(0, (Math.asinh(z / a) - lo) / (hi - lo)));
  }

  draw() {
    const { n } = this;
    const px = Math.round(this.host.clientWidth * (window.devicePixelRatio || 1));
    for (const c of [this.data, this.overlay]) {
      if (c.width !== px) { c.width = px; c.height = px; }
    }
    const ctx = this.data.getContext("2d");
    ctx.clearRect(0, 0, px, px);
    this.overlay.getContext("2d").clearRect(0, 0, px, px);
    if (!n || !this.frames[this.index]) return;

    const img = new ImageData(n, n);
    const cur = this.frames[this.index];
    const first = this.frames[this.readyIndices()[0]];
    if (this.mode === "diff" && !this.template) this.buildTemplate();
    const brightCut = 60; // template pixels brighter than this many sigma: likely false-change residuals

    for (let row = 0; row < n; row += 1) {
      for (let col = 0; col < n; col += 1) {
        const p = row * n + col;
        const o = ((n - 1 - row) * n + col) * 4; // flip: row 0 is south (bottom)
        let rgb;
        if (this.mode === "diff") {
          const z = this.norm(this.index, cur[p]) - this.template[p];
          if (!Number.isFinite(z)) rgb = NO_DATA;
          else {
            // 2.5-sigma dead zone keeps noise dark so real changes stand out.
            const mag = Math.max(0, Math.abs(z) - 2.5) / Math.max(4, this.contrast / 5);
            const t = Math.sign(z) * Math.min(1, mag);
            const dim = this.template[p] > brightCut ? 0.35 : 1;
            rgb = t >= 0
              ? [255 * t * dim + 18, 181 * t * dim + 18, 71 * t * dim + 24]
              : [72 * -t * dim + 18, 166 * -t * dim + 18, 255 * -t * dim + 24];
          }
        } else {
          const src = this.mode === "slider" && col / n < this.split ? first : cur;
          const i = src === first ? this.readyIndices()[0] : this.index;
          const v = src[p];
          if (!Number.isFinite(v)) rgb = NO_DATA;
          else {
            const g = 255 * this.stretch(this.norm(i, v));
            rgb = [g, g, Math.min(255, g * 1.04 + 4)];
          }
        }
        img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = 255;
      }
    }
    const tmp = new OffscreenCanvas(n, n);
    tmp.getContext("2d").putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(tmp, 0, 0, px, px);
    this.drawOverlay(px);
  }

  toCanvas(x, y, px) {
    const s = px / this.n;
    return [(x + 0.5) * s, (this.n - 0.5 - y) * s];
  }

  drawOverlay(px) {
    const g = this.overlay.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    g.lineWidth = 1.5 * dpr;
    g.font = `${12 * dpr}px system-ui, sans-serif`;
    // target crosshair
    const [cx, cy] = [px / 2, px / 2];
    g.strokeStyle = "#ffffff55";
    g.beginPath();
    g.moveTo(cx - 14 * dpr, cy); g.lineTo(cx - 6 * dpr, cy);
    g.moveTo(cx + 6 * dpr, cy); g.lineTo(cx + 14 * dpr, cy);
    g.moveTo(cx, cy - 14 * dpr); g.lineTo(cx, cy - 6 * dpr);
    g.moveTo(cx, cy + 6 * dpr); g.lineTo(cx, cy + 14 * dpr);
    g.stroke();

    if (this.mode === "slider") {
      const x = this.split * px;
      g.strokeStyle = "#ffb547";
      g.lineWidth = 2 * dpr;
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x, px); g.stroke();
      g.fillStyle = "#ffb547";
      g.fillText("first", 8 * dpr, 18 * dpr);
      g.fillText("this frame", px - 76 * dpr, 18 * dpr);
    }

    if (this.showKnown) {
      for (const obj of this.known) {
        const xy = obj.positions[this.index];
        if (!xy) continue;
        const [x, y] = this.toCanvas(xy[0], xy[1], px);
        g.strokeStyle = "#ffb547";
        g.beginPath(); g.arc(x, y, 11 * dpr, 0, Math.PI * 2); g.stroke();
        g.fillStyle = "#ffb547";
        g.fillText(obj.name, x + 14 * dpr, y - 8 * dpr);
      }
    }
    for (const m of this.markers) {
      g.strokeStyle = m.color;
      g.lineWidth = 2 * dpr;
      if (m.track) {
        const [x0, y0] = this.toCanvas(m.track[0], m.track[1], px);
        const [x1, y1] = this.toCanvas(m.track[2], m.track[3], px);
        g.setLineDash([4 * dpr, 4 * dpr]);
        g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
        g.setLineDash([]);
      }
      if (m.x !== undefined) {
        const [x, y] = this.toCanvas(m.x, m.y, px);
        g.beginPath(); g.arc(x, y, (m.r || 10) * dpr, 0, Math.PI * 2); g.stroke();
      }
    }
  }
}
