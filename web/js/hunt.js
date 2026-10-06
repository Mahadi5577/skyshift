// Hunt tab: practice rounds with a planted fake mover, real rounds that feed the Candidates board.
// The server plants the fake into the frames it sends; the browser learns its track only after answering.
import { api } from "./api.js";
import { Viewer } from "./viewer.js";

const $ = (s) => document.querySelector(s);
const LEVELS = [12, 8, 6, 5]; // must match backend/hunt.py

let viewer;
let player = "";
let key = "";
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

// A random key kept in this browser: the server gives a player name to the first key that uses it.
function playerKey() {
  let k = store("skyshift-player-key");
  if (!k) {
    k = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
    store("skyshift-player-key", k);
  }
  return k;
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
    round = await api.huntRound(player, key);
  } catch (e) {
    msg(e.status === 404
      ? "Hunt needs downloaded sky patches first. Open a few places in Explore with the Hours or Days zoom (or run scripts/precache.py), then come back."
      : e.status === 403 ? "That player name is already taken on this server. Please pick another one."
        : `Error: ${e.message}`);
    return;
  }
  stats(round.skill, round.streak);
  const badge = $("#hunt-badge");
  badge.classList.remove("hidden");
  badge.className = `badge ${round.practice ? "practice" : "real"}`;
  badge.textContent = round.practice ? `Practice: a fake mover is hidden here (S/N ${round.snr})` : "Real data: anything you find is a candidate";

  const { signal } = abort;
  viewer.reset(round.n, round.entries);
  viewer.balance = true;
  viewer.showKnown = false;
  msg("Loading frames...", true);
  await Promise.all(round.entries.map((_, i) => api.huntFrame(round.round_id, i)
    .catch(() => null)
    .then((data) => {
      if (signal.aborted) return;
      viewer.setFrame(i, data);
      if (viewer.readyCount()) msg("");
    })));
  if (signal.aborted) return;
  if (viewer.readyCount()) {
    $("#hunt-none").disabled = false;
  } else {
    msg("These frames could not be loaded. Press Next round.");
    $("#hunt-next").disabled = false;
  }
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
  key = playerKey();
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
