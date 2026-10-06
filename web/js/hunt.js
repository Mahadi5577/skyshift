// Hunt tab: practice rounds with a planted fake mover, real rounds that feed the Candidates board.
import { api, loadSequence } from "./api.js";
import { Viewer } from "./viewer.js";

const $ = (s) => document.querySelector(s);
const LEVELS = [12, 8, 6, 5]; // must match backend/hunt.py

let viewer;
let player = "";
let round = null;
let answered = false;
let abort = null;

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private mode: fine without it */ }
  return null;
}

function msg(text, loading = false) {
  const m = $("#hunt-msg");
  m.textContent = text || "";
  m.classList.toggle("hidden", !text);
  m.classList.toggle("loading", loading);
}

function feedback(text, kind = "") {
  const f = $("#hunt-feedback");
  f.textContent = text;
  f.className = `feedback ${kind}`;
}

function stats(skill, streak) {
  $("#st-skill").textContent = skill === undefined ? "-" : `${Math.round(skill * 100)}%`;
  $("#st-streak").textContent = streak ?? "-";
  $("#st-level").textContent = streak === undefined ? "-" : `S/N ${LEVELS[Math.min(Math.floor(streak / 3), LEVELS.length - 1)]}`;
}

// Add a Gaussian "mover" to one frame, scaled to that frame's own noise.
function plant(data, n, x, y, snr, sigma) {
  const vals = Array.from(data).filter(Number.isFinite).sort((a, b) => a - b);
  const med = vals[vals.length >> 1];
  const dev = vals.map((v) => Math.abs(v - med)).sort((a, b) => a - b);
  const amp = snr * 1.4826 * dev[dev.length >> 1];
  const out = new Float32Array(data);
  const r = Math.ceil(sigma * 4);
  for (let row = Math.max(0, Math.floor(y - r)); row <= Math.min(n - 1, Math.ceil(y + r)); row += 1) {
    for (let col = Math.max(0, Math.floor(x - r)); col <= Math.min(n - 1, Math.ceil(x + r)); col += 1) {
      const d2 = (col - x) ** 2 + (row - y) ** 2;
      out[row * n + col] += amp * Math.exp(-d2 / (2 * sigma * sigma));
    }
  }
  return out;
}

async function nextRound() {
  abort?.abort();
  abort = new AbortController();
  answered = false;
  $("#hunt-none").disabled = true;
  $("#hunt-next").disabled = true;
  feedback("");
  viewer.reset(0, []);
  msg("Finding a patch of sky...", true);
  try {
    round = await api.huntRound(player);
  } catch (e) {
    msg(e.status === 404
      ? "Hunt needs downloaded sky patches first. Open a few places in Explore with the Hours or Days zoom (or run scripts/precache.py), then come back."
      : `Error: ${e.message}`);
    return;
  }
  stats(round.skill, round.streak);
  const badge = $("#hunt-badge");
  badge.classList.remove("hidden");
  badge.className = `badge ${round.practice ? "practice" : "real"}`;
  badge.textContent = round.practice ? `Practice: a fake mover is hidden here (S/N ${round.fake.snr})` : "Real data: anything you find is a candidate";

  const seq = await api.status(round.seq_id);
  viewer.reset(seq.n, seq.entries);
  viewer.balance = true;
  viewer.showKnown = false;
  const t = seq.entries.map((e) => e.mjd);
  const t0 = Math.min(...t);
  const span = Math.max(...t) - t0 || 1;
  msg("Loading frames...", true);
  await loadSequence(seq, (i, data) => {
    if (data && round.fake) {
      const f = round.fake;
      const k = (t[i] - t0) / span;
      data = plant(data, seq.n, f.x0 + f.dx * k, f.y0 + f.dy * k, f.snr, f.psf_sigma);
    }
    viewer.setFrame(i, data);
    if (viewer.readyCount()) msg("");
  }, { signal: abort.signal });
  if (!abort.signal.aborted) $("#hunt-none").disabled = false;
}

async function answer(click) {
  if (!round || answered || viewer.readyCount() < 2) return;
  answered = true;
  $("#hunt-none").disabled = true;
  let res;
  try {
    res = await api.huntAnswer(round.round_id, click);
  } catch (e) {
    feedback(`Could not send your answer: ${e.message}`, "bad");
    answered = false;
    return;
  }
  stats(res.skill, res.streak);
  if (click) viewer.markers = [{ x: click[0], y: click[1], color: "#ffffff", r: 7 }];
  if (res.practice) {
    const f = res.fake;
    viewer.markers.push({ track: [f.x0, f.y0, f.x0 + f.dx, f.y0 + f.dy], color: res.found ? "#4fd18b" : "#ff6b6b" });
    feedback(res.found
      ? "Found it! That was a planted practice mover. Your skill score went up."
      : click ? "Not quite. The dashed line shows where the planted mover travelled." : "There was a planted mover: the dashed line shows its path.",
    res.found ? "good" : "bad");
  } else if (res.known_match) {
    feedback(`Nice eye: that is ${res.known_match}, a known solar-system object. Logged on the board.`, "good");
  } else if (res.flagged) {
    feedback("Flag logged on the Candidates board. If other skilled players flag the same spot, it rises to the top.", "good");
  } else {
    feedback("Noted: nothing moving here. Real data is often quiet.");
  }
  viewer.draw();
  $("#hunt-next").disabled = false;
}

export function initHunt() {
  viewer = new Viewer($("#hunt-viewer"), { onClick: ({ x, y }) => answer([x, y]) });
  viewer.fps = 3;
  player = store("skyshift-player") || "";
  $("#player").value = player;
  $("#hunt-start").onsubmit = (e) => {
    e.preventDefault();
    player = $("#player").value.trim();
    if (!player) return;
    store("skyshift-player", player);
    nextRound();
  };
  $("#hunt-none").onclick = () => answer(null);
  $("#hunt-next").onclick = () => nextRound();
}
