// Explore tab: pick a place (tour, search or sky map), choose a time zoom, watch SPHEREx frames.
import { api, loadSequence } from "./api.js";
import { Viewer } from "./viewer.js";

const $ = (s) => document.querySelector(s);
const WAVE_CHOICES = [0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 4.9];

const ZOOM_TEXT = {
  hours: "Frames taken minutes to hours apart. Stars stay fixed; main-belt asteroids crawl a few pixels per hour. SPHEREx steps through colours between exposures, so these frames are brightness-balanced: judge motion, not brightness.",
  days: "Frames from one survey pass, spread over days. Distant bodies such as Pluto, or a hypothetical Planet X, move only a few pixels per day. All frames share one colour, so brightness changes are real.",
  months: "Each frame is the median of up to five images from one survey pass, about six months apart. Moving objects vanish in a median, so what remains is the fixed sky: look for things that brighten, fade or appear.",
  year: "The first and the last survey pass, about a year apart. Fast nearby stars can shift by one or two pixels. Try the Slider or Difference mode.",
};
const MODE_TEXT = {
  blink: "Blink flips through the frames like a flipbook. Your eye is very good at catching what jumps.",
  slider: "Drag across the image: the left side shows the first frame, the right side the current one.",
  diff: "Each frame minus the typical sky here. Orange means brighter now, blue fainter now. Very bright objects are dimmed: they leave false-change patterns even when nothing changed.",
};

const state = { target: null, stop: null, zoom: "days", wave: null, coverage: null, seq: null, abort: null };
let viewer;
let aladin = null;
let overlay = null;

function fmtDate(iso) { return iso.replace("T", " ").slice(0, 16) + " UTC"; }

function fmtDelta(days) {
  const h = days * 24;
  if (h < 1) return `+${Math.round(h * 60)} min`;
  if (h < 48) return `+${Math.floor(h)} h ${Math.round((h % 1) * 60)} min`;
  if (days < 60) return `+${days.toFixed(1)} days`;
  return `+${(days / 30.44).toFixed(1)} months`;
}

function setMsg(text, loading = false) {
  const m = $("#viewer-msg");
  m.textContent = text || "";
  m.classList.toggle("hidden", !text);
  m.classList.toggle("loading", loading);
}

function updateCaption() {
  const seq = state.seq;
  if (!seq || !viewer.frames[viewer.index]) { $("#caption").textContent = ""; return; }
  const i = viewer.index;
  const e = seq.entries[i];
  const parts = [`Frame ${i + 1} of ${seq.entries.length}`];
  if (e.members.length > 1) {
    parts.push(`${e.label} (median of ${e.members.length} images, ${e.date.slice(0, 7)})`);
  } else {
    parts.push(fmtDate(e.date));
    if (i > 0) parts.push(fmtDelta(e.mjd - seq.entries[0].mjd));
    parts.push(`survey pass ${e.pass + 1}`);
  }
  parts.push(`${e.wave.toFixed(2)} µm, detector ${e.det}`);
  $("#caption").textContent = parts.join("  ·  ");
  document.querySelectorAll("#timeline .tick").forEach((t, k) => t.classList.toggle("current", k === i));
}

function renderTimeline() {
  const tl = $("#timeline");
  tl.innerHTML = "";
  const seq = state.seq;
  if (!seq) return;
  const t = seq.entries.map((e) => e.mjd);
  const span = Math.max(...t) - Math.min(...t) || 1;
  // Place ticks by time, but keep them at least `gap` apart so frames minutes apart stay clickable.
  const gap = Math.min(2.5, 92 / Math.max(1, t.length - 1));
  const pos = [];
  t.forEach((ti, i) => pos.push(Math.max(92 * ((ti - t[0]) / span), i ? pos[i - 1] + gap : 0)));
  const scale = pos.length && pos[pos.length - 1] > 92 ? 92 / pos[pos.length - 1] : 1;
  seq.entries.forEach((e, i) => {
    const b = document.createElement("button");
    b.className = "tick";
    b.style.left = `${4 + pos[i] * scale}%`;
    b.title = `${fmtDate(e.date)}, ${e.wave.toFixed(2)} µm`;
    b.setAttribute("aria-label", `Frame ${i + 1}`);
    b.onclick = () => viewer.goto(i);
    tl.append(b);
  });
  refreshTicks();
}

function refreshTicks() {
  document.querySelectorAll("#timeline .tick").forEach((t, i) => {
    t.classList.toggle("ready", !!viewer.frames[i]);
    t.classList.toggle("failed", viewer.failed.has(i));
  });
}

function explain() {
  const stop = state.stop && state.stop.zoom === state.zoom ? state.stop : null;
  $("#explain-title").textContent = stop ? stop.title : "How to read this";
  const body = $("#explain-body");
  body.innerHTML = "";
  for (const text of [stop?.blurb, ZOOM_TEXT[state.zoom], MODE_TEXT[viewer.mode]]) {
    if (!text) continue;
    const p = document.createElement("p");
    p.textContent = text;
    body.append(p);
  }
}

function renderKnown(objects, note) {
  const ul = $("#known-list");
  ul.innerHTML = "";
  if (note) { ul.innerHTML = `<li>${note}</li>`; return; }
  for (const o of objects) {
    const li = document.createElement("li");
    li.innerHTML = `<b></b> known ${o.type.includes("MB") ? "main-belt asteroid" : "solar-system object"}, brightness V ${o.V.toFixed(1)}, moving ${o.rate}″ per hour`;
    li.querySelector("b").textContent = o.name;
    ul.append(li);
  }
}

function fillWaveSelect() {
  const sel = $("#wave");
  sel.innerHTML = "";
  const imgs = state.coverage?.images || [];
  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = `Auto (${state.coverage?.suggested?.[state.zoom]?.toFixed(2) ?? "-"} µm)`;
  sel.append(auto);
  for (const w of WAVE_CHOICES) {
    const m = imgs.filter((im) => Math.abs(im.wave - w) / w < 0.02);
    if (!m.length) continue;
    const passes = new Set(m.map((im) => im.pass)).size;
    const o = document.createElement("option");
    o.value = w;
    o.textContent = `${w.toFixed(2)} µm (${m.length} images, ${passes} passes)`;
    sel.append(o);
  }
  if (state.wave && ![...sel.options].some((o) => +o.value === state.wave)) {
    const o = document.createElement("option");
    o.value = state.wave;
    o.textContent = `${state.wave.toFixed(2)} µm (tour)`;
    sel.append(o);
  }
  sel.value = state.wave ?? "";
}

function moveMap() {
  if (!aladin || !state.target) return;
  try {
    aladin.gotoRaDec(state.target.ra, state.target.dec);
    overlay.removeAll();
    overlay.add(A.circle(state.target.ra, state.target.dec, ((state.seq?.n || 48) * 6.15) / 3600 / 2));
  } catch (e) { console.warn("sky map", e); }
}

export async function setTarget(target, { stop = null, zoom = null } = {}) {
  state.target = target;
  state.stop = stop;
  state.wave = stop?.wave ?? null;
  if (zoom || stop) setZoom(zoom || stop.zoom, false);
  document.querySelectorAll("#tour button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === stop?.id)));
  $("#target-name").textContent = stop ? stop.title : target.name;
  $("#target-sub").textContent = `RA ${target.ra.toFixed(4)}°, Dec ${target.dec.toFixed(4)}°`;
  history.replaceState(null, "", `#t=${target.ra.toFixed(5)},${target.dec.toFixed(5)}&z=${state.zoom}${stop ? `&s=${stop.id}` : ""}`);
  moveMap();
  $("#cov-pill").classList.add("hidden");
  setMsg("Asking the NASA archive which SPHEREx images cover this spot...", true);
  try {
    state.coverage = await api.coverage(target.ra, target.dec);
  } catch (e) {
    setMsg(`Could not search the archive: ${e.message}`);
    return;
  }
  const c = state.coverage;
  const pill = $("#cov-pill");
  pill.textContent = `${c.images.length} images · ${c.passes.length} survey passes`;
  pill.classList.remove("hidden");
  fillWaveSelect();
  if (!c.images.length) {
    setMsg("SPHEREx has not released images of this spot yet. Try another place.");
    return;
  }
  await loadSeq();
}

async function loadSeq() {
  state.abort?.abort();
  const abort = new AbortController();
  state.abort = abort;
  const stop = state.stop && state.stop.zoom === state.zoom ? state.stop : null;
  const req = { ra: state.target.ra, dec: state.target.dec, zoom: state.zoom };
  if (state.wave) req.wave = state.wave;
  if (stop) Object.assign(req, { n: stop.n, tol: stop.tol, t_min: stop.t_min, t_max: stop.t_max });
  viewer.reset(0, []);
  state.seq = null;
  renderTimeline();
  renderKnown([]);
  explain();
  setMsg("Choosing frames...", true);
  let seq;
  try {
    seq = await api.sequence(req);
  } catch (e) {
    setMsg(e.status === 404 ? `${e.message}. Try another zoom level or colour.` : `Error: ${e.message}`);
    return;
  }
  if (abort.signal.aborted) return;
  state.seq = seq;
  viewer.reset(seq.n, seq.entries);
  viewer.balance = seq.balanced;
  $("#balance").checked = seq.balanced;
  renderTimeline();
  moveMap();
  setMsg(`Downloading ${seq.entries.length} frames from NASA's archive...`, true);
  api.known(seq.id).then((k) => {
    if (abort.signal.aborted) return;
    viewer.known = k.objects;
    renderKnown(k.objects, k.note);
    viewer.draw();
  }).catch(() => renderKnown([], "Known-object lookup (SkyBoT) is unavailable right now."));
  await loadSequence(seq, (i, data) => {
    viewer.setFrame(i, data);
    refreshTicks();
    if (viewer.readyCount() >= 1) setMsg("");
    updateCaption();
  }, { signal: abort.signal });
  if (!abort.signal.aborted && !viewer.readyCount()) setMsg("These frames could not be downloaded. Try again or pick another zoom.");
}

function setZoom(z, reload = true) {
  state.zoom = z;
  document.querySelectorAll(".zoom button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.zoom === z)));
  if (reload && state.target) {
    history.replaceState(null, "", location.hash.replace(/z=\w+/, `z=${z}`));
    fillWaveSelect();
    loadSeq();
  }
}

function setMode(m) {
  viewer.mode = m;
  document.querySelectorAll(".seg [data-mode]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === m)));
  viewer.draw();
  explain();
}

function initAladin() {
  const start = () => A.init.then(() => {
    // SPHEREx QR2 all-sky colour map (HiPS by CDS from the six detectors); 2MASS as an alternative.
    aladin = A.aladin("#aladin", {
      survey: $("#map-survey").value, fov: 1.5, target: "202.4696 47.1952", showReticle: true,
      showLayersControl: false, showGotoControl: false, showFullscreenControl: false,
      showFrame: false, showCooGrid: false,
    });
    $("#map-survey").onchange = (e) => aladin.setImageSurvey(e.target.value);
    overlay = A.graphicOverlay({ color: "#ffb547", lineWidth: 2 });
    aladin.addOverlay(overlay);
    moveMap();
  });
  if (window.A) start();
  else window.addEventListener("load", () => (window.A ? start() : ($("#aladin").textContent = "Sky map unavailable offline.")));
}

export async function initExplore() {
  viewer = new Viewer($("#viewer"));
  viewer.onStep = updateCaption;

  document.querySelectorAll(".zoom button").forEach((b) => (b.onclick = () => setZoom(b.dataset.zoom)));
  document.querySelectorAll(".seg [data-mode]").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  $("#play").onclick = () => {
    viewer.playing = !viewer.playing;
    $("#play").innerHTML = viewer.playing ? "&#10074;&#10074;" : "&#9654;";
  };
  $("#prev").onclick = () => viewer.step(-1);
  $("#next").onclick = () => viewer.step(1);
  $("#speed").oninput = (e) => (viewer.fps = +e.target.value);
  $("#contrast").oninput = (e) => { viewer.contrast = +e.target.value; viewer.draw(); };
  $("#balance").onchange = (e) => { viewer.balance = e.target.checked; viewer.template = null; viewer.draw(); };
  $("#known").onchange = (e) => { viewer.showKnown = e.target.checked; viewer.draw(); };
  $("#wave").onchange = (e) => { state.wave = e.target.value ? +e.target.value : null; loadSeq(); };

  $("#search").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#q").value.trim();
    setMsg(`Looking up "${q}"...`, true);
    try {
      await setTarget(await api.resolve(q));
    } catch (err) {
      setMsg(err.message);
    }
  };
  $("#use-center").onclick = () => {
    if (!aladin) return;
    const [ra, dec] = aladin.getRaDec();
    setTarget({ name: `RA ${ra.toFixed(3)}°, Dec ${dec.toFixed(3)}°`, ra, dec });
  };
  document.addEventListener("keydown", (e) => {
    if ($("#tab-explore").classList.contains("hidden") || e.target.closest("input, select, textarea")) return;
    if (e.key === "ArrowRight") viewer.step(1);
    else if (e.key === "ArrowLeft") viewer.step(-1);
    else if (e.key === " ") { e.preventDefault(); $("#play").click(); }
  });

  initAladin();
  explain();
  const stops = await api.tour().catch(() => []);
  const list = $("#tour");
  stops.forEach((s, k) => {
    const li = document.createElement("li");
    li.innerHTML = `<button data-id="${s.id}"><b></b><span>${k + 1}. ${s.zoom} zoom</span></button>`;
    li.querySelector("b").textContent = s.title;
    li.querySelector("button").onclick = () => setTarget({ name: s.title, ra: s.ra, dec: s.dec }, { stop: s });
    list.append(li);
  });
  return stops;
}

// "#t=ra,dec&z=zoom&s=stop" -> open that view.
export function openFromHash(stops) {
  const h = new URLSearchParams(location.hash.slice(1));
  const stop = stops.find((s) => s.id === h.get("s"));
  if (stop) return setTarget({ name: stop.title, ra: stop.ra, dec: stop.dec }, { stop });
  const t = (h.get("t") || "").split(",").map(Number);
  if (t.length === 2 && t.every(Number.isFinite)) {
    return setTarget({ name: `RA ${t[0].toFixed(3)}°, Dec ${t[1].toFixed(3)}°`, ra: t[0], dec: t[1] },
      { zoom: h.get("z") || "days" });
  }
  return null;
}
