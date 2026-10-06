// Online showcase (static hosting such as GitHub Pages): answers the app's API calls from the
// files that scripts/export_static.py writes under static/. Explore has the tour stops at every
// zoom; Hunt has practice rounds only, scored in this browser.

const BASE = "static";
export const NOT_HERE = "This online showcase only has the guided-tour places. "
  + "Run SkyShift on your computer to explore the whole sky.";

// Must match backend/hunt.py.
const LEVELS = [12, 8, 6, 5];
const PSF_SIGMA = 0.9;
const HIT_RADIUS = 3;
const STATS = "skyshift-showcase-stats";

function notHere(message = NOT_HERE) {
  const err = new Error(message);
  err.status = 404;
  return err;
}

async function get(path) {
  const res = await fetch(`${BASE}/${path}`);
  if (!res.ok) throw notHere();
  return res;
}
const json = (path) => get(path).then((r) => r.json());
const floats = (path) => get(path).then((r) => r.arrayBuffer()).then((b) => new Float32Array(b));

let index = null;
const loadIndex = () => (index ??= json("index.json"));

const fixed = (v, d) => (v === null || v === undefined ? "" : Number(v).toFixed(d));
// Same key as request_key() in scripts/export_static.py.
export const requestKey = (r) => [fixed(r.ra, 5), fixed(r.dec, 5), r.zoom, fixed(r.wave, 3), String(r.n ?? 48),
  fixed(r.tol, 3), fixed(r.t_min, 5), fixed(r.t_max, 5)].join(",");

// --- Hunt practice, scored in this browser ---------------------------------------------------
function loadStats() {
  try {
    return JSON.parse(localStorage.getItem(STATS)) || { rounds: 0, hits: 0, streak: 0 };
  } catch {
    return { rounds: 0, hits: 0, streak: 0 };
  }
}

function saveStats(s) {
  try { localStorage.setItem(STATS, JSON.stringify(s)); } catch { /* private mode: fine without it */ }
}

const skill = (s) => Math.round(((s.hits + 1) / (s.rounds + 2)) * 1000) / 1000;
const rounds = new Map();

// Add a Gaussian mover to one frame, scaled to that frame's own noise (as backend/hunt.py does).
function plant(data, n, x, y, snr, sigma) {
  const vals = Array.from(data).filter(Number.isFinite).sort((a, b) => a - b);
  if (!vals.length) return data;
  const med = vals[vals.length >> 1];
  const dev = vals.map((v) => Math.abs(v - med)).sort((a, b) => a - b);
  const amp = snr * 1.4826 * dev[dev.length >> 1];
  const out = new Float32Array(data);
  const r = sigma * 4;
  for (let row = Math.max(0, Math.floor(y - r)); row <= Math.min(n - 1, Math.ceil(y + r)); row += 1) {
    for (let col = Math.max(0, Math.floor(x - r)); col <= Math.min(n - 1, Math.ceil(x + r)); col += 1) {
      const d2 = (col - x) ** 2 + (row - y) ** 2;
      if (d2 <= r * r) out[row * n + col] += amp * Math.exp(-d2 / (2 * sigma * sigma));
    }
  }
  return out;
}

function distToTrack(f, x, y) {
  const len2 = f.dx ** 2 + f.dy ** 2;
  const t = Math.max(0, Math.min(1, ((x - f.x0) * f.dx + (y - f.y0) * f.dy) / len2));
  return Math.hypot(x - (f.x0 + t * f.dx), y - (f.y0 + t * f.dy));
}

export const staticApi = {
  isStatic: true,
  resolve: async () => { throw notHere(); },
  async coverage(ra, dec) {
    return json(`coverage/${fixed(ra, 5)}_${fixed(dec, 5)}.json`);
  },
  async sequence(req) {
    const id = (await loadIndex()).sequences[requestKey(req)];
    if (!id) throw notHere("This zoom and colour is not in the online showcase. Try the stop's own zoom, or run SkyShift on your computer");
    return json(`seq/${id}.json`);
  },
  status: (id) => json(`seq/${id}.json`),
  known: (id) => json(`seq/${id}/known.json`),
  tour: async () => (await loadIndex()).tour,
  frame: (id, i) => floats(`seq/${id}/${i}.bin`),

  async huntRound() {
    const pool = (await loadIndex()).hunt;
    if (!pool.length) throw notHere("no Hunt patches in this showcase");
    const seq = pool[Math.floor(Math.random() * pool.length)];
    const s = loadStats();
    const snr = LEVELS[Math.min(Math.floor(s.streak / 3), LEVELS.length - 1)];
    const ang = Math.random() * 2 * Math.PI;
    const length = 6 + Math.random() * 4;
    const fake = {
      x0: seq.n * (0.25 + Math.random() * 0.5), y0: seq.n * (0.25 + Math.random() * 0.5),
      dx: length * Math.cos(ang), dy: length * Math.sin(ang), snr, psf_sigma: PSF_SIGMA,
    };
    const id = crypto.getRandomValues(new Uint32Array(2)).join("");
    rounds.set(id, { seq, fake });
    return { round_id: id, practice: true, n: seq.n, zoom: seq.zoom, entries: seq.entries, snr,
      skill: skill(s), streak: s.streak };
  },
  async huntFrame(roundId, i) {
    const { seq, fake } = rounds.get(roundId);
    const t = seq.entries.map((e) => e.mjd);
    const t0 = Math.min(...t);
    const k = (t[i] - t0) / (Math.max(...t) - t0 || 1);
    const data = await floats(`seq/${seq.id}/${i}.bin`);
    return plant(data, seq.n, fake.x0 + fake.dx * k, fake.y0 + fake.dy * k, fake.snr, fake.psf_sigma);
  },
  async huntAnswer(roundId, click) {
    const rnd = rounds.get(roundId);
    if (!rnd || rnd.answered) throw notHere("unknown or already answered round");
    rnd.answered = true;
    const s = loadStats();
    const found = !!click && distToTrack(rnd.fake, click[0], click[1]) <= HIT_RADIUS;
    s.rounds += 1;
    s.hits += found ? 1 : 0;
    s.streak = found ? s.streak + 1 : 0;
    saveStats(s);
    return { practice: true, found, fake: rnd.fake, skill: skill(s), streak: s.streak, rounds: s.rounds };
  },
  board: async () => ({
    candidates: [], players: 0,
    note: "The shared candidate board needs the full app: in this online showcase, Hunt has practice rounds only.",
  }),
};
