// Thin wrappers around the SkyShift backend API. In the online showcase (a static copy made by
// scripts/export_static.py) the same calls are answered from files instead: see static.js.
import { staticApi } from "./static.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function call(path, options = {}, retries = 3) {
  const res = await fetch(path, options);
  // 503 = the server is at its download limit; it says when to come back.
  if (res.status === 503 && retries > 0) {
    await sleep(1000 * Math.min(30, Number(res.headers.get("Retry-After")) || 10));
    return call(path, options, retries - 1);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return res;
}

const json = (path, options) => call(path, options).then((r) => r.json());
const floats = (path) => call(path).then((r) => r.arrayBuffer()).then((b) => new Float32Array(b));
const post = (path, body) =>
  json(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const serverApi = {
  isStatic: false,
  resolve: (q) => json(`/api/resolve?q=${encodeURIComponent(q)}`),
  coverage: (ra, dec) => json(`/api/coverage?ra=${ra}&dec=${dec}`),
  sequence: (req) => post("/api/sequence", req),
  status: (id) => json(`/api/sequence/${id}`),
  known: (id) => json(`/api/sequence/${id}/known`),
  tour: () => json("/api/tour"),
  huntRound: (player, key) => json(`/api/hunt/round?player=${encodeURIComponent(player)}&key=${key}`),
  huntAnswer: (round_id, click) => post("/api/hunt/answer", { round_id, click }),
  board: () => json("/api/hunt/board"),
  frame: (id, i) => floats(`/api/sequence/${id}/frame/${i}`),
  huntFrame: (roundId, i) => floats(`/api/hunt/round/${roundId}/frame/${i}`),
};

export const api = document.querySelector('meta[name="skyshift-static"]') ? staticApi : serverApi;

// Poll a sequence until every frame is ready or failed; calls onFrame(i, data) as each arrives.
export async function loadSequence(seq, onFrame, { signal, interval = 1200 } = {}) {
  const done = new Set();
  let status = seq.status;
  for (;;) {
    if (signal?.aborted) return;
    const fetches = [];
    status.forEach((s, i) => {
      if (s === "ready" && !done.has(i)) {
        done.add(i);
        fetches.push(api.frame(seq.id, i).then((d) => !signal?.aborted && onFrame(i, d)));
      } else if (s === "failed" && !done.has(i)) {
        done.add(i);
        onFrame(i, null);
      }
    });
    await Promise.all(fetches);
    if (done.size === status.length) return;
    await new Promise((r) => setTimeout(r, interval));
    status = (await api.status(seq.id)).status;
  }
}
