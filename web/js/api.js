// Thin wrappers around the SkyShift backend API.

async function call(path, options = {}) {
  const res = await fetch(path, options);
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
const post = (path, body) =>
  json(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  resolve: (q) => json(`/api/resolve?q=${encodeURIComponent(q)}`),
  coverage: (ra, dec) => json(`/api/coverage?ra=${ra}&dec=${dec}`),
  sequence: (req) => post("/api/sequence", req),
  status: (id) => json(`/api/sequence/${id}`),
  known: (id) => json(`/api/sequence/${id}/known`),
  tour: () => json("/api/tour"),
  huntRound: (player) => json(`/api/hunt/round?player=${encodeURIComponent(player)}`),
  huntAnswer: (round_id, click) => post("/api/hunt/answer", { round_id, click }),
  board: () => json("/api/hunt/board"),
  async frame(id, i) {
    const buf = await (await call(`/api/sequence/${id}/frame/${i}`)).arrayBuffer();
    return new Float32Array(buf);
  },
};

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
